import { useEffect, useState } from "preact/hooks";
import { cancelRun } from "../api";
import { EmptyState, Metric } from "../components/Common";
import {
  formatBytes,
  formatConfidence,
  formatDuration,
  formatSummaryTitle,
} from "../formatters";
import type { ApplicationViewState, RunSummaryView, Screen } from "../types";

export function Monitor({
  state,
  summary: externalSummary,
  onError,
  onReveal,
  onPreview,
  onNavigate,
}: {
  state: ApplicationViewState;
  summary?: RunSummaryView | null;
  onError: (message: string | null) => void;
  onReveal?: (runId: string) => Promise<boolean>;
  onPreview?: (pathOrUrl: string, displayName: string) => void;
  onNavigate?: (screen: Screen) => void;
}) {
  const [localRun, setLocalRun] = useState(state.active_run);
  const [cancelling, setCancelling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [revealing, setRevealing] = useState(false);
  const [activeTab, setActiveTab] = useState<"summary" | "timeline">("summary");

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

  const [viewMode, setViewMode] = useState<"auto" | "live" | "summary">("auto");
  const run = localRun;

  useEffect(() => {
    if (run?.status === "RUNNING") {
      setViewMode("auto");
    }
  }, [run?.status]);

  const isRunning = run?.status === "RUNNING";
  const isTerminal =
    run?.status &&
    ["SUCCESS", "COMPLETED", "FAILED", "CANCELLED", "WARNING", "PARTIAL"].includes(run.status);
  const effectiveSummary = externalSummary ?? (isTerminal ? state.terminal_summary : null);

  const showSummaryMode =
    viewMode === "live"
      ? false
      : viewMode === "summary"
      ? Boolean(effectiveSummary)
      : !isRunning && Boolean(effectiveSummary);

  const progress = run?.progress?.percentage;
  const canCancel = run?.status === "RUNNING";

  const handleReveal = async () => {
    if (!effectiveSummary || !onReveal) return;
    setRevealing(true);
    onError(null);
    try {
      if (!(await onReveal(effectiveSummary.run_id))) {
        onError("Output directory is unavailable for this run.");
      }
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Unable to reveal output directory.");
    } finally {
      setRevealing(false);
    }
  };

  const cancelDialogModal = (
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
          boxShadow: "var(--shadow-md)",
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
  );

  // 1. TERMINAL SUMMARY VIEW (When task completed, or viewing historical summary)
  if (showSummaryMode && effectiveSummary) {
    const summary = effectiveSummary;
    const isSuccess = summary.status === "SUCCESS" || summary.status === "COMPLETED";
    const badgeClass = isSuccess ? "badge-emerald" : summary.status === "FAILED" ? "badge-crimson" : "badge-amber";

    return (
      <div class="screen-grid monitor-screen" id="screen-summary" data-run-id={summary.run_id}>
        <section class="panel span-2 summary-hero-panel">
          <div class="section-heading">
            <div>
              <span class="eyebrow">Run Summary & Results</span>
              <h3 id="summary-title">{formatSummaryTitle(summary.status)}</h3>
              <span id="summary-run-id" style={{ display: "none" }}>{summary.run_id}</span>
              <span id="monitor-run-id" style={{ display: "none" }}>{summary.run_id}</span>
            </div>
            <div class="button-row">
              <span class={`badge badge--active ${badgeClass}`}>{summary.status}</span>
              {summary.cached ? (
                <span class="badge badge-cached">⚡ Cached</span>
              ) : null}
              {run && (
                <button
                  class="button secondary"
                  onClick={() => setViewMode("live")}
                  type="button"
                  title="View hardware accelerator and stage telemetry"
                >
                  ⚡ Live Pipeline
                </button>
              )}
              {onNavigate && (
                <button
                  id="btn-summary-process-another"
                  class="button primary"
                  onClick={() => onNavigate("home")}
                  type="button"
                >
                  + Process Another Document
                </button>
              )}
              {onReveal && (
                <button
                  id="btn-summary-reveal"
                  class="button secondary"
                  disabled={revealing}
                  onClick={() => void handleReveal()}
                  type="button"
                >
                  {revealing ? "Opening…" : "📁 Open Output Folder"}
                </button>
              )}
            </div>
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

          <div class="summary-subnav-row" style={{ marginTop: "16px", display: "flex", gap: "8px" }}>
            <button
              class={`filter-pill ${activeTab === "summary" ? "active" : ""}`}
              onClick={() => setActiveTab("summary")}
              type="button"
            >
              📄 Deliverables & Inputs
            </button>
            <button
              class={`filter-pill ${activeTab === "timeline" ? "active" : ""}`}
              onClick={() => setActiveTab("timeline")}
              type="button"
            >
              ⚡ Hardware & Stage Timings
            </button>
          </div>
        </section>

        {activeTab === "summary" ? (
          <>
            {/* Confirmed Output Deliverables */}
            <section class="panel span-2">
              <div class="section-heading">
                <div>
                  <span class="eyebrow">Outputs</span>
                  <h3>Confirmed Deliverables</h3>
                </div>
              </div>
              {(summary.artifacts ?? []).length ? (
                <div class="file-list">
                  {(summary.artifacts ?? []).map((artifact) => (
                    <div class="file-row" key={artifact.artifact_id}>
                      <div class="file-icon">OUT</div>
                      <div class="file-main">
                        <strong>{artifact.display_name}</strong>
                        <span>
                          {artifact.role} · {formatBytes(artifact.size_bytes)}
                        </span>
                      </div>
                      <div class="button-row">
                        {onPreview && (
                          <button
                            class="button ghost small"
                            onClick={() =>
                              onPreview(
                                `/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/preview`,
                                artifact.display_name
                              )
                            }
                            type="button"
                          >
                            👁️ Preview
                          </button>
                        )}
                        <a
                          class="button ghost small"
                          href={`/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/raw`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          ↗ Open
                        </a>
                        <a
                          class="button secondary small"
                          href={`/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}`}
                          download
                        >
                          ⤓ Download
                        </a>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="No confirmed artifacts" detail="Only committed outputs are presented as final." />
              )}
            </section>

            {/* Run notes / Warnings & Failures */}
            {(summary.warnings ?? []).length || (summary.failures ?? []).length ? (
              <section class="panel span-2">
                <div class="section-heading">
                  <div>
                    <span class="eyebrow">Run Notes</span>
                    <h3>Warnings & Failures</h3>
                  </div>
                </div>
                {(summary.warnings ?? []).map((warning) => (
                  <p class="note warning" key={`w-${warning}`}>
                    ⚠️ {warning}
                  </p>
                ))}
                {(summary.failures ?? []).map((failure) => (
                  <p class="note failure" key={`f-${failure}`}>
                    ❌ {failure}
                  </p>
                ))}
              </section>
            ) : null}
          </>
        ) : (
          <>
            {/* Stage Timings */}
            <section class="panel">
              <div class="section-heading">
                <div>
                  <span class="eyebrow">Stages</span>
                  <h3>Stage Timings</h3>
                </div>
              </div>
              {(summary.stage_timings ?? []).length ? (
                <div class="data-list">
                  {(summary.stage_timings ?? []).map((stage) => (
                    <div class="data-row" key={stage.stage_name}>
                      <strong>{stage.stage_name}</strong>
                      <span>{stage.call_count} calls</span>
                      <span>{formatDuration(stage.duration_ns)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p class="quiet">No stage timing records.</p>
              )}
            </section>

            {/* Device Summary */}
            <section class="panel">
              <div class="section-heading">
                <div>
                  <span class="eyebrow">Hardware Accelerators</span>
                  <h3>Device Summary</h3>
                </div>
              </div>
              {(summary.device_summaries ?? []).length ? (
                <div class="data-list">
                  {(summary.device_summaries ?? []).map((dev) => (
                    <div class="data-row" key={dev.device_type}>
                      <strong>{dev.device_type}</strong>
                      <span>{dev.execution_count} runs</span>
                      <span>{formatDuration(dev.avg_duration_ns)}</span>
                      <span>{formatConfidence(dev.avg_confidence)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p class="quiet">Processed via Intel Core Ultra 5 125H & Arc iGPU.</p>
              )}
            </section>
          </>
        )}

        {cancelDialogModal}
      </div>
    );
  }

  // 2. LIVE / IDLE EXECUTION VIEW
  return (
    <div class="screen-grid monitor-screen">
      <section class="panel span-2 monitor-hero-panel">
        <div class="section-heading">
          <div>
            <span class="eyebrow">{isRunning ? "Active Execution" : "Live Pipeline"}</span>
            <div class="monitor-title-row">
              {isRunning ? (
                <span class="telemetry-ping-wrap" style={{ display: "inline-flex", marginRight: "8px" }}>
                  <span class="telemetry-ping" />
                  <span class="telemetry-dot" />
                </span>
              ) : null}
              <h3 id="monitor-run-id">{run?.run_id || "No active run"}</h3>
              <span id="summary-run-id" style={{ display: "none" }}>{run?.run_id || ""}</span>
              <div id="screen-summary" style={{ display: "none" }} data-run-id={run?.run_id || ""} />
            </div>
          </div>
          <div class="button-row">
            <span class={`badge badge--active ${isRunning ? "badge-indigo" : ""}`}>
              {isRunning ? "⚡ RUNNING" : run?.status || "IDLE"}
            </span>
            {effectiveSummary && (
              <button
                class="button secondary"
                onClick={() => setViewMode("summary")}
                type="button"
                title="Return to Summary view"
              >
                📄 View Summary
              </button>
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

      {cancelDialogModal}

      {run?.current_focus ? (
        <section class="panel">
          <div class="section-heading">
            <div>
              <span class="eyebrow">Current Focus</span>
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
            <span class="eyebrow">Hardware Accelerators</span>
            <h3>Execution Progress</h3>
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
          <p class="quiet">Active accelerators: Intel Core Ultra 5 125H & Arc iGPU</p>
        )}
      </section>

      <section class="panel span-2">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Files in Pipeline</span>
            <h3>Document Progress</h3>
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
                    <span class="badge badge-cached" style={{ marginLeft: "8px" }}>
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
