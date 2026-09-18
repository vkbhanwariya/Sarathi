import { useEffect, useState } from "preact/hooks";
import { cancelRun } from "../api";
import { Metric } from "../components/Common";
import { formatConfidence, formatDuration } from "../formatters";
import type { ApplicationViewState, Screen } from "../types";

export function Monitor({
  state,
  onError,
  onNavigate,
}: {
  state: ApplicationViewState;
  onError: (message: string | null) => void;
  onNavigate?: (screen: Screen) => void;
}) {
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
          <div>
            <span class="eyebrow">Live run</span>
            <h3 id="monitor-run-id">{run?.run_id || "No active run"}</h3>
          </div>
          <div class="button-row">
            <span class="badge badge--active">{run?.status || "IDLE"}</span>
            {run?.status && run.status !== "RUNNING" && onNavigate && (
              <>
                <button
                  id="btn-monitor-view-summary"
                  class="button secondary"
                  onClick={() => onNavigate("summary")}
                  type="button"
                >
                  View Summary
                </button>
                <button
                  id="btn-monitor-process-another"
                  class="button primary"
                  onClick={() => onNavigate("home")}
                  type="button"
                >
                  Process Another Document
                </button>
              </>
            )}
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
        <span id="top-progress-stage" style="display:none">
          {run?.current_focus?.stage || "Processing..."}
        </span>
        <span id="top-progress-pct" style="display:none">
          {progress != null ? `${progress.toFixed(0)}%` : ""}
        </span>

        <div class="metrics-grid compact">
          <Metric label="Progress" value={progress == null ? "Live" : `${progress.toFixed(0)}%`} />
          <Metric label="Files" value={`${run?.terminal_files ?? 0}/${run?.total_files ?? 0}`} />
          <Metric label="Elapsed" value={formatDuration(run?.elapsed_ns)} />
          <Metric label="Workers" value={run?.active_workers?.length ?? 0} />
        </div>
      </section>

      <div
        class="modal-backdrop"
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.6)",
          display: showCancelDialog ? "grid" : "none",
          placeItems: "center",
          zIndex: 1000,
        }}
      >
        <dialog
          id="cancel-run-dialog"
          open
          class="cancel-dialog"
          aria-modal="true"
          style={{
            padding: "24px",
            background: "var(--surface)",
            borderRadius: "12px",
            border: "1px solid var(--border)",
            maxWidth: "440px",
            boxShadow: "var(--shadow)",
          }}
        >
          <div class="cancel-dialog-content">
            <h4 style={{ margin: "0 0 8px" }}>Cancel Document Processing?</h4>
            <p style={{ margin: "0 0 16px", color: "var(--muted)", fontSize: "13px" }}>
              Document processing will cancel cooperatively after the current stage completes.
            </p>
            <div class="button-row between">
              <button
                id="btn-cancel-dialog-abort"
                class="button ghost"
                onClick={() => setShowCancelDialog(false)}
                type="button"
              >
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
          <div class="section-heading">
            <div>
              <span class="eyebrow">Current focus</span>
              <h3>{run.current_focus.operation_name}</h3>
            </div>
          </div>
          <dl class="facts">
            <div>
              <dt>Stage</dt>
              <dd>{run.current_focus.stage}</dd>
            </div>
            <div>
              <dt>Device</dt>
              <dd>{run.current_focus.device_type}</dd>
            </div>
            <div>
              <dt>Elapsed</dt>
              <dd>{formatDuration(run.current_focus.elapsed_ns)}</dd>
            </div>
            <div>
              <dt>Activity</dt>
              <dd>{run.current_focus.last_activity || "—"}</dd>
            </div>
          </dl>
        </section>
      ) : null}

      <section class="panel">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Devices</span>
            <h3>Execution progress</h3>
          </div>
        </div>
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
        ) : (
          <p class="quiet">No device execution records yet.</p>
        )}
      </section>

      <section class="panel span-2">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Files</span>
            <h3>Run progress</h3>
          </div>
        </div>
        {run?.files?.length ? (
          <div class="data-list">
            {run.files.map((file) => (
              <div class="data-row wide" key={file.input_id}>
                <strong>{file.display_name}</strong>
                <span>
                  {file.status}
                  {file.cached ? (
                    <span
                      class="badge badge-cached"
                      style={{
                        marginLeft: "8px",
                        background: "rgba(56, 189, 248, 0.15)",
                        color: "#38bdf8",
                        border: "1px solid rgba(56, 189, 248, 0.3)",
                        borderRadius: "4px",
                        padding: "1px 6px",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                      }}
                    >
                      ⚡ Cached
                    </span>
                  ) : null}
                </span>
                <span>{file.current_stage || "—"}</span>
                <span>{formatDuration(file.elapsed_ns)}</span>
                <span>{file.error_message || (file.warning_count ? `${file.warning_count} warning(s)` : "")}</span>
              </div>
            ))}
          </div>
        ) : (
          <p class="quiet">File-level progress will appear as execution starts.</p>
        )}
      </section>
    </div>
  );
}
