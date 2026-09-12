import { useEffect, useMemo, useRef, useState } from "preact/hooks";

import {
  browseFiles,
  browseFolder,
  cancelRun,
  clearCache,
  clearHistory,
  fetchDocumentPreview,
  fetchHistory,
  fetchInspector,
  fetchPdfPage,
  fetchRunSummary,
  fetchState,
  intakePaths,
  previewPlan,
  revealRun,
  startRun,
  submitReview,
  subscribeState,
  type StateStream,
} from "./api";
import type {
  ActionParameterView,
  ApplicationViewState,
  AvailableActionView,
  DocumentPreviewData,
  InputItemView,
  InputSelectionView,
  InspectorViewState,
  PlanPreview,
  PreflightView,
  ReviewItemView,
  RunRequest,
  RunSummaryView,
  TerminalRunHistoryView,
} from "./types";

type Screen = "home" | "monitor" | "review" | "summary" | "inspector";
type InputFilter = "all" | "eligible" | "issues";

const screens: readonly { id: Screen; label: string }[] = [
  { id: "home", label: "Home" },
  { id: "monitor", label: "Monitor" },
  { id: "review", label: "Review" },
  { id: "summary", label: "Summary" },
  { id: "inspector", label: "Inspector" },
];

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === 0) return "0 B";
  if (!Number.isFinite(bytes) || !bytes || bytes < 0) return "—";
  const units = ["B", "KB", "MB", "GB"] as const;
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatDuration(ns: number | null | undefined): string {
  if (ns === 0) return "0.0 s";
  if (!Number.isFinite(ns) || !ns || ns < 0) return "—";
  const seconds = ns / 1_000_000_000;
  if (seconds < 1) return `${Math.round(ns / 1_000_000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export function formatConfidence(value: number | null | undefined): string {
  if (value === 0) return "0.0%";
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

export function formatStatus(status: string | null | undefined): { label: string; badgeClass: string } {
  if (!status) return { label: "—", badgeClass: "badge-slate" };
  const upper = status.toUpperCase();
  switch (upper) {
    case "SUCCESS":
      return { label: "Run Completed Successfully", badgeClass: "badge-emerald" };
    case "RUNNING":
      return { label: "Running", badgeClass: "badge-indigo" };
    case "CANCELLED":
      return { label: "Run Cancelled", badgeClass: "badge-crimson" };
    case "FAILED":
      return { label: "Run Failed (FAILED)", badgeClass: "badge-crimson" };
    case "WARNING":
    case "PARTIAL":
      return { label: "Completed with Warnings", badgeClass: "badge-amber" };
    case "QUARANTINED":
      return { label: "Run Quarantined", badgeClass: "badge-crimson" };
    default:
      return { label: `Unknown (${upper})`, badgeClass: "badge-slate" };
  }
}

export function formatSummaryTitle(status: string): string {
  switch (status) {
    case "SUCCESS": return "Run Completed Successfully";
    case "WARNING":
    case "PARTIAL": return "Run Completed with Warnings";
    case "CANCELLED": return "Run Cancelled";
    case "QUARANTINED": return "Run Quarantined";
    default: return `Run Failed (${status})`;
  }
}

if (typeof window !== "undefined") {
  (window as any).__formatters = {
    formatDuration,
    formatConfidence,
    formatBytes,
    formatStatus,
  };
  (window as any).__formatSummaryTitle = formatSummaryTitle;
}

function Metric({ label, value, detail }: { label: string; value: string | number; detail?: string }) {
  return (
    <article class="metric">
      <span class="metric__label">{label}</span>
      <strong>{value}</strong>
      {detail ? <span class="metric__detail">{detail}</span> : null}
    </article>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div class="empty-state">
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

function actionDefaults(action: AvailableActionView | undefined): Record<string, unknown> {
  const defaults: Record<string, unknown> = {};
  for (const parameter of action?.parameters ?? []) defaults[parameter.parameter_id] = parameter.default_value;
  return defaults;
}

function ActionParameter({
  parameter,
  value,
  onChange,
}: {
  parameter: ActionParameterView;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const inputId = `param-${parameter.parameter_id}`;
  if (parameter.kind === "toggle") {
    return (
      <label class="toggle-row">
        <input id={inputId} type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.currentTarget.checked)} />
        <span>
          <strong>{parameter.display_name}</strong>
          {parameter.description ? <small>{parameter.description}</small> : null}
        </span>
      </label>
    );
  }
  if (parameter.kind === "select") {
    return (
      <label class="field">
        <span>{parameter.display_name}</span>
        <select id={inputId} value={String(value ?? "")} onChange={(event) => onChange(event.currentTarget.value)} onInput={(event) => onChange(event.currentTarget.value)}>
          {parameter.options.map(([optionValue, label]) => (
            <option value={optionValue} key={optionValue}>{label}</option>
          ))}
        </select>
      </label>
    );
  }
  return (
    <label class="field">
      <span>{parameter.display_name}</span>
      <input id={inputId} value={String(value ?? "")} onInput={(event) => onChange(event.currentTarget.value)} />
    </label>
  );
}

function CommandPalette({
  open,
  onClose,
  commands,
}: {
  open: boolean;
  onClose: () => void;
  commands: readonly { id: string; label: string; action: () => void }[];
}) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.label.toLowerCase().includes(q));
  }, [commands, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  if (!open) return null;

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((idx) => (filtered.length ? (idx + 1) % filtered.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((idx) => (filtered.length ? (idx - 1 + filtered.length) % filtered.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const cmd = filtered[selectedIndex];
      if (cmd) {
        onClose();
        cmd.action();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  return (
    <div class="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <dialog id="command-palette-dialog" class="palette-dialog" open aria-modal="true" aria-label="Command Palette">
        <div class="palette-content">
          <input
            ref={inputRef}
            id="palette-search-input"
            class="palette-search"
            placeholder="Type a command or jump to screen (F1-F5)..."
            autocomplete="off"
            value={query}
            onInput={(e) => setQuery(e.currentTarget.value)}
            onKeyDown={handleKeyDown}
          />
          <div id="palette-command-list" class="palette-list">
            {filtered.length === 0 ? (
              <div class="palette-item empty">No matching commands found.</div>
            ) : (
              filtered.map((cmd, idx) => (
                <button
                  key={cmd.id}
                  class={idx === selectedIndex ? "palette-item active" : "palette-item"}
                  data-index={idx}
                  onClick={() => {
                    onClose();
                    cmd.action();
                  }}
                  type="button"
                >
                  <span>{cmd.label}</span>
                </button>
              ))
            )}
          </div>
        </div>
      </dialog>
    </div>
  );
}

function DocumentPreviewModal({
  target,
  onClose,
}: {
  target: { pathOrUrl: string; displayName: string } | null;
  onClose: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<DocumentPreviewData | null>(null);
  const [pdfPage, setPdfPage] = useState(1);
  const [pdfZoom, setPdfZoom] = useState(1.0);
  const [pdfTab, setPdfTab] = useState<"canvas" | "native" | "text">("canvas");
  const [imageZoom, setImageZoom] = useState(1.0);
  const [textWrap, setTextWrap] = useState(false);
  const [textSearch, setTextSearch] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!target) {
      setData(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    setData(null);
    setPdfPage(1);
    setPdfZoom(1.0);
    setPdfTab("canvas");
    setImageZoom(1.0);
    setTextWrap(false);
    setTextSearch("");
    setCopied(false);

    void fetchDocumentPreview(target.pathOrUrl)
      .then((res) => {
        setData(res);
        setPdfPage(res.current_page || 1);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load document preview.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [target]);

  if (!target) return null;

  const endpoint = target.pathOrUrl;
  let rawUrl = "";
  if (endpoint.includes("/api/inputs/")) {
    rawUrl = endpoint.replace("/preview", "/raw");
  } else if (endpoint.includes("/api/runs/") && endpoint.includes("/artifacts/")) {
    rawUrl = endpoint.replace("/preview", "/raw");
  } else {
    const p = data?.raw_path || endpoint;
    rawUrl = `/api/preview/raw?path=${encodeURIComponent(p)}`;
  }

  const loadPdfPage = async (page: number) => {
    let pageUrl = "";
    if (endpoint.includes("/api/inputs/")) {
      pageUrl = endpoint.replace("/preview", `/pdf_page?page=${page}`);
    } else if (endpoint.includes("/api/runs/") && endpoint.includes("/artifacts/")) {
      pageUrl = endpoint.replace("/preview", `/pdf_page?page=${page}`);
    } else {
      const p = data?.raw_path || endpoint;
      pageUrl = `/api/preview/pdf_page?path=${encodeURIComponent(p)}&page=${page}`;
    }
    setLoading(true);
    try {
      const pageRes = await fetchPdfPage(pageUrl);
      if (pageRes.page_data_url) {
        setData((prev) => (prev ? { ...prev, current_page: page, page_data_url: pageRes.page_data_url, page_text: pageRes.page_text } : null));
        setPdfPage(page);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load PDF page.");
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = (text: string) => {
    void navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const totalPages = data?.page_count || 1;

  const renderHighlightedContent = (raw: string, filter: string) => {
    if (!filter.trim()) return raw;
    const parts: (string | preact.JSX.Element)[] = [];
    const escaped = filter.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp(`(${escaped})`, "gi");
    let lastIdx = 0;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(raw)) !== null) {
      if (match.index > lastIdx) parts.push(raw.slice(lastIdx, match.index));
      parts.push(<mark key={match.index} style={{ background: "var(--warning)", color: "#000", borderRadius: "2px" }}>{match[0]}</mark>);
      lastIdx = match.index + match[0].length;
    }
    if (lastIdx < raw.length) parts.push(raw.slice(lastIdx));
    return parts;
  };

  return (
    <div class="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <dialog id="doc-preview-dialog" class="preview-modal-dialog" open aria-modal="true" aria-label="Document Preview">
        <div class="preview-modal-header">
          <h3 id="preview-modal-title">{target.displayName || "Document Preview"}</h3>
          <button id="btn-close-preview" class="button ghost small" onClick={onClose} type="button" aria-label="Close Preview">✕ Close</button>
        </div>
        <div id="preview-modal-content" class="preview-modal-content">
          {loading && !data ? (
            <div class="loading compact"><div class="spinner" /><strong>Loading preview…</strong></div>
          ) : error ? (
            <div>
              <div class="inline-error" style={{ marginBottom: "16px" }}>{error}</div>
              <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                <a href={rawUrl} target="_blank" class="button primary small">↗ Open in Browser Tab</a>
                <a href={`${rawUrl}?download=1`} download class="button secondary small">⤓ Download</a>
                <button class="button ghost small" onClick={onClose} type="button">✕ Close</button>
              </div>
            </div>
          ) : !data ? null : (
            <>
              {data.type === "pdf" && (
                <div>
                  <div class="doc-preview-toolbar">
                    <div class="doc-page-indicator">
                      <button id="btn-pdf-prev" class="button ghost small" disabled={pdfPage <= 1 || loading} onClick={() => void loadPdfPage(pdfPage - 1)} type="button">◀ Prev</button>
                      <span>Page <strong id="pdf-curr-page-text">{pdfPage}</strong> of <strong>{totalPages}</strong></span>
                      <button id="btn-pdf-next" class="button ghost small" disabled={pdfPage >= totalPages || loading} onClick={() => void loadPdfPage(pdfPage + 1)} type="button">Next ▶</button>
                    </div>
                    <div class="doc-preview-tabs">
                      <button id="tab-btn-pdf-canvas" class={pdfTab === "canvas" ? "doc-preview-tab-btn active" : "doc-preview-tab-btn"} onClick={() => setPdfTab("canvas")} type="button">🖼️ Rendered Page</button>
                      <button id="tab-btn-pdf-native" class={pdfTab === "native" ? "doc-preview-tab-btn active" : "doc-preview-tab-btn"} onClick={() => setPdfTab("native")} type="button">🌐 Browser Viewer</button>
                      <button id="tab-btn-pdf-text" class={pdfTab === "text" ? "doc-preview-tab-btn active" : "doc-preview-tab-btn"} onClick={() => setPdfTab("text")} type="button">📝 Page Text</button>
                    </div>
                    <div class="button-row">
                      <button id="btn-pdf-zoom-in" class="button secondary small" onClick={() => setPdfZoom((z) => Math.min(3.0, z + 0.25))} title="Zoom In" type="button">➕</button>
                      <button id="btn-pdf-zoom-out" class="button secondary small" onClick={() => setPdfZoom((z) => Math.max(0.5, z - 0.25))} title="Zoom Out" type="button">➖</button>
                      <button id="btn-pdf-zoom-reset" class="button secondary small" onClick={() => setPdfZoom(1.0)} title="Reset Zoom" type="button">Reset</button>
                      <a href={rawUrl} target="_blank" class="button ghost small" title="Open in dedicated browser tab">↗ Open Tab</a>
                      <a href={`${rawUrl}?download=1`} download class="button secondary small" title="Download file">⤓ Download</a>
                    </div>
                  </div>
                  <div id="pdf-pane-canvas" class="preview-canvas-container" style={{ display: pdfTab === "canvas" ? "flex" : "none" }}>
                    <img id="pdf-page-image" src={data.page_data_url || ""} alt={`Page ${pdfPage}`} style={{ transform: `scale(${pdfZoom})` }} />
                  </div>
                  <div id="pdf-pane-native" style={{ display: pdfTab === "native" ? "block" : "none", width: "100%" }}>
                    <iframe src={rawUrl} style={{ width: "100%", height: "560px", border: "1px solid var(--border)", borderRadius: "8px", background: "#ffffff" }} title="Native PDF Viewer" />
                  </div>
                  <div id="pdf-pane-text" style={{ display: pdfTab === "text" ? "block" : "none", width: "100%" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                      <span class="quiet">Extracted text layer for current page</span>
                      <button id="btn-copy-pdf-page-text" class="button secondary small" onClick={() => copyToClipboard(data.page_text || "")} type="button">
                        {copied ? "✓ Copied!" : "📋 Copy Page Text"}
                      </button>
                    </div>
                    <pre id="pdf-page-text-content" style={{ fontFamily: "monospace", fontSize: "12px", lineHeight: "1.6", whiteSpace: "pre-wrap", wordBreak: "break-word", background: "var(--surface-soft)", padding: "16px", borderRadius: "8px", maxHeight: "500px", overflowY: "auto" }}>
                      {data.page_text || "(No text detected on this page)"}
                    </pre>
                  </div>
                </div>
              )}

              {data.type === "word" && (
                <div>
                  <div class="doc-preview-toolbar">
                    <div class="doc-page-indicator">
                      <span>Word Document · <strong>{data.total_paragraphs ?? data.paragraphs?.length ?? 0}</strong> paragraphs{data.tables?.length ? ` · ${data.tables.length} tables` : ""} ({formatBytes(data.size)})</span>
                    </div>
                    <div class="button-row">
                      <button id="btn-copy-word-text" class="button secondary small" onClick={() => copyToClipboard((data.paragraphs || []).join("\n\n"))} type="button">
                        {copied ? "✓ Copied!" : "📋 Copy Text"}
                      </button>
                      <a href={`${rawUrl}?download=1`} download class="button primary small">⤓ Download (.docx)</a>
                    </div>
                  </div>
                  <div class="word-doc-sheet">
                    {(data.paragraphs && data.paragraphs.length > 0) ? (
                      data.paragraphs.map((para, i) => <p key={i} style={{ marginBottom: "12px", textAlign: "justify" }}>{para}</p>)
                    ) : (
                      <p class="quiet">(Empty document or no readable paragraphs)</p>
                    )}
                    {data.tables?.map((table, tIdx) => (
                      <div key={tIdx} style={{ margin: "20px 0" }}>
                        <div style={{ fontSize: "11px", color: "var(--muted)", marginBottom: "6px" }}>Table {tIdx + 1}</div>
                        <table class="data-table">
                          {table.headers?.length ? (
                            <thead><tr>{table.headers.map((h, hIdx) => <th key={hIdx}>{h}</th>)}</tr></thead>
                          ) : null}
                          <tbody>
                            {table.rows?.map((row, rIdx) => (
                              <tr key={rIdx}>{row.map((cell, cIdx) => <td key={cIdx}>{cell}</td>)}</tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {data.type === "text" && (
                <div>
                  <div class="doc-preview-toolbar">
                    <div class="doc-page-indicator">
                      <span>Text File · <strong>{(data.content || "").split("\n").length}</strong> lines ({formatBytes(data.size)}){data.truncated ? " · (Truncated to 256KB)" : ""}</span>
                    </div>
                    <div class="button-row">
                      <input id="txt-search-input" class="search-input" style={{ width: "160px", minHeight: "29px", padding: "4px 8px", fontSize: "12px" }} placeholder="Find in text…" value={textSearch} onInput={(e) => setTextSearch(e.currentTarget.value)} />
                      <button id="btn-toggle-wrap" class="button secondary small" onClick={() => setTextWrap((w) => !w)} type="button">↔ Wrap: {textWrap ? "On" : "Off"}</button>
                      <button id="btn-copy-text" class="button secondary small" onClick={() => copyToClipboard(data.content || "")} type="button">{copied ? "✓ Copied!" : "📋 Copy Content"}</button>
                      <a href={`${rawUrl}?download=1`} download class="button ghost small">⤓ Download</a>
                    </div>
                  </div>
                  <pre id="txt-code-block" style={{ fontFamily: "monospace", fontSize: "12px", lineHeight: "1.6", whiteSpace: textWrap ? "pre-wrap" : "pre", wordBreak: textWrap ? "break-word" : "normal", background: "var(--surface-soft)", padding: "16px", borderRadius: "8px", maxHeight: "520px", overflow: "auto", border: "1px solid var(--border)" }}>
                    <code id="txt-code-content">{renderHighlightedContent(data.content || "", textSearch)}</code>
                  </pre>
                </div>
              )}

              {data.type === "tabular" && (
                <div>
                  <div class="doc-preview-toolbar">
                    <div class="doc-page-indicator">
                      <span>Tabular Data · Showing {data.rows?.length ?? 0} rows ({formatBytes(data.size)})</span>
                    </div>
                    <div class="button-row">
                      <a href={`${rawUrl}?download=1`} download class="button primary small">⤓ Download Table</a>
                    </div>
                  </div>
                  <div style={{ maxHeight: "520px", overflow: "auto", border: "1px solid var(--border)", borderRadius: "8px" }}>
                    <table class="data-table">
                      {data.headers?.length ? (
                        <thead><tr>{data.headers.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
                      ) : null}
                      <tbody>
                        {data.rows?.map((row, rIdx) => (
                          <tr key={rIdx}>{row.map((c, cIdx) => <td key={cIdx}>{c}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {data.type === "image" && (
                <div>
                  <div class="doc-preview-toolbar">
                    <div class="doc-page-indicator">
                      <span>Image ({formatBytes(data.size)})</span>
                    </div>
                    <div class="button-row">
                      <button id="btn-zoom-in" class="button secondary small" onClick={() => setImageZoom((z) => Math.min(3.0, z + 0.25))} type="button">➕</button>
                      <button id="btn-zoom-out" class="button secondary small" onClick={() => setImageZoom((z) => Math.max(0.5, z - 0.25))} type="button">➖</button>
                      <button id="btn-zoom-reset" class="button secondary small" onClick={() => setImageZoom(1.0)} type="button">Reset</button>
                      <a href={`${rawUrl}?download=1`} download class="button primary small">⤓ Download</a>
                    </div>
                  </div>
                  <div class="preview-canvas-container">
                    <img id="preview-img" src={data.data_url || ""} alt="Preview" style={{ transform: `scale(${imageZoom})`, transition: "transform 0.15s ease" }} />
                  </div>
                </div>
              )}

              {(data.type === "binary" || (!["pdf", "word", "text", "tabular", "image"].includes(data.type || ""))) && (
                <div style={{ textAlign: "center", padding: "40px" }}>
                  <div style={{ fontSize: "48px", marginBottom: "12px" }}>📦</div>
                  <h3>{data.name || target.displayName}</h3>
                  <p class="quiet" style={{ margin: "8px 0 16px 0" }}>Binary file ({formatBytes(data.size)})</p>
                  <a href={`${rawUrl}?download=1`} download class="button primary small">⤓ Download File</a>
                </div>
              )}
            </>
          )}
        </div>
      </dialog>
    </div>
  );
}

export type PrimaryTaskId =
  | "documents_extraction"
  | "bank_consolidation"
  | "font_conversion"
  | "translation";

export interface PrimaryTaskDef {
  id: PrimaryTaskId;
  label: string;
  icon: string;
  description: string;
}

export const PRIMARY_TASKS: readonly PrimaryTaskDef[] = [
  {
    id: "documents_extraction",
    label: "Documents Extraction",
    icon: "📄",
    description: "Native extraction, local OCR, or cloud document AI",
  },
  {
    id: "bank_consolidation",
    label: "Bank Account Consolidation",
    icon: "🏦",
    description: "Financial table extraction & transaction reconciliation",
  },
  {
    id: "font_conversion",
    label: "Font Conversion",
    icon: "🔤",
    description: "Legacy Hindi typewriter font to/from Unicode conversion",
  },
  {
    id: "translation",
    label: "Translation",
    icon: "🌐",
    description: "Local neural or cloud translation between Hindi and English",
  },
];

export function isCloudAction(actionId: string): boolean {
  return (
    actionId.startsWith("gemini_") ||
    actionId.startsWith("azure_") ||
    actionId.startsWith("mistral_") ||
    actionId.startsWith("bhashini_") ||
    actionId.includes("cloud")
  );
}

function Home({
  state,
  onStarted,
  onError,
  onPreview,
}: {
  state: ApplicationViewState;
  onStarted: (runId: string) => void;
  onError: (message: string | null) => void;
  onPreview: (pathOrUrl: string, displayName: string) => void;
}) {
  const initialRoots = state.input_selection.items.flatMap((item) => item.source_path ? [item.source_path] : []);

  const [roots, setRoots] = useState<string[]>(initialRoots);
  const [selection, setSelection] = useState<InputSelectionView>(state.input_selection);
  const [preflight, setPreflight] = useState<PreflightView | null>(state.preflight);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [checkedPaths, setCheckedPaths] = useState<Set<string>>(new Set());
  const excludedRef = useRef(excluded);
  excludedRef.current = excluded;
  const checkedPathsRef = useRef(checkedPaths);
  checkedPathsRef.current = checkedPaths;
  const [showAllInputsTable, setShowAllInputsTable] = useState(false);
  const [intakeExpanded, setIntakeExpanded] = useState(true);
  const [recursive, setRecursive] = useState(false);
  const [manualPath, setManualPath] = useState("");

  const [primaryTask, setPrimaryTask] = useState<PrimaryTaskId | null>(null);

  const [subtaskByPrimary, setSubtaskByPrimary] = useState<Record<PrimaryTaskId, string>>(() => ({
    documents_extraction: state.requirement === "ocr" ? "instant_ocr" : state.requirement.endsWith("_ocr") ? "cloud_ocr" : "native",
    bank_consolidation: (state as any).profile === "accurate" ? "accurate" : "instant",
    font_conversion: "legacy_to_unicode",
    translation: state.requirement.endsWith("_translation")
      ? state.requirement.replace("_translation", "")
      : "indictrans2",
  }));

  const [cloudOcrProvider, setCloudOcrProvider] = useState<string>(
    state.requirement.endsWith("_ocr") ? state.requirement : "gemini_ocr"
  );
  const [transDirection, setTransDirection] = useState<string>("");
  const [statutoryEnabled, setStatutoryEnabled] = useState<boolean>(true);
  const [convertLegacyFonts, setConvertLegacyFonts] = useState<boolean>(true);
  const [layoutAnalysis, setLayoutAnalysis] = useState<boolean>(false);
  const [preserveLayout, setPreserveLayout] = useState<boolean>(false);
  const [sourceFont, setSourceFont] = useState<string>("");

  const ocrAction = state.available_actions.find((a) => a.action_id === "ocr");
  const [ocrCustomParams, setOcrCustomParams] = useState<Record<string, unknown>>(() => {
    const d = actionDefaults(ocrAction);
    d.profile = "custom";
    d.engine = "rapidocr";
    return d;
  });

  const [plan, setPlan] = useState<PlanPreview | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<InputFilter>("all");
  const [page, setPage] = useState(1);

  useEffect(() => {
    setSelection(state.input_selection);
    setPreflight(state.preflight);
  }, [state.input_selection, state.preflight]);

  const visibleItems = useMemo(
    () => selection.items.filter((item) => !item.source_path || !excluded.has(item.source_path)),
    [selection.items, excluded],
  );
  const eligiblePaths = visibleItems.flatMap((item) => item.is_eligible && item.source_path ? [item.source_path] : []);
  const issueCount = visibleItems.filter((item) => !item.is_eligible).length;
  const eligibleCount = visibleItems.length - issueCount;
  const totalSize = visibleItems.reduce((sum, item) => sum + item.size_bytes, 0);

  const filteredItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return visibleItems.filter((item) => {
      if (filter === "eligible" && !item.is_eligible) return false;
      if (filter === "issues" && item.is_eligible) return false;
      if (!normalized) return true;
      return `${item.display_name} ${item.source_path ?? ""}`.toLowerCase().includes(normalized);
    });
  }, [visibleItems, query, filter]);

  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(filteredItems.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pagedItems = filteredItems.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  const selectAllRef = useRef<HTMLInputElement>(null);
  const pagedCheckedCount = pagedItems.filter((i) => checkedPaths.has(i.source_path || i.display_name)).length;
  const isAllPagedChecked = pagedItems.length > 0 && pagedCheckedCount === pagedItems.length;
  const isIndeterminate = pagedCheckedCount > 0 && !isAllPagedChecked;

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = isIndeterminate;
    }
  }, [isIndeterminate]);

  useEffect(() => setPage(1), [query, filter]);

  const currentSubtask = primaryTask ? subtaskByPrimary[primaryTask] : undefined;

  const currentBackendMapping = useMemo<{
    requirement: string;
    profile: string;
  } | null>(() => {
    if (!primaryTask || !currentSubtask) return null;
    if (primaryTask === "documents_extraction") {
      if (currentSubtask === "native") return { requirement: "read_native", profile: layoutAnalysis ? "layout_preserving" : "instant" };
      if (currentSubtask === "instant_ocr") return { requirement: "ocr", profile: "instant" };
      if (currentSubtask === "accurate_ocr") return { requirement: "ocr", profile: "accurate" };
      if (currentSubtask === "cloud_ocr") return { requirement: cloudOcrProvider, profile: "instant" };
      if (currentSubtask === "custom_ocr") {
        const p = String(ocrCustomParams.profile || "custom");
        return { requirement: "ocr", profile: p };
      }
      return { requirement: "read_native", profile: "instant" };
    }
    if (primaryTask === "bank_consolidation") {
      return { requirement: "bank_statements", profile: currentSubtask === "accurate" ? "accurate" : "instant" };
    }
    if (primaryTask === "font_conversion") {
      return { requirement: "font_conversion", profile: "instant" };
    }
    if (primaryTask === "translation") {
      if (currentSubtask === "opus_mt") return { requirement: "translation", profile: "instant" };
      if (currentSubtask === "bhashini") return { requirement: "bhashini_translation", profile: "instant" };
      if (currentSubtask === "gemini") return { requirement: "gemini_translation", profile: "instant" };
      if (currentSubtask === "mistral") return { requirement: "mistral_translation", profile: "instant" };
      if (currentSubtask === "azure") return { requirement: "azure_translation", profile: "instant" };
      return { requirement: "translation", profile: "instant" };
    }
    return { requirement: "read_native", profile: "instant" };
  }, [primaryTask, currentSubtask, layoutAnalysis, cloudOcrProvider, ocrCustomParams.profile]);

  const activeAction = currentBackendMapping
    ? state.available_actions.find((action) => action.action_id === currentBackendMapping.requirement)
    : undefined;

  const buildRequest = (): RunRequest => {
    const req = currentBackendMapping?.requirement ?? "read_native";
    const prof = currentBackendMapping?.profile ?? "instant";
    const customOptions: Record<string, unknown> = {};

    if (primaryTask === "documents_extraction") {
      if (currentSubtask === "native") {
        const statEl = typeof document !== "undefined" ? (document.getElementById("param-statutory") as HTMLInputElement | null) : null;
        customOptions.statutory = statEl ? statEl.checked : statutoryEnabled;
        const legacyEl = typeof document !== "undefined" ? (document.getElementById("param-convert-legacy-fonts") as HTMLInputElement | null) : null;
        customOptions.convert_legacy_fonts = legacyEl ? legacyEl.checked : convertLegacyFonts;
        const layoutEl = typeof document !== "undefined" ? (document.getElementById("param-layout-analysis") as HTMLInputElement | null) : null;
        const isLayout = layoutEl ? layoutEl.checked : layoutAnalysis;
        if (isLayout) {
          customOptions.layout_analysis = true;
        }
      } else if (currentSubtask === "accurate_ocr") {
        const layEl = typeof document !== "undefined" ? (document.getElementById("param-preserve-layout") as HTMLInputElement | null) : null;
        if (layEl ? layEl.checked : preserveLayout) {
          customOptions.preserve_layout = true;
        }
      } else if (currentSubtask === "custom_ocr") {
        customOptions.engine = "rapidocr";
        const ocrAct = state.available_actions.find((a) => a.action_id === "ocr");
        for (const parameter of ocrAct?.parameters ?? []) {
          if (parameter.parameter_id === "profile") continue;
          const el = typeof document !== "undefined" ? (document.getElementById(`param-${parameter.parameter_id}`) as HTMLInputElement | null) : null;
          const domVal = parameter.kind === "toggle" ? el?.checked : el?.value;
          const val = domVal !== undefined ? domVal : (ocrCustomParams[parameter.parameter_id] ?? parameter.default_value);
          if (parameter.kind === "toggle") customOptions[parameter.parameter_id] = Boolean(val);
          else if (val !== undefined && val !== null && val !== "") customOptions[parameter.parameter_id] = val;
        }
      }
    } else if (primaryTask === "font_conversion") {
      if (currentSubtask === "unicode_to_krutidev") {
        customOptions.font_mode = "to_krutidev";
        customOptions.target_script = "legacy";
        customOptions.target_profile_id = "to_krutidev";
      } else if (currentSubtask === "unicode_to_devlys") {
        customOptions.font_mode = "to_devlys";
        customOptions.target_script = "legacy";
        customOptions.target_profile_id = "to_devlys";
      } else {
        customOptions.font_mode = "auto_unicode";
        const fontEl = typeof document !== "undefined" ? (document.getElementById("param-source-font") as HTMLSelectElement | null) : null;
        const fontVal = fontEl ? fontEl.value : sourceFont;
        if (fontVal) customOptions.source_font = fontVal;
      }
    } else if (primaryTask === "translation") {
      if (transDirection) {
        customOptions.direction = transDirection;
      }
      if (currentSubtask === "opus_mt") {
        customOptions.engine = "opus_mt";
      } else if (currentSubtask === "indictrans2") {
        customOptions.engine = "indictrans2";
      }
    }

    return {
      paths: eligiblePaths,
      requirement: req,
      profile: prof,
      recursive,
      custom_options: customOptions,
    };
  };

  const buildRequestRef = useRef(buildRequest);
  buildRequestRef.current = buildRequest;

  const refreshIntake = async (nextRoots: readonly string[], nextRecursive = recursive) => {
    setWorking(true);
    onError(null);
    try {
      const result = await intakePaths(nextRoots, nextRecursive);
      setRoots([...nextRoots]);
      setSelection(result.input_selection);
      setPreflight(result.preflight);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Unable to inspect selected inputs.");
    } finally {
      setWorking(false);
    }
  };

  const addRoots = async (paths: readonly string[]) => {
    const clean = paths.map((path) => path.trim()).filter(Boolean);
    if (!clean.length) return;
    setExcluded((current) => {
      const next = new Set(current);
      for (const path of clean) next.delete(path);
      return next;
    });
    await refreshIntake([...new Set([...roots, ...clean])]);
  };

  const removeItem = async (item: InputItemView) => {
    if (!item.source_path) return;
    if (roots.includes(item.source_path)) {
      await refreshIntake(roots.filter((root) => root !== item.source_path));
    } else {
      setExcluded((current) => new Set([...current, item.source_path as string]));
    }
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      (window as any).__sarathi_set_intake = (
        testItems: InputItemView[],
        testPreflight?: PreflightView,
      ) => {
        setSelection({
          total_files: testItems.length,
          total_size_bytes: testItems.reduce((acc, i) => acc + (i.size_bytes || 0), 0),
          is_grouped: false,
          groups: [],
          items: testItems,
        });
        if (testPreflight) setPreflight(testPreflight);
        setCheckedPaths(new Set());
      };
      (window as any).__sarathi_build_request = () => buildRequestRef.current();
      (window as any).__sarathi_remove_path = (paths: string[]) => {
        const next = new Set(excludedRef.current);
        for (const p of paths) next.add(p);
        excludedRef.current = next;
        setExcluded(next);
      };
      (window as any).__sarathi_add_path = (paths: string[]) => {
        const next = new Set(excludedRef.current);
        for (const p of paths) next.delete(p);
        excludedRef.current = next;
        setExcluded(next);
      };
      (window as any).__sarathi_is_excluded = (p: string) => excludedRef.current.has(p);
      (window as any).__sarathi_get_checked_paths = () => Array.from(checkedPathsRef.current);
      (window as any).__sarathi_clear_checked = () => {
        checkedPathsRef.current = new Set();
        setCheckedPaths(new Set());
      };
      (window as any).__sarathi_add_checked = (p: string) => {
        const next = new Set(checkedPathsRef.current);
        next.add(p);
        checkedPathsRef.current = next;
        setCheckedPaths(next);
      };
      (window as any).__sarathi_set_input_page = (p: number) => setPage(p);
      (window as any).__sarathi_set_show_all = (show: boolean) => setShowAllInputsTable(show);
      (window as any).__sarathi_set_filter = (f: "all" | "eligible" | "issues") => setFilter(f);
      (window as any).__sarathi_set_primary_task = (t: PrimaryTaskId) => setPrimaryTask(t);
      (window as any).__sarathi_get_primary_task = () => primaryTask;
      (window as any).__sarathi_set_subtask = (t: PrimaryTaskId, s: string) => {
        setSubtaskByPrimary((prev) => ({ ...prev, [t]: s }));
      };
      (window as any).__sarathi_get_subtask = (t: PrimaryTaskId) => subtaskByPrimary[t];
      (window as any).__sarathi_set_cloud_ocr_provider = (p: string) => setCloudOcrProvider(p);
      (window as any).__sarathi_set_translation_direction = (d: string) => setTransDirection(d);
      (window as any).__sarathi_set_ocr_param = (key: string, val: unknown) => {
        setOcrCustomParams((prev) => ({ ...prev, [key]: val }));
      };
    }
  });

  useEffect(() => {
    if (!primaryTask || !activeAction?.is_enabled || !eligiblePaths.length) {
      setPlan(null);
      setPlanError(null);
      return;
    }
    const timer = window.setTimeout(() => {
      void previewPlan(buildRequest())
        .then((next) => { setPlan(next); setPlanError(null); })
        .catch((reason) => {
          setPlan(null);
          setPlanError(reason instanceof Error ? reason.message : "Unable to preview plan.");
        });
    }, 200);
    return () => window.clearTimeout(timer);
  }, [
    primaryTask,
    currentSubtask,
    cloudOcrProvider,
    transDirection,
    statutoryEnabled,
    convertLegacyFonts,
    layoutAnalysis,
    preserveLayout,
    sourceFont,
    JSON.stringify(ocrCustomParams),
    recursive,
    eligiblePaths.join("\n"),
    activeAction?.is_enabled,
  ]);

  const handleBrowse = async (folder: boolean) => {
    setWorking(true);
    onError(null);
    try {
      const paths = folder ? await browseFolder() : await browseFiles();
      if (paths.length) await addRoots(paths);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Unable to open native picker.");
    } finally {
      setWorking(false);
    }
  };

  const handleStart = async () => {
    if (!primaryTask || !activeAction?.is_enabled || !eligiblePaths.length || planError) return;
    setWorking(true);
    onError(null);
    try {
      onStarted(await startRun(buildRequest()));
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Unable to start run.");
    } finally {
      setWorking(false);
    }
  };

  const showGroupedSummary = visibleItems.length > 10 && !showAllInputsTable;

  return (
    <div class="screen-grid home-cockpit">
      {/* Column 1: Document Intake */}
      <section class="panel intake-panel">
        <div class="panel-header">
          <div class="panel-title-wrap">
            <span class="panel-icon panel-icon--amber">
              <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
              </svg>
            </span>
            <h2 class="panel-heading">Document Intake</h2>
          </div>
          <div class="panel-header-meta">
            <span class="count-badge">{visibleItems.length} selected ({formatBytes(totalSize)})</span>
            <button class="icon-toggle-btn" onClick={() => setIntakeExpanded(!intakeExpanded)} type="button" aria-label="Toggle Intake Section">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={intakeExpanded ? "M5 15l7-7 7 7" : "M19 9l-7 7-7-7"} />
              </svg>
            </button>
          </div>
        </div>

        {intakeExpanded ? (
          <div class="panel-body intake-panel-body">
            {/* Quick Action Bar */}
            <div class="intake-actions-toolbar">
              <div class="intake-btn-group">
                <button id="btn-browse-files" class="btn-action" disabled={working} onClick={() => void handleBrowse(false)} type="button">
                  + Add files
                </button>
                <button id="btn-browse-folder" class="btn-action" disabled={working} onClick={() => void handleBrowse(true)} type="button">
                  + Add folder
                </button>
                <button class="btn-clear" disabled={working || visibleItems.length === 0} onClick={() => { setExcluded(new Set()); void refreshIntake([]); }} type="button">
                  Clear
                </button>
              </div>
              <label class="recursive-label">
                <input
                  type="checkbox"
                  checked={recursive}
                  onChange={(event) => {
                    const checked = event.currentTarget.checked;
                    setRecursive(checked);
                    if (roots.length) void refreshIntake(roots, checked);
                  }}
                />
                <span>Recursive folders</span>
              </label>
            </div>

            {/* Path Input Bar */}
            <div class="path-input-bar">
              <input
                class="path-input"
                placeholder="Paste a file or folder path and press Enter"
                value={manualPath}
                onInput={(event) => setManualPath(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && manualPath.trim()) {
                    void addRoots([manualPath.trim()]);
                    setManualPath("");
                  }
                }}
              />
              <button
                class="btn-add-path"
                disabled={working || !manualPath.trim()}
                onClick={() => { void addRoots([manualPath.trim()]); setManualPath(""); }}
                type="button"
              >
                Add
              </button>
            </div>

            {/* Search & Filter Badges */}
            <div class="intake-search-filter-row">
              <div class="search-input-wrap">
                <svg class="search-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input
                  id="input-files-filter"
                  class="filter-search-input"
                  placeholder="Search selected documents..."
                  value={query}
                  onInput={(event) => setQuery(event.currentTarget.value)}
                />
              </div>
              <div class="filter-segmented-group">
                <button
                  id="btn-filter-all"
                  class={filter === "all" ? "filter-seg-btn active" : "filter-seg-btn"}
                  onClick={() => setFilter("all")}
                  type="button"
                >
                  All <span id="filter-all-count">{visibleItems.length}</span>
                </button>
                <button
                  id="btn-filter-eligible"
                  class={filter === "eligible" ? "filter-seg-btn active" : "filter-seg-btn"}
                  onClick={() => setFilter("eligible")}
                  type="button"
                >
                  Eligible <span id="filter-eligible-count">{eligibleCount}</span>
                </button>
                <button
                  id="btn-filter-issues"
                  class={filter === "issues" ? "filter-seg-btn active" : "filter-seg-btn"}
                  onClick={() => setFilter("issues")}
                  type="button"
                >
                  Issues <span id="filter-issues-count">{issueCount}</span>
                </button>
              </div>
            </div>

            {/* Intake Queue Summary */}
            <div id="input-grouped-summary" class={`grouped-summary-card ${showGroupedSummary ? "" : "hidden"}`}>
              <span class="grouped-summary-text">
                <strong>{visibleItems.length} documents selected</strong>
                <span class="quiet"> · {formatBytes(totalSize)}</span>
              </span>
              <button id="btn-view-all-inputs" class="btn-view-all" onClick={() => setShowAllInputsTable(true)} type="button">
                View All ({visibleItems.length} files)
              </button>
            </div>

            {/* Intake Table */}
            <div class={`table-container input-table-container ${showGroupedSummary ? "hidden" : ""}`}>
              {visibleItems.length > 10 && showAllInputsTable ? (
                <div class="collapse-summary-wrap">
                  <button id="btn-collapse-inputs" class="btn-collapse-summary" onClick={() => setShowAllInputsTable(false)} type="button">
                    Collapse to summary
                  </button>
                </div>
              ) : null}

              {checkedPaths.size > 0 ? (
                <div id="selection-scope-banner" class="selection-scope-banner">
                  <span id="selection-scope-text">
                    {checkedPaths.size === filteredItems.length && filteredItems.length > pagedItems.length
                      ? `All ${filteredItems.length} matching documents selected`
                      : `All ${pagedItems.filter((i) => checkedPaths.has(i.source_path || i.display_name)).length} documents on this page selected`}
                  </span>
                  <div class="button-row">
                    {checkedPaths.size < filteredItems.length ? (
                      <button id="btn-select-all-matching" class="button ghost small" onClick={() => setCheckedPaths(new Set(filteredItems.map((i) => i.source_path || i.display_name)))} type="button">
                        Select all {filteredItems.length} matching
                      </button>
                    ) : null}
                    <button id="btn-clear-selection-scope" class="button ghost small" onClick={() => setCheckedPaths(new Set())} type="button">
                      Clear
                    </button>
                  </div>
                </div>
              ) : null}

              <table class="data-table compact-table">
                <thead>
                  <tr>
                    <th style="width: 36px; text-align: center;">
                      <input
                        id="chk-select-all-inputs"
                        ref={selectAllRef}
                        type="checkbox"
                        checked={isAllPagedChecked}
                        onChange={(e) => {
                          const checked = e.currentTarget.checked;
                          setCheckedPaths((prev) => {
                            const next = new Set(prev);
                            for (const item of pagedItems) {
                              const key = item.source_path || item.display_name;
                              if (checked) next.add(key);
                              else next.delete(key);
                            }
                            return next;
                          });
                        }}
                      />
                    </th>
                    <th>Document</th>
                    <th>Status</th>
                    <th style="text-align: right;">Actions</th>
                  </tr>
                </thead>
                <tbody id="selected-inputs-tbody">
                  {visibleItems.length === 0 ? (
                    <tr class="empty-row"><td colSpan={4} class="empty-cell">No documents selected. Click Add files or paste a path above.</td></tr>
                  ) : filteredItems.length === 0 ? (
                    <tr class="empty-row"><td colSpan={4} class="empty-cell">No documents match the filter query</td></tr>
                  ) : (
                    pagedItems.map((item) => {
                      const itemKey = item.source_path || item.display_name;
                      const isChecked = checkedPaths.has(itemKey);
                      return (
                        <tr key={item.input_id} data-path={itemKey}>
                          <td style="text-align: center;">
                            <input
                              type="checkbox"
                              class="input-row-chk"
                              checked={isChecked}
                              onChange={(e) => {
                                const checked = e.currentTarget.checked;
                                const next = new Set(checkedPathsRef.current);
                                if (checked) next.add(itemKey);
                                else next.delete(itemKey);
                                checkedPathsRef.current = next;
                                setCheckedPaths(next);
                                if (selectAllRef.current) {
                                  const pCount = pagedItems.filter((i) => next.has(i.source_path || i.display_name)).length;
                                  selectAllRef.current.indeterminate = pCount > 0 && pCount < pagedItems.length;
                                }
                              }}
                            />
                          </td>
                          <td>
                            <div class="doc-item-cell">
                              <strong class="doc-name">{item.display_name}</strong>
                              <span class="doc-size">{item.source_path ? `${item.source_path} · ` : ""}{formatBytes(item.size_bytes)}</span>
                            </div>
                          </td>
                          <td>
                            {item.is_eligible ? (
                              <span class="badge badge-emerald">Eligible</span>
                            ) : (
                              <button
                                class="btn-issue-info badge badge-crimson"
                                tabIndex={0}
                                aria-label={`Issue: ${item.issue_reason || "Ineligible document"}`}
                                type="button"
                              >
                                {item.issue_reason || "Issue"}
                              </button>
                            )}
                          </td>
                          <td style="text-align: right;">
                            <div class="button-row compact" style="justify-content: flex-end;">
                              <button class="button ghost mini" onClick={() => onPreview(`/api/inputs/${encodeURIComponent(item.input_id)}/preview`, item.display_name)} type="button">Preview</button>
                              <a class="button ghost mini" href={`/api/inputs/${encodeURIComponent(item.input_id)}/raw`} target="_blank">Open</a>
                              <button class="button ghost mini text-danger" onClick={() => void removeItem(item)} type="button">Remove</button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>

              {filteredItems.length > pageSize ? (
                <div class="pagination" style="margin-top: 10px; display: flex; align-items: center; justify-content: space-between; padding: 4px 8px;">
                  <button id="btn-input-prev" class="button ghost small" disabled={currentPage <= 1} onClick={() => setPage((v) => Math.max(1, v - 1))} type="button">Previous</button>
                  <span id="input-page-indicator" style="font-size: 11px;">Page {currentPage} of {pageCount} ({filteredItems.length} total)</span>
                  <button id="btn-input-next" class="button ghost small" disabled={currentPage >= pageCount} onClick={() => setPage((v) => Math.min(pageCount, v + 1))} type="button">Next</button>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </section>

      {/* Column 2: Processing Capability & Execution Plan */}
      <div class="column-action">
        {/* Processing Action Panel */}
        <section class="panel capability-panel">
          <div class="panel-header">
            <div class="panel-title-wrap">
              <div>
                <span class="capability-eyebrow">Task Selection</span>
                <div class="capability-title-row">
                  <span class="panel-icon panel-icon--amber">⚡</span>
                  <h2 class="panel-heading">Processing Action</h2>
                </div>
              </div>
            </div>
            {primaryTask ? (
              <div class="active-task-badge-pill">
                <span>Active:</span>
                <strong>{PRIMARY_TASKS.find((t) => t.id === primaryTask)?.label}</strong>
                <button
                  id="btn-deselect-task"
                  class="btn-deselect-task"
                  type="button"
                  title="Deselect task and view all primary tasks"
                  onClick={() => setPrimaryTask(null)}
                >
                  ✕
                </button>
              </div>
            ) : (
              <span class="step-guide-badge">Step 1: Choose Primary Task</span>
            )}
          </div>

          {/* Level 1: Primary Task Hierarchy Accordion (Collapsible Level 1 & Level 2) */}
          <div class="tasks-accordion" role="tablist" aria-label="Primary Tasks">
            {PRIMARY_TASKS.map((task) => {
              const isSelected = primaryTask === task.id;
              return (
                <div
                  key={task.id}
                  class={`accordion-item ${isSelected ? "expanded" : "collapsed"}`}
                  data-task={task.id}
                >
                  <button
                    id={`btn-task-${task.id.replace(/_/g, "-")}`}
                    data-task={task.id}
                    class={`primary-task-tab-btn accordion-header-btn ${isSelected ? "active" : ""}`}
                    role="tab"
                    aria-selected={isSelected}
                    aria-expanded={isSelected}
                    type="button"
                    onClick={() => setPrimaryTask(isSelected ? null : task.id)}
                  >
                    <div class="accordion-header-left">
                      <span class="primary-task-icon">{task.icon}</span>
                      <div class="primary-task-info">
                        <span class="primary-task-label">{task.label}</span>
                        <span class="primary-task-desc">{task.description}</span>
                      </div>
                    </div>
                    <div class="accordion-header-right">
                      {isSelected ? (
                        <span class="accordion-badge accordion-badge--active">Active</span>
                      ) : (
                        <span class="accordion-badge accordion-badge--hint">Click to expand</span>
                      )}
                      <span class={`accordion-chevron ${isSelected ? "open" : ""}`} aria-hidden="true">
                        ▾
                      </span>
                    </div>
                  </button>

                  {/* Level 2: Second-Level Progressive Choices Collapsing under this Level 1 Task */}
                  {isSelected && (
                    <div class="accordion-body">
                      {task.id === "documents_extraction" && (
                        <div class="subtasks-container">
                          <div class="subtasks-grid">
                            {/* 1.1 Native Extraction */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "read_native");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "native";
                              return (
                                <div
                                  key="native"
                                  id="subtask-native"
                                  data-subtask="native"
                                  data-req="read_native"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "native" }))}
                                  title={isEnabled ? "Direct digital extraction from PDF, DOCX, XLSX, XLS, CSV." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Native Extraction</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>DIGITAL</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Direct digital extraction from PDF, DOCX, XLSX, XLS, CSV. Automatically invokes statutory/legal extraction.
                                  </p>
                                  <div class="subtask-options-row">
                                    <label class="toggle-row mini">
                                      <input
                                        id="param-convert-legacy-fonts"
                                        type="checkbox"
                                        checked={convertLegacyFonts}
                                        onChange={(e) => {
                                          setConvertLegacyFonts(e.currentTarget.checked);
                                          setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "native" }));
                                        }}
                                      />
                                      <span>
                                        <strong>Convert Legacy Fonts to Unicode</strong>
                                      </span>
                                    </label>
                                    <label class="toggle-row mini" title="Use Graph Neural Networks for multi-column flow, table grids, and semantic headers">
                                      <input
                                        id="param-layout-analysis"
                                        type="checkbox"
                                        checked={layoutAnalysis}
                                        onChange={(e) => {
                                          setLayoutAnalysis(e.currentTarget.checked);
                                          setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "native" }));
                                        }}
                                      />
                                      <span>
                                        <strong>Deep Layout Analysis (GNN)</strong>
                                      </span>
                                    </label>
                                    <label class="toggle-row mini">
                                      <input
                                        id="param-statutory"
                                        type="checkbox"
                                        checked={statutoryEnabled}
                                        onChange={(e) => {
                                          setStatutoryEnabled(e.currentTarget.checked);
                                          setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "native" }));
                                        }}
                                      />
                                      <span>
                                        <strong>Statutory Extraction</strong>
                                      </span>
                                    </label>
                                  </div>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">read_native</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 1.2 Instant OCR */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "ocr");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "instant_ocr";
                              return (
                                <div
                                  key="instant_ocr"
                                  id="subtask-instant-ocr"
                                  data-subtask="instant_ocr"
                                  data-req="ocr"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "instant_ocr" }))}
                                  title={isEnabled ? "RapidOCR inference with OpenVINO acceleration." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Instant OCR</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>RAPIDOCR</span>
                                  </div>
                                  <p class="action-card-desc">
                                    RapidOCR inference with OpenVINO acceleration. Single pass, bypasses heavy preprocessing.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">ocr:instant</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 1.3 Accurate OCR */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "ocr");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "accurate_ocr";
                              return (
                                <div
                                  key="accurate_ocr"
                                  id="subtask-accurate-ocr"
                                  data-subtask="accurate_ocr"
                                  data-req="ocr"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "accurate_ocr" }))}
                                  title={isEnabled ? "Quality-optimized OCR with full preprocessing." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Accurate OCR</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>ACCURATE</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Quality-optimized OCR with CLAHE, deskew, binarization, and selective Tesseract 5 fallback.
                                  </p>
                                  <div class="subtask-options-row">
                                    <label class="toggle-row mini">
                                      <input
                                        id="param-preserve-layout"
                                        type="checkbox"
                                        checked={preserveLayout}
                                        onChange={(e) => {
                                          setPreserveLayout(e.currentTarget.checked);
                                          setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "accurate_ocr" }));
                                        }}
                                      />
                                      <span>
                                        <strong>Preserve Layout</strong>
                                      </span>
                                    </label>
                                  </div>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">ocr:accurate</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 1.4 Cloud OCR */}
                            {(() => {
                              const cloudActs = [
                                { id: "gemini_ocr", label: "Gemini" },
                                { id: "mistral_ocr", label: "Mistral" },
                                { id: "azure_ocr", label: "Azure" },
                                { id: "bhashini_ocr", label: "Bhashini" },
                              ];
                              const curCloudAct = state.available_actions.find((a) => a.action_id === cloudOcrProvider);
                              const isEnabled = curCloudAct ? curCloudAct.is_enabled : false;
                              const isSel = currentSubtask === "cloud_ocr";
                              return (
                                <div
                                  key="cloud_ocr"
                                  id="subtask-cloud-ocr"
                                  data-subtask="cloud_ocr"
                                  data-req="cloud_ocr"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "cloud_ocr" }))}
                                  title={isEnabled ? "External cloud multimodal document recognition." : (curCloudAct?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Cloud Document AI</h4>
                                    <span class={`action-tag action-tag--cloud ${isSel ? "active" : ""}`}>CLOUD</span>
                                  </div>
                                  <p class="action-card-desc">
                                    External cloud multimodal document recognition with fail-closed Kavacha authorization.
                                  </p>
                                  <div class="cloud-provider-chips" onClick={(e) => e.stopPropagation()}>
                                    {cloudActs.map((cp) => {
                                      const act = state.available_actions.find((a) => a.action_id === cp.id);
                                      const isChipAvail = act ? act.is_enabled : false;
                                      const isChipActive = cloudOcrProvider === cp.id;
                                      return (
                                        <button
                                          key={cp.id}
                                          id={`chip-${cp.id.replace(/_/g, "-")}`}
                                          class={`cloud-chip ${isChipActive ? "active" : ""} ${!isChipAvail ? "disabled" : ""}`}
                                          disabled={!isChipAvail}
                                          title={isChipAvail ? cp.label : (act?.disabled_reason || "Unavailable")}
                                          type="button"
                                          onClick={() => {
                                            setCloudOcrProvider(cp.id);
                                            setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "cloud_ocr" }));
                                          }}
                                        >
                                          {cp.label}
                                        </button>
                                      );
                                    })}
                                  </div>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">{cloudOcrProvider}</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 1.5 Custom OCR */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "ocr");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "custom_ocr";
                              return (
                                <div
                                  key="custom_ocr"
                                  id="subtask-custom-ocr"
                                  data-subtask="custom_ocr"
                                  data-req="ocr"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "custom_ocr" }))}
                                  title={isEnabled ? "Fine-grained control over OCR parameters." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Custom OCR</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>CUSTOM</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Fine-grained parameter control over OCR engine, language, and preprocessing toggles.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">ocr:custom</code>
                                  </div>
                                </div>
                              );
                            })()}
                          </div>

                          {/* Custom OCR Parameter Panel */}
                          {currentSubtask === "custom_ocr" && ocrAction?.parameters.length ? (
                            <div class="parameter-section">
                              <div class="parameter-header">
                                <span class="eyebrow">Parameters</span>
                                <h4>Custom OCR Options</h4>
                              </div>
                              <div class="parameter-list">
                                {ocrAction.parameters.map((parameter) => (
                                  <ActionParameter
                                    key={parameter.parameter_id}
                                    parameter={parameter}
                                    value={ocrCustomParams[parameter.parameter_id] ?? parameter.default_value}
                                    onChange={(value) => {
                                      setOcrCustomParams((prev) => ({ ...prev, [parameter.parameter_id]: value }));
                                    }}
                                  />
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      )}

                      {task.id === "bank_consolidation" && (
                        <div class="subtasks-container">
                          <div class="subtasks-grid">
                            {/* 2.1 Instant Consolidation */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "bank_statements");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "instant";
                              return (
                                <div
                                  key="instant"
                                  id="subtask-instant-consolidation"
                                  data-subtask="instant"
                                  data-req="bank_statements"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, bank_consolidation: "instant" }))}
                                  title={isEnabled ? "Throughput-optimized financial statement parsing." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Instant Consolidation</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>FAST</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Throughput-optimized parsing and standard reconciliation heuristics across financial statements.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">bank_statements:instant</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 2.2 Accurate Consolidation */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "bank_statements");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "accurate";
                              return (
                                <div
                                  key="accurate"
                                  id="subtask-accurate-consolidation"
                                  data-subtask="accurate"
                                  data-req="bank_statements"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, bank_consolidation: "accurate" }))}
                                  title={isEnabled ? "Strict running balance verification and deduplication." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Accurate Consolidation</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>ACCURATE</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Strict running balance verification, debit/credit inversion detection, and multi-page pagination deduplication.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">bank_statements:accurate</code>
                                  </div>
                                </div>
                              );
                            })()}
                          </div>
                        </div>
                      )}

                      {task.id === "font_conversion" && (
                        <div class="subtasks-container">
                          <div class="subtasks-grid">
                            {/* 3.1 Legacy to Unicode */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "font_conversion");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "legacy_to_unicode";
                              return (
                                <div
                                  key="legacy_to_unicode"
                                  id="subtask-legacy-to-unicode"
                                  data-subtask="legacy_to_unicode"
                                  data-req="font_conversion"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, font_conversion: "legacy_to_unicode" }))}
                                  title={isEnabled ? "Auto-detects legacy Hindi font encodings and converts to Unicode." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Legacy to Unicode</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>UNICODE</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Auto-detects non-Unicode Indian font encodings (KrutiDev, DevLys, Chanakya, Shusha, Shivaji) and converts to standardized Unicode Devanagari.
                                  </p>
                                  <div class="subtask-options-row" onClick={(e) => e.stopPropagation()}>
                                    <label class="field mini" style={{ margin: 0 }}>
                                      <span style={{ fontSize: "11px" }}>Source Font Hint</span>
                                      <select
                                        id="param-source-font"
                                        value={sourceFont}
                                        onChange={(e) => setSourceFont(e.currentTarget.value)}
                                        style={{ padding: "3px 6px", fontSize: "11px" }}
                                      >
                                        <option value="">Auto-Detect Source Font</option>
                                        <option value="krutidev010">KrutiDev 010 / DevLys</option>
                                        <option value="chanakya010">Chanakya</option>
                                        <option value="shusha010">Shusha</option>
                                        <option value="shivaji010">Shivaji</option>
                                      </select>
                                    </label>
                                  </div>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">font_conversion:auto_unicode</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 3.2 Unicode to KrutiDev */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "font_conversion");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "unicode_to_krutidev";
                              return (
                                <div
                                  key="unicode_to_krutidev"
                                  id="subtask-unicode-to-krutidev"
                                  data-subtask="unicode_to_krutidev"
                                  data-req="font_conversion"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, font_conversion: "unicode_to_krutidev" }))}
                                  title={isEnabled ? "Reverses Unicode Devanagari text into legacy KrutiDev 010." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Unicode to KrutiDev</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>KRUTIDEV</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Reverses Unicode Devanagari text into legacy KrutiDev 010 typewriter encoding using precompiled reverse transducers.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">font_conversion:to_krutidev</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 3.3 Unicode to DevLys */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "font_conversion");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "unicode_to_devlys";
                              return (
                                <div
                                  key="unicode_to_devlys"
                                  id="subtask-unicode-to-devlys"
                                  data-subtask="unicode_to_devlys"
                                  data-req="font_conversion"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, font_conversion: "unicode_to_devlys" }))}
                                  title={isEnabled ? "Reverses Unicode Devanagari text into legacy DevLys 010." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Unicode to DevLys</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>DEVLYS</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Reverses Unicode Devanagari text into legacy DevLys 010 typewriter encoding using precompiled reverse transducers.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">font_conversion:to_devlys</code>
                                  </div>
                                </div>
                              );
                            })()}
                          </div>
                        </div>
                      )}

                      {task.id === "translation" && (
                        <div class="subtasks-container">
                          {/* Direction selector first */}
                          <div class="translation-direction-toolbar" role="group" aria-label="Translation Direction">
                            <button
                              id="btn-direction-auto"
                              data-dir=""
                              class={`direction-seg-btn ${transDirection === "" ? "active" : ""}`}
                              type="button"
                              onClick={() => setTransDirection("")}
                            >
                              ⚡ Auto-Detect Language Direction
                            </button>
                            <button
                              id="btn-direction-hi-en"
                              data-dir="hi_en"
                              class={`direction-seg-btn ${transDirection === "hi_en" ? "active" : ""}`}
                              type="button"
                              onClick={() => setTransDirection("hi_en")}
                            >
                              Hindi → English
                            </button>
                            <button
                              id="btn-direction-en-hi"
                              data-dir="en_hi"
                              class={`direction-seg-btn ${transDirection === "en_hi" ? "active" : ""}`}
                              type="button"
                              onClick={() => setTransDirection("en_hi")}
                            >
                              English → Hindi
                            </button>
                          </div>

                          {/* 6 Engine Choices */}
                          <div class="subtasks-grid">
                            {[
                              {
                                id: "indictrans2",
                                actionId: "indictrans2_translation",
                                label: "IndicTrans2 (Local)",
                                tag: "INDICTRANS2",
                                isCloud: false,
                                desc: "AI4Bharat IndicTrans2 local Transformer. Optimized for high-fidelity 22 Indian languages.",
                                code: "indictrans2_translation",
                              },
                              {
                                id: "opus_mt",
                                actionId: "translation",
                                label: "Helsinki OPUS-MT (Local)",
                                tag: "OPUS-MT",
                                isCloud: false,
                                desc: "Fast Marian-based neural translation engine running fully offline and local.",
                                code: "translation:opus_mt",
                              },
                              {
                                id: "bhashini",
                                actionId: "bhashini_translation",
                                label: "Bhashini (Cloud)",
                                tag: "BHASHINI",
                                isCloud: true,
                                desc: "Government of India Bhashini National Language Translation Mission API. Authorized by Kavacha.",
                                code: "bhashini_translation",
                              },
                              {
                                id: "gemini",
                                actionId: "gemini_translation",
                                label: "Google Gemini (Cloud)",
                                tag: "GEMINI",
                                isCloud: true,
                                desc: "Google Gemini multimodal translation adapter. High context multilingual reasoning.",
                                code: "gemini_translation",
                              },
                              {
                                id: "mistral",
                                actionId: "mistral_translation",
                                label: "Mistral (Cloud)",
                                tag: "MISTRAL",
                                isCloud: true,
                                desc: "Mistral AI European cloud translation adapter. Authorized by Kavacha.",
                                code: "mistral_translation",
                              },
                              {
                                id: "azure",
                                actionId: "azure_translation",
                                label: "Azure AI (Cloud)",
                                tag: "AZURE",
                                isCloud: true,
                                desc: "Microsoft Azure AI Translator cloud service. Enterprise translation backbone.",
                                code: "azure_translation",
                              },
                            ].map((eng) => {
                              const act = state.available_actions.find((a) => a.action_id === eng.actionId);
                              const isEnabled = act ? act.is_enabled : false;
                              const isSel = currentSubtask === eng.id;
                              return (
                                <div
                                  key={eng.id}
                                  id={`subtask-engine-${eng.id.replace(/_/g, "-")}`}
                                  data-subtask={eng.id}
                                  data-req={eng.actionId}
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => {
                                    setSubtaskByPrimary((prev) => ({ ...prev, translation: eng.id }));
                                  }}
                                  title={isEnabled ? eng.desc : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">{eng.label}</h4>
                                    <span class={`action-tag ${eng.isCloud ? "action-tag--cloud" : ""} ${isSel ? "active" : ""}`}>
                                      {eng.tag}
                                    </span>
                                  </div>
                                  <p class="action-card-desc">{isEnabled ? eng.desc : (act?.disabled_reason || "Unavailable")}</p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">{eng.code}</code>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* If no Level 1 task is selected, show instructional prompt */}
          {!primaryTask && (
            <div id="level1-empty-prompt" class="level1-empty-prompt">
              <span class="level1-prompt-icon">👆</span>
              <div class="level1-prompt-text">
                <strong>Select a Primary Task Above</strong>
                <p>Choose one of the four primary tasks above to view its specific methods, engines, and configuration options.</p>
              </div>
            </div>
          )}
        </section>

        {/* Preflight Execution Plan Card */}
        <section class="panel execution-plan-card">
          <div class="execution-plan-header">
            <div>
              <span class="preflight-eyebrow">Preflight</span>
              <h3 class="execution-plan-title">Execution Plan</h3>
            </div>
            <span class="preflight-status-text">
              {!primaryTask ? "Select a task above" : preflight ? `${eligibleCount} eligible · ${issueCount} issues` : "Select inputs to validate"}
            </span>
          </div>

          {!primaryTask ? (
            <div class="empty-state" style={{ padding: "20px 14px" }}>
              <strong>No Task Selected</strong>
              <p class="quiet" style={{ margin: "4px 0 0 0", fontSize: "12px" }}>
                Select a primary task above to view options and preview execution.
              </p>
            </div>
          ) : plan ? (
            <div class="plan-details-box">
              <div class="plan-header-row">
                <strong>{plan.document_count} document{plan.document_count === 1 ? "" : "s"}</strong>
                <span class="badge badge-emerald">Plan ready</span>
              </div>
              <div class="plan-stages-row">
                {plan.stages.map((stage, idx) => (
                  <span key={stage.name} class="stage-chip">
                    {stage.name}
                    {idx < plan.stages.length - 1 ? <span class="stage-arrow">→</span> : null}
                  </span>
                ))}
              </div>
              {plan.devices.length ? (
                <small class="plan-devices">
                  {plan.devices.map((device) => `${device.device_type}${device.is_available ? "" : " unavailable"}`).join(" · ")}
                </small>
              ) : null}
            </div>
          ) : null}

          {planError ? <div class="inline-error">{planError}</div> : null}

          <button
            id="btn-start-run"
            class="button primary btn-primary btn-start-run"
            disabled={working || !primaryTask || !eligiblePaths.length || !activeAction?.is_enabled || Boolean(planError)}
            onClick={() => void handleStart()}
            type="button"
          >
            <span>{working ? "Working…" : !primaryTask ? "Select a Task to Start" : "Start document processing"}</span>
            <span class="btn-bolt">⚡</span>
          </button>
        </section>
      </div>
    </div>
  );
}

function Monitor({ state, onError }: { state: ApplicationViewState; onError: (message: string | null) => void }) {
  const [localRun, setLocalRun] = useState(state.active_run);
  const [cancelling, setCancelling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);

  useEffect(() => {
    setLocalRun(state.active_run);
  }, [state.active_run]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      (window as any).__sarathi_set_active_run = (testRun: any) => {
        setLocalRun(testRun);
      };
    }
  }, []);

  const run = localRun;
  const progress = run?.progress?.percentage;
  const canCancel = run?.status === "RUNNING";

  return (
    <div class="screen-grid">
      <section class="panel span-2">
        <div class="section-heading">
          <div><span class="eyebrow">Live run</span><h3 id="monitor-run-id">{run?.run_id || "No active run"}</h3></div>
          <div class="button-row">
            <span class="badge badge--active">{run?.status || "IDLE"}</span>
            <button
              id="btn-cancel-run"
              class="button danger"
              disabled={!canCancel && !cancelling}
              onClick={() => setShowCancelDialog(true)}
              type="button"
            >
              {cancelling ? "Cancelling…" : "Cancel"}
            </button>
          </div>
        </div>

        <div
          id="top-progress-container"
          class={`top-progress-container ${progress == null ? "indeterminate" : ""}`}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress != null ? Math.round(progress) : undefined}
          aria-busy={progress == null ? "true" : "false"}
        >
          <div id="top-progress-bar" class="top-progress-bar" style={{ width: `${progress ?? 0}%` }} />
        </div>
        <span id="top-progress-stage" style="display:none">{run?.current_focus?.stage || "Processing..."}</span>
        <span id="top-progress-pct" style="display:none">{progress != null ? `${progress.toFixed(0)}%` : ""}</span>

        <div class="metrics-grid compact">
          <Metric label="Progress" value={progress == null ? "Live" : `${progress.toFixed(0)}%`} />
          <Metric label="Files" value={`${run?.terminal_files ?? 0}/${run?.total_files ?? 0}`} />
          <Metric label="Elapsed" value={formatDuration(run?.elapsed_ns)} />
          <Metric label="Workers" value={run?.active_workers?.length ?? 0} />
        </div>
      </section>

      <div class="modal-backdrop" style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", display: showCancelDialog ? "grid" : "none", placeItems: "center", zIndex: 1000 }}>
        <dialog id="cancel-run-dialog" open class="cancel-dialog" aria-modal="true" style={{ padding: "24px", background: "var(--surface)", borderRadius: "12px", border: "1px solid var(--border)", maxWidth: "440px", boxShadow: "var(--shadow)" }}>
          <div class="cancel-dialog-content">
            <h4 style={{ margin: "0 0 8px" }}>Cancel Document Processing?</h4>
            <p style={{ margin: "0 0 16px", color: "var(--muted)", fontSize: "13px" }}>
              Document processing will cancel cooperatively after the current stage completes.
            </p>
            <div class="button-row between">
              <button id="btn-cancel-dialog-abort" class="button ghost" onClick={() => setShowCancelDialog(false)} type="button">
                Continue processing
              </button>
              <button
                id="btn-cancel-dialog-confirm"
                class="button danger"
                onClick={() => {
                  setShowCancelDialog(false);
                  const targetId = run?.run_id;
                  if (targetId) {
                    setCancelling(true);
                    void cancelRun(targetId)
                      .catch((reason) => onError(reason instanceof Error ? reason.message : "Unable to cancel run."))
                      .finally(() => setCancelling(false));
                  }
                }}
                type="button"
              >
                Confirm cancel
              </button>
            </div>
          </div>
        </dialog>
      </div>

      {run?.current_focus ? (
        <section class="panel">
          <div class="section-heading"><div><span class="eyebrow">Current focus</span><h3>{run.current_focus.operation_name}</h3></div></div>
          <dl class="facts">
            <div><dt>Stage</dt><dd>{run.current_focus.stage}</dd></div>
            <div><dt>Device</dt><dd>{run.current_focus.device_type}</dd></div>
            <div><dt>Elapsed</dt><dd>{formatDuration(run.current_focus.elapsed_ns)}</dd></div>
            <div><dt>Activity</dt><dd>{run.current_focus.last_activity || "—"}</dd></div>
          </dl>
        </section>
      ) : null}

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">Devices</span><h3>Execution progress</h3></div></div>
        {run?.device_progress?.length ? (
          <div class="data-list">
            {run.device_progress.map((device) => (
              <div class="data-row" key={device.device_type}>
                <strong>{device.device_type}</strong>
                <span>{device.execution_count} executions</span>
                <span>{formatDuration(device.avg_duration_ns)}</span>
                <span>{formatConfidence(device.avg_confidence)}</span>
              </div>
            ))}
          </div>
        ) : <p class="quiet">No device execution records yet.</p>}
      </section>

      <section class="panel span-2">
        <div class="section-heading"><div><span class="eyebrow">Files</span><h3>Run progress</h3></div></div>
        {run?.files?.length ? (
          <div class="data-list">
            {run.files.map((file) => (
              <div class="data-row wide" key={file.input_id}>
                <strong>{file.display_name}</strong>
                <span>{file.status}</span>
                <span>{file.current_stage || "—"}</span>
                <span>{formatDuration(file.elapsed_ns)}</span>
                <span>{file.error_message || (file.warning_count ? `${file.warning_count} warning(s)` : "")}</span>
              </div>
            ))}
          </div>
        ) : <p class="quiet">File-level progress will appear as execution starts.</p>}
      </section>
    </div>
  );
}

function Review({ state, onRefresh, onError }: { state: ApplicationViewState; onRefresh: () => Promise<void>; onError: (message: string | null) => void }) {
  const [itemsOverride, setItemsOverride] = useState<ReviewItemView[] | null>(null);
  const queue = itemsOverride ?? state.review_queue;
  const [selectedId, setSelectedId] = useState<string | null>(queue[0]?.item_id ?? null);
  const [workingItem, setWorkingItem] = useState<string | null>(null);
  const [showDraftBox, setShowDraftBox] = useState(false);
  const [draftInput, setDraftInput] = useState("");
  const [savedDrafts, setSavedDrafts] = useState<Record<string, string>>({});

  const loadReviewQueue = async () => {
    try {
      const res = await fetch("/api/review");
      if (res.ok) {
        const payload = await res.json();
        if (Array.isArray(payload.items)) {
          setItemsOverride(payload.items);
          return;
        }
      }
    } catch {
      // fallback
    }
    await onRefresh();
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      (window as any).__sarathi_load_review = loadReviewQueue;
      (window as any).loadReviewQueue = loadReviewQueue;
    }
  });

  useEffect(() => {
    if (queue.length && (!selectedId || !queue.some((i) => i.item_id === selectedId))) {
      setSelectedId(queue[0]?.item_id ?? null);
    }
  }, [queue, selectedId]);

  const selectedIndex = Math.max(0, queue.findIndex((item) => item.item_id === selectedId));
  const item = queue.length ? queue[selectedIndex] ?? null : null;
  const runId = state.active_run?.run_id ?? state.terminal_summary?.run_id ?? "";
  const pendingCount = queue.filter((i) => (i.status || "").toLowerCase() === "pending").length;

  useEffect(() => {
    if (item) {
      setDraftInput(savedDrafts[item.item_id] ?? item.draft_proposal ?? item.output_text ?? "");
      setShowDraftBox(false);
    }
  }, [item?.item_id]);

  const apply = async (action: "accept" | "unresolved") => {
    if (!item) return;
    setWorkingItem(item.item_id);
    onError(null);
    try {
      await submitReview(runId, item.item_id, item.attempt_id, action);
      await onRefresh();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Unable to submit review action.");
    } finally {
      setWorkingItem(null);
    }
  };

  const getBadgeClass = (status: string) => {
    const s = (status || "").toLowerCase();
    if (s === "accepted") return "emerald";
    if (s === "unresolved") return "crimson";
    return "amber";
  };

  return (
    <div class="screen-grid">
      <section class="panel">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Human review</span>
            <h3 id="review-queue-count">{queue.length} items ({pendingCount} pending)</h3>
          </div>
        </div>
        <div class="table-container">
          <table class="data-table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Stage</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody id="review-queue-tbody">
              {queue.length === 0 ? (
                <tr><td colSpan={3} style="text-align: center; padding: 24px; color: var(--muted);">No items currently require human review.</td></tr>
              ) : (
                queue.map((reviewItem, idx) => (
                  <tr
                    key={reviewItem.item_id}
                    class={`review-row ${reviewItem.item_id === item?.item_id ? "selected active" : ""}`}
                    data-idx={idx}
                    onClick={() => setSelectedId(reviewItem.item_id)}
                    style="cursor: pointer;"
                  >
                    <td>
                      <strong>{reviewItem.item_id}</strong>
                      <div class="quiet">{reviewItem.file_display_name}</div>
                    </td>
                    <td>{reviewItem.stage}</td>
                    <td>
                      <span class={`badge badge-${getBadgeClass(reviewItem.status)}`}>
                        {reviewItem.status.toUpperCase()}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section id="review-detail-card" class={`panel ${item ? "" : "hidden"}`}>
        {item ? (
          <>
            <div class="section-heading">
              <div>
                <span class="eyebrow">Review item</span>
                <h3 id="review-active-item-title">{item.item_id}</h3>
              </div>
              <span id="review-status-badge" class={`badge badge-${getBadgeClass(item.status)}`}>
                {item.status.toUpperCase()}
              </span>
            </div>
            <p class="quiet">{item.issue_reason || (item as any).message || "Review required."}</p>
            <div class="review-text">
              <div><span>Source</span><p id="review-source-text">{item.source_text || (item as any).context?.source || "—"}</p></div>
              <div><span>Output</span><p id="review-output-text">{item.output_text || (item as any).context?.output || "—"}</p></div>
            </div>

            <div style="margin-top: 12px;">
              <button id="btn-review-edit" class="button secondary small" onClick={() => setShowDraftBox(true)} type="button">
                Propose Edit
              </button>
            </div>

            <div id="review-draft-box" class={`review-draft-card ${showDraftBox ? "" : "hidden"}`}>
              <label class="field">
                <span>Proposed correction</span>
                <input id="review-draft-input" value={draftInput} onInput={(e) => setDraftInput(e.currentTarget.value)} />
              </label>
              <div class="button-row">
                <button
                  id="btn-review-save-draft"
                  class="button secondary small"
                  onClick={() => {
                    setSavedDrafts((prev) => ({ ...prev, [item.item_id]: draftInput }));
                    setShowDraftBox(false);
                  }}
                  type="button"
                >
                  Save Draft
                </button>
                <button class="button ghost small" onClick={() => setShowDraftBox(false)} type="button">Cancel</button>
              </div>
            </div>

            <div id="review-proposed-display" class={savedDrafts[item.item_id] ? "" : "hidden"} style="margin-top: 10px;">
              <span class="quiet">Proposed: </span>
              <strong id="review-proposed-text">{savedDrafts[item.item_id]}</strong>
            </div>

            <div class="button-row between" style="margin-top: 18px;">
              <div class="button-row">
                <button id="btn-review-prev" class="button ghost" disabled={selectedIndex <= 0} onClick={() => setSelectedId(queue[selectedIndex - 1]?.item_id ?? item.item_id)} type="button">Previous</button>
                <button id="btn-review-next" class="button ghost" disabled={selectedIndex >= queue.length - 1} onClick={() => setSelectedId(queue[selectedIndex + 1]?.item_id ?? item.item_id)} type="button">Next</button>
              </div>
            </div>

            <div class="button-row action-row" style="margin-top: 16px;">
              <button id="btn-review-accept" class="button primary" disabled={workingItem === item.item_id || !item.available_actions.includes("accept")} onClick={() => void apply("accept")} type="button">Accept</button>
              <button id="btn-review-dismiss" class="button secondary" disabled={workingItem === item.item_id || !item.available_actions.includes("unresolved")} onClick={() => void apply("unresolved")} type="button">Mark Unresolved</button>
            </div>
          </>
        ) : (
          <EmptyState title="No item selected" detail="Select an item from the review queue." />
        )}
      </section>
    </div>
  );
}

function Summary({ summary, onReveal, onError, onPreview }: { summary: RunSummaryView | null; onReveal: (runId: string) => Promise<boolean>; onError: (message: string | null) => void; onPreview: (pathOrUrl: string, displayName: string) => void }) {
  const [revealing, setRevealing] = useState(false);
  if (!summary) return <EmptyState title="No completed run" detail="Run outcomes and confirmed artifacts will appear here." />;

  const handleReveal = async () => {
    setRevealing(true);
    onError(null);
    try {
      if (!await onReveal(summary.run_id)) onError("Output directory is unavailable for this run.");
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Unable to reveal output directory.");
    } finally {
      setRevealing(false);
    }
  };

  return (
    <div class="screen-grid">
      <section class="panel span-2">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Terminal run</span>
            <h3 id="summary-title">{formatSummaryTitle(summary.status)}</h3>
            <span id="summary-run-id" style="display:none">{summary.run_id}</span>
          </div>
          <div class="button-row"><span class="badge badge--active">{summary.status}</span><button class="button secondary" disabled={revealing} onClick={() => void handleReveal()} type="button">{revealing ? "Opening…" : "Open output folder"}</button></div>
        </div>
        <div class="metrics-grid compact">
          <Metric label="Inputs" value={summary.total_inputs} />
          <Metric label="Successful" value={summary.successful_files ?? "—"} />
          <Metric label="Warnings" value={summary.warning_files ?? "—"} />
          <Metric label="Failed" value={summary.failed_files ?? "—"} />
          <Metric label="Wall time" value={formatDuration(summary.wall_time_ns)} />
          <Metric label="Avg/input" value={formatDuration(summary.avg_duration_per_input_ns)} />
          <Metric label="Confidence" value={formatConfidence(summary.avg_confidence)} />
          <Metric label="Accuracy" value={formatConfidence(summary.accuracy)} />
        </div>
      </section>

      <section class="panel span-2">
        <div class="section-heading"><div><span class="eyebrow">Output</span><h3>Confirmed artifacts</h3></div></div>
        {(summary.artifacts ?? []).length ? (
          <div class="file-list">
            {(summary.artifacts ?? []).map((artifact) => (
              <div class="file-row" key={artifact.artifact_id}>
                <div class="file-icon">OUT</div>
                <div class="file-main"><strong>{artifact.display_name}</strong><span>{artifact.role} · {formatBytes(artifact.size_bytes)}</span></div>
                <div class="button-row">
                  <button class="button ghost small" onClick={() => onPreview(`/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/preview`, artifact.display_name)} type="button">Preview</button>
                  <a class="button ghost small" href={`/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/raw`} target="_blank">Open</a>
                  <a class="button secondary small" href={`/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}`}>Download</a>
                </div>
              </div>
            ))}
          </div>
        ) : <EmptyState title="No confirmed artifacts" detail="Only committed outputs are presented as final." />}
      </section>

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">Stages</span><h3>Timing</h3></div></div>
        {(summary.stage_timings ?? []).length ? <div class="data-list">{(summary.stage_timings ?? []).map((stage) => <div class="data-row" key={stage.stage_name}><strong>{stage.stage_name}</strong><span>{stage.call_count} calls</span><span>{formatDuration(stage.duration_ns)}</span></div>)}</div> : <p class="quiet">No stage timing records.</p>}
      </section>

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">Hardware</span><h3>Device summary</h3></div></div>
        {(summary.device_summaries ?? []).length ? <div class="data-list">{(summary.device_summaries ?? []).map((device) => <div class="data-row" key={device.device_type}><strong>{device.device_type}</strong><span>{device.execution_count} executions</span><span>{formatDuration(device.avg_duration_ns)}</span><span>{formatConfidence(device.avg_confidence)}</span></div>)}</div> : <p class="quiet">No hardware execution records.</p>}
      </section>

      {((summary.warnings ?? []).length || (summary.failures ?? []).length) ? (
        <section class="panel span-2">
          <div class="section-heading"><div><span class="eyebrow">Run notes</span><h3>Warnings and failures</h3></div></div>
          {(summary.warnings ?? []).map((warning) => <p class="note warning" key={`w-${warning}`}>{warning}</p>)}
          {(summary.failures ?? []).map((failure) => <p class="note failure" key={`f-${failure}`}>{failure}</p>)}
        </section>
      ) : null}
    </div>
  );
}

function Inspector({ inspector }: { inspector: InspectorViewState | null }) {
  const [logQuery, setLogQuery] = useState("");
  const [logLevel, setLogLevel] = useState("ALL");
  const [regionQuery, setRegionQuery] = useState("");
  if (!inspector) return <EmptyState title="Nothing selected for inspection" detail="Select a run from History or complete a run to inspect telemetry." />;

  const logs = inspector.activity_logs.filter((entry) => {
    if (logLevel !== "ALL" && entry.severity.toUpperCase() !== logLevel) return false;
    const target = `${entry.timestamp} ${entry.component} ${entry.message}`.toLowerCase();
    return !logQuery || target.includes(logQuery.toLowerCase());
  });
  const regions = inspector.region_confidence.filter((region) => {
    const target = `${region.region_id} ${region.file_display_name} ${region.page_number} ${region.region_type} ${region.method}`.toLowerCase();
    return !regionQuery || target.includes(regionQuery.toLowerCase());
  });

  return (
    <div class="screen-grid">
      <section class="panel span-2">
        <div class="section-heading">
          <div><span class="eyebrow">Technical inspector</span><h3>{inspector.run_id}</h3></div>
          <div class="button-row">
            <span class="badge badge--active">{inspector.status}</span>
            <a id="btn-export-diagnostics" class="button secondary" href={`/api/runs/${encodeURIComponent(inspector.run_id)}/diagnostics?download=1`}>Export diagnostics</a>
          </div>
        </div>
        <div class="metrics-grid compact">
          <Metric label="Elapsed" value={formatDuration(inspector.elapsed_ns)} />
          <Metric label="Workers" value={inspector.worker_performance.length} />
          <Metric label="Pages" value={inspector.page_confidence.length} />
          <Metric label="Fallbacks" value={inspector.fallback_improvements.length} />
        </div>
      </section>

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">System</span><h3>Runtime facts</h3></div></div>
        <dl class="facts">{inspector.system_facts.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
      </section>

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">Confidence</span><h3>Distribution</h3></div></div>
        <div class="data-list">{inspector.confidence_distribution.map(([bucket, count]) => <div class="data-row" key={bucket}><strong>{bucket}</strong><span>{count}</span></div>)}</div>
      </section>

      <section class="panel span-2">
        <div class="section-heading"><div><span class="eyebrow">Activity</span><h3>Logs</h3></div></div>
        <div class="filter-bar">
          <input class="search-input" placeholder="Search logs" value={logQuery} onInput={(e) => setLogQuery(e.currentTarget.value)} />
          <select value={logLevel} onChange={(e) => setLogLevel(e.currentTarget.value)}>
            <option value="ALL">ALL</option>
            <option value="INFO">INFO</option>
            <option value="WARN">WARN</option>
            <option value="ERROR">ERROR</option>
            <option value="FAILED">FAILED</option>
          </select>
          <button class="button ghost small" onClick={() => void navigator.clipboard.writeText(inspector.activity_logs.map((entry) => `[${entry.timestamp}] [${entry.severity}] ${entry.component}: ${entry.message}`).join("\n"))} type="button">Copy logs</button>
        </div>
        <div class="log-list">
          {logs.length ? logs.map((entry, index) => (
            <div class="log-entry" key={`${entry.timestamp}-${index}`}>
              <span>{entry.timestamp}</span>
              <strong>{entry.severity}</strong>
              <span>{entry.component}: {entry.message}</span>
            </div>
          )) : <p class="quiet">No logs match the current filter.</p>}
        </div>
      </section>

      <section class="panel span-2">
        <div class="section-heading"><div><span class="eyebrow">Pages</span><h3>Confidence</h3></div></div>
        <div class="data-list">
          {inspector.page_confidence.length ? inspector.page_confidence.map((page) => (
            <div class="data-row wide" key={`${page.file_display_name}-${page.page_number}`}>
              <strong>{page.file_display_name}</strong>
              <span>Page {page.page_number}</span>
              <span>{formatConfidence(page.confidence_score)}</span>
              <span>{page.region_count} regions</span>
              <span>{page.review_recommended ? "Review" : "OK"}</span>
            </div>
          )) : <p class="quiet">No page confidence records.</p>}
        </div>
      </section>

      <section class="panel span-2">
        <div class="section-heading"><div><span class="eyebrow">Regions</span><h3>Confidence details</h3></div></div>
        <input class="search-input" placeholder="Filter regions" value={regionQuery} onInput={(e) => setRegionQuery(e.currentTarget.value)} />
        <div class="data-list spaced">
          {regions.length ? regions.map((region) => (
            <div class="data-row wide" key={region.region_id}>
              <strong>{region.region_id}</strong>
              <span>{region.file_display_name} · P{region.page_number}</span>
              <span>{region.region_type}</span>
              <span>{formatConfidence(region.confidence_score)}</span>
              <span>{region.fallback_engine || region.method}</span>
            </div>
          )) : <p class="quiet">No region confidence records match the filter.</p>}
        </div>
      </section>
    </div>
  );
}

function HistoryDrawer({
  open,
  history,
  busy,
  error,
  onClose,
  onSummary,
  onInspector,
  onClearHistory,
  onClearCache,
}: {
  open: boolean;
  history: readonly TerminalRunHistoryView[];
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSummary: (runId: string) => void;
  onInspector: (runId: string) => void;
  onClearHistory: () => void;
  onClearCache: () => void;
}) {
  if (!open) return null;
  return (
    <div class="drawer-backdrop" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside aria-label="Run history" class="drawer">
        <div class="drawer-heading">
          <div><span class="eyebrow">Terminal history</span><h3>Recent runs</h3></div>
          <button class="button ghost small" onClick={onClose} type="button">Close</button>
        </div>
        <div class="button-row" style="margin: 8px 0 14px;">
          <button id="btn-clear-history" class="button ghost small" onClick={onClearHistory} type="button">Clear history</button>
          <button id="btn-clear-cache" class="button ghost small" onClick={onClearCache} type="button">Clear cache</button>
        </div>
        {error ? <div class="inline-error">{error}</div> : null}
        {busy ? <div class="loading"><div class="spinner" /><span>Loading history…</span></div> : null}
        <div class="history-list">
          {history.length ? history.map((item) => (
            <div class="history-item" key={item.run_id}>
              <div class="history-item__header">
                <strong>{item.run_id}</strong>
                <span class="badge">{item.status}</span>
              </div>
              <div class="history-item__meta">
                <span>{item.requirement}</span>
                <span>{item.duration_ms} ms</span>
                <span>{item.artifact_count} artifacts · {item.warning_count} warnings</span>
              </div>
              <div class="button-row">
                <button class="button ghost small" onClick={() => onSummary(item.run_id)} type="button">Summary</button>
                <button class="button ghost small" onClick={() => onInspector(item.run_id)} type="button">Inspector</button>
              </div>
            </div>
          )) : <p class="quiet">No saved runs in history.</p>}
        </div>
      </aside>
    </div>
  );
}

export function App() {
  const [screen, setScreen] = useState<Screen>("home");
  const [state, setState] = useState<ApplicationViewState | null>(null);
  const [summaryOverride, setSummaryOverride] = useState<RunSummaryView | null>(null);
  const [inspectorOverride, setInspectorOverride] = useState<InspectorViewState | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<readonly TerminalRunHistoryView[]>([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [previewTarget, setPreviewTarget] = useState<{ pathOrUrl: string; displayName: string } | null>(null);
  const connectedRef = useRef(false);
  const summaryRequest = useRef(0);
  const summarySeqRef = useRef(0);
  const inspectorRequest = useRef(0);

  const refresh = async () => {
    try {
      const next = await fetchState();
      setState(next);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to refresh Mukha state.");
    }
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "p") {
        event.preventDefault();
        setPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    let stream: StateStream | null = null;
    const initialRefresh = async () => {
      try {
        const next = await fetchState(abort.signal);
        setState(next);
        setError(null);
      } catch (reason) {
        if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load Mukha state.");
      }
    };
    void initialRefresh();
    stream = subscribeState(
      (next) => { setState(next); setError(null); },
      (isConnected) => { connectedRef.current = isConnected; setConnected(isConnected); },
    );
    const pollId = window.setInterval(() => {
      if (!connectedRef.current) {
        void fetchState(abort.signal)
          .then((next) => { setState(next); setError(null); })
          .catch((reason) => { if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to refresh Mukha state."); });
      }
    }, 2000);
    return () => { abort.abort(); stream?.close(); window.clearInterval(pollId); };
  }, []);

  const openHistory = async () => {
    setHistoryOpen(true);
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      setHistory(await fetchHistory(30));
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : "Unable to load run history.");
    } finally {
      setHistoryBusy(false);
    }
  };

  const loadSummary = async (runId: string) => {
    const seq = ++summarySeqRef.current;
    const requestId = ++summaryRequest.current;
    setError(null);
    try {
      const summary = await fetchRunSummary(runId);
      if (seq !== summarySeqRef.current || requestId !== summaryRequest.current) return;
      setSummaryOverride(summary);
      setInspectorOverride(null);
      setHistoryOpen(false);
      setScreen("summary");
    } catch (reason) {
      if (seq === summarySeqRef.current && requestId === summaryRequest.current) {
        setError(reason instanceof Error ? reason.message : "Unable to load run summary.");
      }
    }
  };

  const loadInspector = async (runId: string) => {
    const requestId = ++inspectorRequest.current;
    setError(null);
    try {
      const inspector = await fetchInspector(runId);
      if (requestId !== inspectorRequest.current) return;
      setInspectorOverride(inspector);
      setHistoryOpen(false);
      setScreen("inspector");
    } catch (reason) {
      if (requestId === inspectorRequest.current) setError(reason instanceof Error ? reason.message : "Unable to load inspector data.");
    }
  };

  const chooseScreen = (next: Screen) => {
    if (next === "summary") setSummaryOverride(null);
    if (next === "inspector") {
      setInspectorOverride(null);
      const runId = state?.active_run?.run_id ?? state?.terminal_summary?.run_id;
      if (runId) { void loadInspector(runId); return; }
    }
    setScreen(next);
  };

  const handleClearHistory = async () => {
    if (!window.confirm("Clear all historical run records and telemetry? This cannot be undone.")) return;
    try {
      if (await clearHistory()) setHistory([]);
      else setHistoryError("History was not cleared.");
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : "Unable to clear history.");
    }
  };

  const handleClearCache = async () => {
    if (!window.confirm("Clear all Smriti cache entries?")) return;
    try {
      const count = await clearCache();
      setHistoryError(`Smriti cache cleared (${count} entries).`);
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : "Unable to clear cache.");
    }
  };

  const summary = summaryOverride ?? state?.terminal_summary ?? null;
  const inspector = inspectorOverride ?? state?.inspector ?? null;

  useEffect(() => {
    if (typeof window !== "undefined") {
      (window as any).__sarathi_load_summary = loadSummary;
      (window as any).loadRunSummary = loadSummary;
    }
  }, [loadSummary]);

  const paletteCommands = useMemo(() => [
    { id: "nav-home", label: "Navigate: Griha (Home - Intake / Setup)", action: () => chooseScreen("home") },
    { id: "nav-monitor", label: "Navigate: Pravritti (Monitor - Live Execution)", action: () => chooseScreen("monitor") },
    { id: "nav-review", label: "Navigate: Pariksha (Review - Review Queue)", action: () => chooseScreen("review") },
    { id: "nav-summary", label: "Navigate: Samapti (Summary - Run Summary)", action: () => chooseScreen("summary") },
    { id: "nav-inspector", label: "Navigate: Nirikshana (Inspector - Telemetry)", action: () => chooseScreen("inspector") },
    { id: "act-add-files", label: "Action: Add Input Files...", action: () => { chooseScreen("home"); void browseFiles().then((paths) => { if (paths.length) void intakePaths(paths, false); }); } },
    { id: "act-add-folder", label: "Action: Add Folder...", action: () => { chooseScreen("home"); void browseFolder().then((paths) => { if (paths.length) void intakePaths(paths, true); }); } },
    { id: "act-start-run", label: "Action: Start Document Processing", action: () => { chooseScreen("home"); } },
    {
      id: "act-cancel-run",
      label: "Action: Cancel Active Run",
      action: () => {
        if (state?.active_run?.run_id) void cancelRun(state.active_run.run_id);
      },
    },
    { id: "act-history", label: "Action: Open Run History (Ctrl+H)", action: () => void openHistory() },
    { id: "act-clear-history", label: "Action: Clear Terminal Run History", action: () => void handleClearHistory() },
    { id: "act-clear-cache", label: "Action: Clear Smriti Cache", action: () => void handleClearCache() },
    {
      id: "act-copy-logs",
      label: "Action: Copy Activity Logs to Clipboard",
      action: () => {
        const logs = inspector?.activity_logs ?? state?.inspector?.activity_logs ?? [];
        const text = logs.map((l) => `[${l.timestamp}] [${l.severity}] [${l.component}] ${l.message}`).join("\n");
        void navigator.clipboard.writeText(text || "No activity logs available.");
      },
    },
    {
      id: "act-export-diag",
      label: "Action: Export Run Diagnostics (JSON)",
      action: () => {
        const runId = inspector?.run_id ?? state?.active_run?.run_id ?? summary?.run_id;
        if (runId) {
          const link = document.createElement("a");
          link.href = `/api/runs/${encodeURIComponent(runId)}/diagnostics?download=1`;
          link.download = `diagnostics_${runId}.json`;
          document.body.appendChild(link);
          link.click();
          link.remove();
        }
      },
    },
  ], [state, summary, inspector]);

  const docCount = state?.input_selection?.items?.length ?? 0;
  const eligibleCount = state?.input_selection?.items?.filter((i) => i.is_eligible).length ?? 0;
  const totalSize = state?.input_selection?.items?.reduce((acc, i) => acc + (i.size_bytes || 0), 0) ?? 0;
  const policyLabel = state?.policy_label || (state?.requirement && isCloudAction(state.requirement) ? "Cloud" : "Local");

  return (
    <div class="app-shell app-container">
      <aside class="sidebar" data-purpose="main-sidebar">
        <div class="sidebar-top">
          {/* Branding & Creator Tag */}
          <div class="brand">
            <div class="brand-mark">S</div>
            <div class="brand-text">
              <h1>Sarathi</h1>
              <span class="brand-subtitle">Local Intelligence</span>
              <span class="brand-creator">by : VishNu KumaR</span>
            </div>
          </div>

          {/* Navigation Views */}
          <nav class="sidebar-nav" aria-label="Primary Navigation">
            {screens.map((item) => (
              <button
                class={screen === item.id ? "nav-item nav-tab active" : "nav-item nav-tab"}
                data-screen={item.id}
                onClick={() => chooseScreen(item.id)}
                type="button"
                key={item.id}
              >
                <span class="nav-glyph">{item.label.slice(0, 1)}</span>
                <span>{item.label}</span>
              </button>
            ))}
          </nav>

          {/* Action Utilities */}
          <div class="sidebar-actions">
            <button
              id="btn-command-palette"
              class="sidebar-action-btn"
              onClick={() => setPaletteOpen(true)}
              title="Command Palette (Ctrl+P)"
              type="button"
            >
              <svg class="icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16m-7 6h7" />
              </svg>
              <span>Commands</span>
            </button>
            <button
              id="btn-open-history"
              class="sidebar-action-btn"
              onClick={() => void openHistory()}
              title="Activity History"
              type="button"
            >
              <svg class="icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>History</span>
            </button>
          </div>

          {/* Workspace Pill */}
          <div class="sidebar-workspace-card">
            <div class="workspace-card-header">
              <span class="workspace-card-title">Workspace</span>
              <span class="workspace-card-badge">{eligibleCount} eligible</span>
            </div>
            <div class="workspace-card-status">
              <span class="workspace-dot" />
              <span>Ready</span>
              <span class="workspace-sep">·</span>
              <span class="workspace-mode">{policyLabel}</span>
            </div>
            <div class="workspace-card-stats">{docCount} docs · {formatBytes(totalSize)}</div>
          </div>
        </div>

        {/* Engine Telemetry / Status Footer */}
        <div class="sidebar-footer">
          <div class="telemetry-engine-row">
            <span class="telemetry-ping-wrap">
              <span class="telemetry-ping" />
              <span class="telemetry-dot" />
            </span>
            <span class="telemetry-label">Local Engine</span>
            <span class="telemetry-badge">Ready</span>
          </div>
          <div class="telemetry-detail-row">
            <span>{state?.requirement || "read_native"}</span>
            <span>rev {state?.state_revision ?? "1"}</span>
          </div>
        </div>
      </aside>

      <main class="workspace app-main">
        <header class="topbar app-header">
          <div class="topbar-left">
            <span class="eyebrow">Mukha</span>
            <h2 class="screen-title">{screens.find((item) => item.id === screen)?.label}</h2>
          </div>
          <div class="topbar-meta">
            <span class="badge">{state?.requirement || "No requirement"}</span>
            <span class="revision">rev {state?.state_revision ?? "—"}</span>
          </div>
        </header>

        {error ? <div class="error-banner" role="alert">{error}</div> : null}
        {!state ? (
          <div class="loading"><div class="spinner" /><strong>Connecting to Sarathi…</strong></div>
        ) : (
          <div class="screen">
            <div id="screen-home" class={`screen-view ${screen === "home" ? "active" : "hidden"}`}>
              <Home state={state} onError={setError} onStarted={(runId) => { setSummaryOverride(null); setInspectorOverride(null); chooseScreen("monitor"); void refresh().catch(() => undefined); if (!runId) setError("Run started without an identifier."); }} onPreview={(pathOrUrl, displayName) => setPreviewTarget({ pathOrUrl, displayName })} />
            </div>
            <div id="screen-monitor" class={`screen-view ${screen === "monitor" ? "active" : "hidden"}`}>
              <Monitor state={state} onError={setError} />
            </div>
            <div id="screen-review" class={`screen-view ${screen === "review" ? "active" : "hidden"}`}>
              <Review state={state} onError={setError} onRefresh={refresh} />
            </div>
            <div id="screen-summary" class={`screen-view ${screen === "summary" ? "active" : "hidden"}`} data-run-id={summary?.run_id ?? ""}>
              <Summary summary={summary} onError={setError} onReveal={revealRun} onPreview={(pathOrUrl, displayName) => setPreviewTarget({ pathOrUrl, displayName })} />
            </div>
            <div id="screen-inspector" class={`screen-view ${screen === "inspector" ? "active" : "hidden"}`}>
              <Inspector inspector={inspector} />
            </div>
          </div>
        )}
      </main>

      <HistoryDrawer
        open={historyOpen}
        history={history}
        busy={historyBusy}
        error={historyError}
        onClose={() => setHistoryOpen(false)}
        onSummary={(runId) => void loadSummary(runId)}
        onInspector={(runId) => void loadInspector(runId)}
        onClearHistory={() => void handleClearHistory()}
        onClearCache={() => void handleClearCache()}
      />

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={paletteCommands} />
      <DocumentPreviewModal target={previewTarget} onClose={() => setPreviewTarget(null)} />
    </div>
  );
}
