import { useEffect, useState } from "preact/hooks";
import { fetchDocumentPreview, fetchPdfPage } from "../api";
import { formatBytes } from "../formatters";
import type { DocumentPreviewData } from "../types";

export function DocumentPreviewModal({
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
        setData((prev) =>
          prev
            ? {
                ...prev,
                current_page: page,
                page_data_url: pageRes.page_data_url,
                page_text: pageRes.page_text,
              }
            : null
        );
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
      parts.push(
        <mark
          key={match.index}
          style={{ background: "var(--warning)", color: "#000", borderRadius: "2px" }}
        >
          {match[0]}
        </mark>
      );
      lastIdx = match.index + match[0].length;
    }
    if (lastIdx < raw.length) parts.push(raw.slice(lastIdx));
    return parts;
  };

  return (
    <div
      class="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <dialog id="doc-preview-dialog" class="preview-modal-dialog" open aria-modal="true" aria-label="Document Preview">
        <div class="preview-modal-header">
          <h3 id="preview-modal-title">{target.displayName || "Document Preview"}</h3>
          <button
            id="btn-close-preview"
            class="button ghost small"
            onClick={onClose}
            type="button"
            aria-label="Close Preview"
          >
            ✕ Close
          </button>
        </div>
        <div id="preview-modal-content" class="preview-modal-content">
          {loading && !data ? (
            <div class="loading compact">
              <div class="spinner" />
              <strong>Loading preview…</strong>
            </div>
          ) : error ? (
            <div>
              <div class="inline-error" style={{ marginBottom: "16px" }}>
                {error}
              </div>
              <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                <a href={rawUrl} target="_blank" class="button primary small">
                  ↗ Open in Browser Tab
                </a>
                <a href={`${rawUrl}?download=1`} download class="button secondary small">
                  ⤓ Download
                </a>
                <button class="button ghost small" onClick={onClose} type="button">
                  ✕ Close
                </button>
              </div>
            </div>
          ) : !data ? null : (
            <>
              {data.type === "pdf" && (
                <div>
                  <div class="doc-preview-toolbar">
                    <div class="doc-page-indicator">
                      <button
                        id="btn-pdf-prev"
                        class="button ghost small"
                        disabled={pdfPage <= 1 || loading}
                        onClick={() => void loadPdfPage(pdfPage - 1)}
                        type="button"
                      >
                        ◀ Prev
                      </button>
                      <span>
                        Page <strong id="pdf-curr-page-text">{pdfPage}</strong> of <strong>{totalPages}</strong>
                      </span>
                      <button
                        id="btn-pdf-next"
                        class="button ghost small"
                        disabled={pdfPage >= totalPages || loading}
                        onClick={() => void loadPdfPage(pdfPage + 1)}
                        type="button"
                      >
                        Next ▶
                      </button>
                    </div>
                    <div class="doc-preview-tabs">
                      <button
                        id="tab-btn-pdf-canvas"
                        class={pdfTab === "canvas" ? "doc-preview-tab-btn active" : "doc-preview-tab-btn"}
                        onClick={() => setPdfTab("canvas")}
                        type="button"
                      >
                        🖼️ Rendered Page
                      </button>
                      <button
                        id="tab-btn-pdf-native"
                        class={pdfTab === "native" ? "doc-preview-tab-btn active" : "doc-preview-tab-btn"}
                        onClick={() => setPdfTab("native")}
                        type="button"
                      >
                        🌐 Browser Viewer
                      </button>
                      <button
                        id="tab-btn-pdf-text"
                        class={pdfTab === "text" ? "doc-preview-tab-btn active" : "doc-preview-tab-btn"}
                        onClick={() => setPdfTab("text")}
                        type="button"
                      >
                        📝 Page Text
                      </button>
                    </div>
                    <div class="button-row">
                      <button
                        id="btn-pdf-zoom-in"
                        class="button secondary small"
                        onClick={() => setPdfZoom((z) => Math.min(3.0, z + 0.25))}
                        title="Zoom In"
                        type="button"
                      >
                        ➕
                      </button>
                      <button
                        id="btn-pdf-zoom-out"
                        class="button secondary small"
                        onClick={() => setPdfZoom((z) => Math.max(0.5, z - 0.25))}
                        title="Zoom Out"
                        type="button"
                      >
                        ➖
                      </button>
                      <button
                        id="btn-pdf-zoom-reset"
                        class="button secondary small"
                        onClick={() => setPdfZoom(1.0)}
                        title="Reset Zoom"
                        type="button"
                      >
                        Reset
                      </button>
                      <a href={rawUrl} target="_blank" class="button ghost small" title="Open in dedicated browser tab">
                        ↗ Open Tab
                      </a>
                      <a href={`${rawUrl}?download=1`} download class="button secondary small" title="Download file">
                        ⤓ Download
                      </a>
                    </div>
                  </div>
                  <div
                    id="pdf-pane-canvas"
                    class="preview-canvas-container"
                    style={{ display: pdfTab === "canvas" ? "flex" : "none" }}
                  >
                    <img
                      id="pdf-page-image"
                      src={data.page_data_url || ""}
                      alt={`Page ${pdfPage}`}
                      style={{ transform: `scale(${pdfZoom})` }}
                    />
                  </div>
                  <div
                    id="pdf-pane-native"
                    style={{ display: pdfTab === "native" ? "block" : "none", width: "100%" }}
                  >
                    <iframe
                      src={rawUrl}
                      style={{
                        width: "100%",
                        height: "560px",
                        border: "1px solid var(--border)",
                        borderRadius: "8px",
                        background: "#ffffff",
                      }}
                      title="Native PDF Viewer"
                    />
                  </div>
                  <div id="pdf-pane-text" style={{ display: pdfTab === "text" ? "block" : "none", width: "100%" }}>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginBottom: "8px",
                      }}
                    >
                      <span class="quiet">Extracted text layer for current page</span>
                      <button
                        id="btn-copy-pdf-page-text"
                        class="button secondary small"
                        onClick={() => copyToClipboard(data.page_text || "")}
                        type="button"
                      >
                        {copied ? "✓ Copied!" : "📋 Copy Page Text"}
                      </button>
                    </div>
                    <pre
                      id="pdf-page-text-content"
                      style={{
                        fontFamily: "monospace",
                        fontSize: "12px",
                        lineHeight: "1.6",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        background: "var(--surface-soft)",
                        padding: "16px",
                        borderRadius: "8px",
                        maxHeight: "500px",
                        overflowY: "auto",
                      }}
                    >
                      {data.page_text || "(No text detected on this page)"}
                    </pre>
                  </div>
                </div>
              )}

              {data.type === "word" && (
                <div>
                  <div class="doc-preview-toolbar">
                    <div class="doc-page-indicator">
                      <span>
                        Word Document · <strong>{data.total_paragraphs ?? data.paragraphs?.length ?? 0}</strong>{" "}
                        paragraphs{data.tables?.length ? ` · ${data.tables.length} tables` : ""} (
                        {formatBytes(data.size)})
                      </span>
                    </div>
                    <div class="button-row">
                      <button
                        id="btn-copy-word-text"
                        class="button secondary small"
                        onClick={() => copyToClipboard((data.paragraphs || []).join("\n\n"))}
                        type="button"
                      >
                        {copied ? "✓ Copied!" : "📋 Copy Text"}
                      </button>
                      <a href={`${rawUrl}?download=1`} download class="button primary small">
                        ⤓ Download (.docx)
                      </a>
                    </div>
                  </div>
                  <div class="word-doc-sheet">
                    {data.paragraphs && data.paragraphs.length > 0 ? (
                      data.paragraphs.map((para, i) => (
                        <p key={i} style={{ marginBottom: "12px", textAlign: "justify" }}>
                          {para}
                        </p>
                      ))
                    ) : (
                      <p class="quiet">(Empty document or no readable paragraphs)</p>
                    )}
                    {data.tables?.map((table, tIdx) => (
                      <div key={tIdx} style={{ margin: "20px 0" }}>
                        <div style={{ fontSize: "11px", color: "var(--muted)", marginBottom: "6px" }}>
                          Table {tIdx + 1}
                        </div>
                        <table class="data-table">
                          {table.headers?.length ? (
                            <thead>
                              <tr>
                                {table.headers.map((h, hIdx) => (
                                  <th key={hIdx}>{h}</th>
                                ))}
                              </tr>
                            </thead>
                          ) : null}
                          <tbody>
                            {table.rows?.map((row, rIdx) => (
                              <tr key={rIdx}>
                                {row.map((cell, cIdx) => (
                                  <td key={cIdx}>{cell}</td>
                                ))}
                              </tr>
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
                      <span>
                        Text File · <strong>{(data.content || "").split("\n").length}</strong> lines (
                        {formatBytes(data.size)}){data.truncated ? " · (Truncated to 256KB)" : ""}
                      </span>
                    </div>
                    <div class="button-row">
                      <input
                        id="txt-search-input"
                        class="search-input"
                        style={{ width: "160px", minHeight: "29px", padding: "4px 8px", fontSize: "12px" }}
                        placeholder="Find in text…"
                        value={textSearch}
                        onInput={(e) => setTextSearch(e.currentTarget.value)}
                      />
                      <button
                        id="btn-toggle-wrap"
                        class="button secondary small"
                        onClick={() => setTextWrap((w) => !w)}
                        type="button"
                      >
                        ↔ Wrap: {textWrap ? "On" : "Off"}
                      </button>
                      <button
                        id="btn-copy-text"
                        class="button secondary small"
                        onClick={() => copyToClipboard(data.content || "")}
                        type="button"
                      >
                        {copied ? "✓ Copied!" : "📋 Copy Content"}
                      </button>
                      <a href={`${rawUrl}?download=1`} download class="button ghost small">
                        ⤓ Download
                      </a>
                    </div>
                  </div>
                  <pre
                    id="txt-code-block"
                    style={{
                      fontFamily: "monospace",
                      fontSize: "12px",
                      lineHeight: "1.6",
                      whiteSpace: textWrap ? "pre-wrap" : "pre",
                      wordBreak: textWrap ? "break-word" : "normal",
                      background: "var(--surface-soft)",
                      padding: "16px",
                      borderRadius: "8px",
                      maxHeight: "520px",
                      overflow: "auto",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <code id="txt-code-content">{renderHighlightedContent(data.content || "", textSearch)}</code>
                  </pre>
                </div>
              )}

              {data.type === "tabular" && (
                <div>
                  <div class="doc-preview-toolbar">
                    <div class="doc-page-indicator">
                      <span>
                        Tabular Data · Showing {data.rows?.length ?? 0} rows ({formatBytes(data.size)})
                      </span>
                    </div>
                    <div class="button-row">
                      <a href={`${rawUrl}?download=1`} download class="button primary small">
                        ⤓ Download Table
                      </a>
                    </div>
                  </div>
                  <div
                    style={{
                      maxHeight: "520px",
                      overflow: "auto",
                      border: "1px solid var(--border)",
                      borderRadius: "8px",
                    }}
                  >
                    <table class="data-table">
                      {data.headers?.length ? (
                        <thead>
                          <tr>
                            {data.headers.map((h, i) => (
                              <th key={i}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                      ) : null}
                      <tbody>
                        {data.rows?.map((row, rIdx) => (
                          <tr key={rIdx}>
                            {row.map((c, cIdx) => (
                              <td key={cIdx}>{c}</td>
                            ))}
                          </tr>
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
                      <button
                        id="btn-zoom-in"
                        class="button secondary small"
                        onClick={() => setImageZoom((z) => Math.min(3.0, z + 0.25))}
                        type="button"
                      >
                        ➕
                      </button>
                      <button
                        id="btn-zoom-out"
                        class="button secondary small"
                        onClick={() => setImageZoom((z) => Math.max(0.5, z - 0.25))}
                        type="button"
                      >
                        ➖
                      </button>
                      <button
                        id="btn-zoom-reset"
                        class="button secondary small"
                        onClick={() => setImageZoom(1.0)}
                        type="button"
                      >
                        Reset
                      </button>
                      <a href={`${rawUrl}?download=1`} download class="button primary small">
                        ⤓ Download
                      </a>
                    </div>
                  </div>
                  <div class="preview-canvas-container">
                    <img
                      id="preview-img"
                      src={data.data_url || ""}
                      alt="Preview"
                      style={{ transform: `scale(${imageZoom})`, transition: "transform 0.15s ease" }}
                    />
                  </div>
                </div>
              )}

              {(data.type === "binary" || !["pdf", "word", "text", "tabular", "image"].includes(data.type || "")) && (
                <div style={{ textAlign: "center", padding: "40px" }}>
                  <div style={{ fontSize: "48px", marginBottom: "12px" }}>📦</div>
                  <h3>{data.name || target.displayName}</h3>
                  <p class="quiet" style={{ margin: "8px 0 16px 0" }}>
                    Binary file ({formatBytes(data.size)})
                  </p>
                  <a href={`${rawUrl}?download=1`} download class="button primary small">
                    ⤓ Download File
                  </a>
                </div>
              )}
            </>
          )}
        </div>
      </dialog>
    </div>
  );
}
