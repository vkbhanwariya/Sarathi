import { useState } from "preact/hooks";
import { EmptyState, Metric } from "../components/Common";
import {
  formatBytes,
  formatConfidence,
  formatDuration,
  formatSummaryTitle,
} from "../formatters";
import type { RunSummaryView, Screen } from "../types";

export function Summary({
  summary,
  onReveal,
  onError,
  onPreview,
  onNavigate,
}: {
  summary: RunSummaryView | null;
  onReveal: (runId: string) => Promise<boolean>;
  onError: (message: string | null) => void;
  onPreview: (pathOrUrl: string, displayName: string) => void;
  onNavigate?: (screen: Screen) => void;
}) {
  const [revealing, setRevealing] = useState(false);
  if (!summary)
    return (
      <EmptyState
        title="No completed run"
        detail="Run outcomes and confirmed artifacts will appear here."
      />
    );

  const handleReveal = async () => {
    setRevealing(true);
    onError(null);
    try {
      if (!(await onReveal(summary.run_id))) onError("Output directory is unavailable for this run.");
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
            <span id="summary-run-id" style="display:none">
              {summary.run_id}
            </span>
          </div>
          <div class="button-row">
            <span class="badge badge--active">{summary.status}</span>
            {summary.cached ? (
              <span
                class="badge badge-cached"
                style={{
                  background: "rgba(56, 189, 248, 0.15)",
                  color: "#38bdf8",
                  border: "1px solid rgba(56, 189, 248, 0.3)",
                  borderRadius: "4px",
                  padding: "2px 8px",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                }}
              >
                ⚡ Cached
              </span>
            ) : null}
            {onNavigate && (
              <button
                id="btn-summary-process-another"
                class="button primary"
                onClick={() => onNavigate("home")}
                type="button"
              >
                Process Another Document
              </button>
            )}
            <button
              class="button secondary"
              disabled={revealing}
              onClick={() => void handleReveal()}
              type="button"
            >
              {revealing ? "Opening…" : "Open output folder"}
            </button>
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
      </section>

      <section class="panel span-2">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Output</span>
            <h3>Confirmed artifacts</h3>
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
                    Preview
                  </button>
                  <a
                    class="button ghost small"
                    href={`/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/raw`}
                    target="_blank"
                  >
                    Open
                  </a>
                  <a
                    class="button secondary small"
                    href={`/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}`}
                  >
                    Download
                  </a>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="No confirmed artifacts" detail="Only committed outputs are presented as final." />
        )}
      </section>

      <section class="panel">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Stages</span>
            <h3>Timing</h3>
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

      <section class="panel">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Hardware</span>
            <h3>Device summary</h3>
          </div>
        </div>
        {(summary.device_summaries ?? []).length ? (
          <div class="data-list">
            {(summary.device_summaries ?? []).map((device) => (
              <div class="data-row" key={device.device_type}>
                <strong>{device.device_type}</strong>
                <span>{device.execution_count} executions</span>
                <span>{formatDuration(device.avg_duration_ns)}</span>
                <span>{formatConfidence(device.avg_confidence)}</span>
              </div>
            ))}
          </div>
        ) : (
          <p class="quiet">No hardware execution records.</p>
        )}
      </section>

      {(summary.warnings ?? []).length || (summary.failures ?? []).length ? (
        <section class="panel span-2">
          <div class="section-heading">
            <div>
              <span class="eyebrow">Run notes</span>
              <h3>Warnings and failures</h3>
            </div>
          </div>
          {(summary.warnings ?? []).map((warning) => (
            <p class="note warning" key={`w-${warning}`}>
              {warning}
            </p>
          ))}
          {(summary.failures ?? []).map((failure) => (
            <p class="note failure" key={`f-${failure}`}>
              {failure}
            </p>
          ))}
        </section>
      ) : null}
    </div>
  );
}
