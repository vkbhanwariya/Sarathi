import { useMemo, useState } from "preact/hooks";
import { formatDuration } from "../formatters";
import type { TerminalRunHistoryView } from "../types";

export function History({
  history,
  busy,
  error,
  onRefresh,
  onSummary,
  onInspector,
  onClearHistory,
  onClearCache,
  onReveal,
  onNavigateHome,
}: {
  history: readonly TerminalRunHistoryView[];
  busy: boolean;
  error: string | null;
  onRefresh: () => Promise<void>;
  onSummary: (runId: string) => void;
  onInspector: (runId: string) => void;
  onClearHistory: () => void;
  onClearCache: () => void;
  onReveal: (runId: string) => Promise<boolean>;
  onNavigateHome?: () => void;
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "completed" | "failed" | "cancelled">("all");
  const [revealingRunId, setRevealingRunId] = useState<string | null>(null);

  const filteredItems = useMemo(() => {
    return history.filter((item) => {
      if (statusFilter !== "all") {
        const itemStatus = (item.status || "").toLowerCase();
        if (statusFilter === "completed" && itemStatus !== "completed" && itemStatus !== "success") return false;
        if (statusFilter === "failed" && itemStatus !== "failed") return false;
        if (statusFilter === "cancelled" && itemStatus !== "cancelled") return false;
      }
      if (!searchQuery.trim()) return true;
      const query = searchQuery.toLowerCase();
      return (
        item.run_id.toLowerCase().includes(query) ||
        (item.requirement || "").toLowerCase().includes(query) ||
        (item.profile || "").toLowerCase().includes(query) ||
        (item.status || "").toLowerCase().includes(query)
      );
    });
  }, [history, searchQuery, statusFilter]);

  const kpis = useMemo(() => {
    const total = history.length;
    const completed = history.filter((i) => {
      const s = (i.status || "").toLowerCase();
      return s === "completed" || s === "success";
    }).length;
    const failed = history.filter((i) => (i.status || "").toLowerCase() === "failed").length;
    const totalArtifacts = history.reduce((acc, i) => acc + (i.artifact_count || 0), 0);
    const totalDurationMs = history.reduce((acc, i) => acc + (i.duration_ms || 0), 0);
    const successRate = total > 0 ? Math.round((completed / total) * 100) : 0;
    return { total, completed, failed, totalArtifacts, totalDurationMs, successRate };
  }, [history]);

  const handleReveal = async (runId: string) => {
    setRevealingRunId(runId);
    try {
      await onReveal(runId);
    } finally {
      setRevealingRunId(null);
    }
  };

  const formatRequirement = (req: string) => {
    if (!req) return "General Processing";
    return req
      .replace(/^documents_extraction:/, "Extraction: ")
      .replace(/^bank_statements:/, "Bank Analysis: ")
      .replace(/^font_conversion:/, "Font Standardization: ")
      .replace(/^translation:/, "Translation: ")
      .replace(/_/g, " ");
  };

  const formatTimestamp = (ts: string) => {
    if (!ts) return "—";
    try {
      const d = new Date(ts);
      return d.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return ts;
    }
  };

  return (
    <div class="screen-view-container history-screen">
      {/* Top Header & Overview */}
      <section class="panel history-header-panel">
        <div class="history-top-row">
          <div>
            <span class="eyebrow">Audit & Run Ledger</span>
            <h2 class="panel-heading">Execution History</h2>
            <p class="panel-subheading">
              Chronological log of local document processing runs, deliverables, and hardware execution telemetry.
            </p>
          </div>
          <div class="button-row history-actions-group">
            <button
              id="btn-refresh-history"
              class="button secondary small"
              onClick={() => void onRefresh()}
              disabled={busy}
              type="button"
            >
              {busy ? "Refreshing…" : "↻ Refresh"}
            </button>
            <button
              id="btn-clear-history"
              class="button ghost small"
              onClick={onClearHistory}
              type="button"
              title="Clear all past run history"
            >
              Clear History
            </button>
            <button
              id="btn-clear-cache"
              class="button ghost small"
              onClick={onClearCache}
              type="button"
              title="Purge Smriti result cache"
            >
              Clear Cache
            </button>
          </div>
        </div>

        {error ? <div class="inline-error">{error}</div> : null}

        {/* KPI Metrics Strip */}
        <div class="metrics-grid compact history-kpis-grid">
          <div class="metric-card">
            <span class="metric-label">Total Runs</span>
            <strong class="metric-value">{kpis.total}</strong>
          </div>
          <div class="metric-card">
            <span class="metric-label">Success Rate</span>
            <strong class="metric-value metric-value--emerald">{kpis.successRate}%</strong>
          </div>
          <div class="metric-card">
            <span class="metric-label">Deliverables Produced</span>
            <strong class="metric-value">{kpis.totalArtifacts}</strong>
          </div>
          <div class="metric-card">
            <span class="metric-label">Total Execution Time</span>
            <strong class="metric-value">{formatDuration(kpis.totalDurationMs * 1_000_000)}</strong>
          </div>
        </div>
      </section>

      {/* Filter & Search Bar */}
      <section class="panel history-list-panel">
        <div class="history-controls-row">
          <div class="search-input-wrap history-search-wrap">
            <svg class="search-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              id="history-search-input"
              class="search-input"
              placeholder="Filter by run ID, workflow, profile..."
              value={searchQuery}
              onInput={(e) => setSearchQuery(e.currentTarget.value)}
            />
            {searchQuery && (
              <button class="search-clear-btn" onClick={() => setSearchQuery("")} type="button">
                ✕
              </button>
            )}
          </div>

          <div class="filter-pill-group history-filter-group" role="radiogroup" aria-label="Filter runs by status">
            {(["all", "completed", "failed", "cancelled"] as const).map((st) => (
              <button
                key={st}
                class={`filter-pill ${statusFilter === st ? "active" : ""}`}
                onClick={() => setStatusFilter(st)}
                type="button"
              >
                {st.charAt(0).toUpperCase() + st.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Run Items List */}
        <div class="history-card-list">
          {busy && history.length === 0 ? (
            <div class="loading">
              <div class="spinner" />
              <span>Loading run history…</span>
            </div>
          ) : filteredItems.length === 0 ? (
            <div class="history-empty-state">
              <div class="empty-icon-box">📜</div>
              <h3>{history.length === 0 ? "No runs recorded yet" : "No matching runs"}</h3>
              <p>
                {history.length === 0
                  ? "Completed processing runs and generated office deliverables will appear here."
                  : `No historical runs match "${searchQuery}" or the selected status filter.`}
              </p>
              {history.length === 0 && onNavigateHome && (
                <button class="button primary" onClick={onNavigateHome} type="button">
                  Start a Run in Griha
                </button>
              )}
            </div>
          ) : (
            filteredItems.map((item) => {
              const isSuccess = (item.status || "").toLowerCase() === "completed" || (item.status || "").toLowerCase() === "success";
              const isFailed = (item.status || "").toLowerCase() === "failed";
              const isCancelled = (item.status || "").toLowerCase() === "cancelled";
              const badgeClass = isSuccess ? "badge-emerald" : isFailed ? "badge-crimson" : isCancelled ? "badge-amber" : "badge-slate";

              return (
                <div class={`history-run-card ${isSuccess ? "is-success" : isFailed ? "is-failed" : ""}`} key={item.run_id}>
                  <div class="history-run-card__header">
                    <div class="history-run-title-group">
                      <span class={`status-dot ${isSuccess ? "status-dot--active" : isFailed ? "status-dot--error" : ""}`} />
                      <strong class="history-run-id">{item.run_id}</strong>
                      <span class={`badge ${badgeClass}`}>{item.status.toUpperCase()}</span>
                    </div>
                    <span class="history-run-time" title={item.start_time_utc || item.completed_at_utc}>
                      {formatTimestamp(item.completed_at_utc || item.start_time_utc)}
                    </span>
                  </div>

                  <div class="history-run-card__body">
                    <div class="history-run-details">
                      <div class="history-run-chip">
                        <span class="chip-label">Workflow:</span>
                        <strong class="chip-val">{formatRequirement(item.requirement)}</strong>
                      </div>
                      <div class="history-run-chip">
                        <span class="chip-label">Duration:</span>
                        <span class="chip-val font-mono">{item.duration_ms ? `${(item.duration_ms / 1000).toFixed(2)}s` : "—"}</span>
                      </div>
                      <div class="history-run-chip">
                        <span class="chip-label">Artifacts:</span>
                        <span class="chip-val">{item.artifact_count} deliverable{item.artifact_count === 1 ? "" : "s"}</span>
                      </div>
                      {item.warning_count > 0 && (
                        <div class="history-run-chip history-run-chip--warning">
                          <span class="chip-label">Warnings:</span>
                          <span class="chip-val">{item.warning_count}</span>
                        </div>
                      )}
                    </div>

                    <div class="history-run-actions">
                      <button
                        class="button secondary small history-action-btn"
                        onClick={() => onSummary(item.run_id)}
                        type="button"
                        title="View complete run outcomes and download artifacts"
                      >
                        📊 View Summary
                      </button>
                      <button
                        class="button secondary small history-action-btn"
                        onClick={() => onInspector(item.run_id)}
                        type="button"
                        title="Inspect telemetry, confidence, and system logs"
                      >
                        🔍 Inspect
                      </button>
                      {item.output_dir && (
                        <button
                          class="button ghost small history-action-btn"
                          disabled={revealingRunId === item.run_id}
                          onClick={() => void handleReveal(item.run_id)}
                          type="button"
                          title="Reveal output files in Windows File Explorer"
                        >
                          {revealingRunId === item.run_id ? "Opening…" : "📁 Open Folder"}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
