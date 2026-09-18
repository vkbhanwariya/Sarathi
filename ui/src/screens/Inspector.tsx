import { useState } from "preact/hooks";
import { EmptyState, Metric } from "../components/Common";
import { formatConfidence, formatDuration } from "../formatters";
import type { InspectorViewState } from "../types";

export function Inspector({ inspector }: { inspector: InspectorViewState | null }) {
  const [logQuery, setLogQuery] = useState("");
  const [logLevel, setLogLevel] = useState("ALL");
  const [regionQuery, setRegionQuery] = useState("");
  if (!inspector)
    return (
      <EmptyState
        title="Nothing selected for inspection"
        detail="Select a run from History or complete a run to inspect telemetry."
      />
    );

  const logs = inspector.activity_logs.filter((entry) => {
    if (logLevel !== "ALL" && entry.severity.toUpperCase() !== logLevel) return false;
    const target = `${entry.timestamp} ${entry.component} ${entry.message}`.toLowerCase();
    return !logQuery || target.includes(logQuery.toLowerCase());
  });
  const regions = inspector.region_confidence.filter((region) => {
    const target =
      `${region.region_id} ${region.file_display_name} ${region.page_number} ${region.region_type} ${region.method}`.toLowerCase();
    return !regionQuery || target.includes(regionQuery.toLowerCase());
  });

  return (
    <div class="screen-grid">
      <section class="panel span-2">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Technical inspector</span>
            <h3>{inspector.run_id}</h3>
          </div>
          <div class="button-row">
            <span class="badge badge--active">{inspector.status}</span>
            <a
              id="btn-export-diagnostics"
              class="button secondary"
              href={`/api/runs/${encodeURIComponent(inspector.run_id)}/diagnostics?download=1`}
            >
              Export diagnostics
            </a>
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
        <div class="section-heading">
          <div>
            <span class="eyebrow">System</span>
            <h3>Runtime facts</h3>
          </div>
        </div>
        <dl class="facts">
          {inspector.system_facts.map(([name, value]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section class="panel">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Confidence</span>
            <h3>Distribution</h3>
          </div>
        </div>
        <div class="data-list">
          {inspector.confidence_distribution.map(([bucket, count]) => (
            <div class="data-row" key={bucket}>
              <strong>{bucket}</strong>
              <span>{count}</span>
            </div>
          ))}
        </div>
      </section>

      <section class="panel span-2">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Activity</span>
            <h3>Logs</h3>
          </div>
        </div>
        <div class="filter-bar">
          <input
            class="search-input"
            placeholder="Search logs"
            value={logQuery}
            onInput={(e) => setLogQuery(e.currentTarget.value)}
          />
          <select value={logLevel} onChange={(e) => setLogLevel(e.currentTarget.value)}>
            <option value="ALL">ALL</option>
            <option value="INFO">INFO</option>
            <option value="WARN">WARN</option>
            <option value="ERROR">ERROR</option>
            <option value="FAILED">FAILED</option>
          </select>
          <button
            class="button ghost small"
            onClick={() =>
              void navigator.clipboard.writeText(
                inspector.activity_logs
                  .map((entry) => `[${entry.timestamp}] [${entry.severity}] ${entry.component}: ${entry.message}`)
                  .join("\n")
              )
            }
            type="button"
          >
            Copy logs
          </button>
        </div>
        <div class="log-list">
          {logs.length ? (
            logs.map((entry, index) => (
              <div class="log-entry" key={`${entry.timestamp}-${index}`}>
                <span>{entry.timestamp}</span>
                <strong>{entry.severity}</strong>
                <span>
                  {entry.component}: {entry.message}
                </span>
              </div>
            ))
          ) : (
            <p class="quiet">No logs match the current filter.</p>
          )}
        </div>
      </section>

      <section class="panel span-2">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Pages</span>
            <h3>Confidence</h3>
          </div>
        </div>
        <div class="data-list">
          {inspector.page_confidence.length ? (
            inspector.page_confidence.map((page) => (
              <div class="data-row wide" key={`${page.file_display_name}-${page.page_number}`}>
                <strong>{page.file_display_name}</strong>
                <span>Page {page.page_number}</span>
                <span>{formatConfidence(page.confidence_score)}</span>
                <span>{page.region_count} regions</span>
                <span>{page.review_recommended ? "Review" : "OK"}</span>
              </div>
            ))
          ) : (
            <p class="quiet">No page confidence records.</p>
          )}
        </div>
      </section>

      <section class="panel span-2">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Regions</span>
            <h3>Confidence details</h3>
          </div>
        </div>
        <input
          class="search-input"
          placeholder="Filter regions"
          value={regionQuery}
          onInput={(e) => setRegionQuery(e.currentTarget.value)}
        />
        <div class="data-list spaced">
          {regions.length ? (
            regions.map((region) => (
              <div class="data-row wide" key={region.region_id}>
                <strong>{region.region_id}</strong>
                <span>
                  {region.file_display_name} · P{region.page_number}
                </span>
                <span>{region.region_type}</span>
                <span>{formatConfidence(region.confidence_score)}</span>
                <span>{region.fallback_engine || region.method}</span>
              </div>
            ))
          ) : (
            <p class="quiet">No region confidence records match the filter.</p>
          )}
        </div>
      </section>
    </div>
  );
}
