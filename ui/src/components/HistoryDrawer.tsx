import type { TerminalRunHistoryView } from "../types";

export function HistoryDrawer({
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
    <div
      class="drawer-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside aria-label="Run history" class="drawer">
        <div class="drawer-heading">
          <div>
            <span class="eyebrow">Terminal history</span>
            <h3>Recent runs</h3>
          </div>
          <button class="button ghost small" onClick={onClose} type="button">
            Close
          </button>
        </div>
        <div class="button-row" style="margin: 8px 0 14px;">
          <button id="btn-clear-history" class="button ghost small" onClick={onClearHistory} type="button">
            Clear history
          </button>
          <button id="btn-clear-cache" class="button ghost small" onClick={onClearCache} type="button">
            Clear cache
          </button>
        </div>
        {error ? <div class="inline-error">{error}</div> : null}
        {busy ? (
          <div class="loading">
            <div class="spinner" />
            <span>Loading history…</span>
          </div>
        ) : null}
        <div class="history-list">
          {history.length ? (
            history.map((item) => (
              <div class="history-item" key={item.run_id}>
                <div class="history-item__header">
                  <strong>{item.run_id}</strong>
                  <span class="badge">{item.status}</span>
                </div>
                <div class="history-item__meta">
                  <span>{item.requirement}</span>
                  <span>{item.duration_ms} ms</span>
                  <span>
                    {item.artifact_count} artifacts · {item.warning_count} warnings
                  </span>
                </div>
                <div class="button-row">
                  <button class="button ghost small" onClick={() => onSummary(item.run_id)} type="button">
                    Summary
                  </button>
                  <button class="button ghost small" onClick={() => onInspector(item.run_id)} type="button">
                    Inspector
                  </button>
                </div>
              </div>
            ))
          ) : (
            <p class="quiet">No saved runs in history.</p>
          )}
        </div>
      </aside>
    </div>
  );
}
