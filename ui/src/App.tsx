import { useEffect, useState } from "preact/hooks";

import { fetchState, subscribeState, type StateStream } from "./api";
import type { ApplicationViewState } from "./types";

type Screen = "home" | "monitor" | "review" | "summary" | "inspector";

const screens: readonly { id: Screen; label: string }[] = [
  { id: "home", label: "Home" },
  { id: "monitor", label: "Monitor" },
  { id: "review", label: "Review" },
  { id: "summary", label: "Summary" },
  { id: "inspector", label: "Inspector" },
];

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"] as const;
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDuration(ns: number): string {
  if (!Number.isFinite(ns) || ns <= 0) return "—";
  const seconds = ns / 1_000_000_000;
  if (seconds < 1) return `${Math.round(ns / 1_000_000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
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

function Home({ state }: { state: ApplicationViewState }) {
  const selected = state.input_selection;
  return (
    <div class="screen-grid">
      <section class="hero panel">
        <div>
          <span class="eyebrow">Document intelligence workspace</span>
          <h2>Process documents without losing sight of the evidence.</h2>
          <p>
            Sarathi keeps intake, execution, review and artifacts in one local workflow.
          </p>
        </div>
        <div class="hero__status">
          <span class="status-dot" />
          <div>
            <strong>{state.startup?.is_initializing ? "Initializing" : "Ready"}</strong>
            <span>{state.policy_label || "Local runtime"}</span>
          </div>
        </div>
      </section>

      <div class="metrics-grid">
        <Metric label="Selected files" value={selected.total_files} detail={formatBytes(selected.total_size_bytes)} />
        <Metric label="Available actions" value={state.available_actions.length} />
        <Metric label="Review queue" value={state.review_queue.length} />
        <Metric label="State revision" value={state.state_revision} />
      </div>

      <section class="panel span-2">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Intake</span>
            <h3>Selected documents</h3>
          </div>
          <span class="quiet">{selected.total_files ? `${selected.total_files} files` : "No selection"}</span>
        </div>
        {selected.items.length ? (
          <div class="file-list">
            {selected.items.slice(0, 8).map((item) => (
              <div class="file-row" key={item.input_id}>
                <div class="file-icon">{item.is_eligible ? "DOC" : "!"}</div>
                <div class="file-main">
                  <strong>{item.display_name}</strong>
                  <span>{item.media_type || "Unknown type"} · {formatBytes(item.size_bytes)}</span>
                </div>
                <span class={item.is_eligible ? "badge badge--ok" : "badge badge--warn"}>
                  {item.is_eligible ? "Ready" : "Check"}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="No documents selected" detail="Input controls will move here during the Home screen migration." />
        )}
      </section>

      <section class="panel">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Capabilities</span>
            <h3>Available actions</h3>
          </div>
        </div>
        {state.available_actions.length ? (
          <div class="action-list">
            {state.available_actions.slice(0, 6).map((action) => (
              <button class="action-card" disabled={!action.is_enabled} key={action.action_id} type="button">
                <span>{action.label}</span>
                <small>{action.is_enabled ? action.description || action.action_id : action.disabled_reason || "Unavailable"}</small>
              </button>
            ))}
          </div>
        ) : (
          <EmptyState title="No actions available" detail="Capability readiness from the current runtime will appear here." />
        )}
      </section>
    </div>
  );
}

function Monitor({ state }: { state: ApplicationViewState }) {
  const run = state.active_run;
  if (!run) return <EmptyState title="No active run" detail="The live execution view appears automatically when processing starts." />;
  const progress = run.progress?.percentage;
  return (
    <div class="screen-grid">
      <section class="panel span-2">
        <div class="section-heading">
          <div><span class="eyebrow">Live run</span><h3>{run.run_id}</h3></div>
          <span class="badge badge--active">{run.status}</span>
        </div>
        <div class="progress-track" aria-label="Run progress">
          <div class="progress-track__fill" style={{ width: `${progress ?? 0}%` }} />
        </div>
        <div class="metrics-grid compact">
          <Metric label="Progress" value={progress == null ? "Live" : `${progress.toFixed(0)}%`} />
          <Metric label="Files" value={`${run.terminal_files}/${run.total_files}`} />
          <Metric label="Elapsed" value={formatDuration(run.elapsed_ns)} />
        </div>
      </section>
    </div>
  );
}

function Review({ state }: { state: ApplicationViewState }) {
  if (!state.review_queue.length) return <EmptyState title="Review queue is clear" detail="Low-confidence or unresolved items will be surfaced here." />;
  return (
    <section class="panel">
      <div class="section-heading"><div><span class="eyebrow">Human review</span><h3>{state.review_queue.length} items need attention</h3></div></div>
      <div class="file-list">
        {state.review_queue.map((item) => (
          <div class="file-row" key={item.item_id}>
            <div class="file-icon">REV</div>
            <div class="file-main"><strong>{item.file_display_name}</strong><span>{item.stage} · {item.issue_reason}</span></div>
            <span class="badge badge--warn">{item.confidence == null ? "Review" : `${Math.round(item.confidence * 100)}%`}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function Summary({ state }: { state: ApplicationViewState }) {
  const summary = state.terminal_summary;
  if (!summary) return <EmptyState title="No completed run" detail="Run outcomes and confirmed artifacts will appear here." />;
  return (
    <div class="screen-grid">
      <div class="metrics-grid span-2">
        <Metric label="Status" value={summary.status} />
        <Metric label="Inputs" value={summary.total_inputs} />
        <Metric label="Successful" value={summary.successful_files ?? "—"} />
        <Metric label="Wall time" value={formatDuration(summary.wall_time_ns)} />
      </div>
      <section class="panel span-2">
        <div class="section-heading"><div><span class="eyebrow">Output</span><h3>Confirmed artifacts</h3></div></div>
        {summary.artifacts.length ? (
          <div class="file-list">
            {summary.artifacts.map((artifact) => (
              <div class="file-row" key={artifact.artifact_id}>
                <div class="file-icon">OUT</div>
                <div class="file-main"><strong>{artifact.display_name}</strong><span>{artifact.role}</span></div>
                <span class="quiet">{artifact.size_bytes == null ? "" : formatBytes(artifact.size_bytes)}</span>
              </div>
            ))}
          </div>
        ) : <EmptyState title="No confirmed artifacts" detail="Only committed outputs are presented as final." />}
      </section>
    </div>
  );
}

function Inspector({ state }: { state: ApplicationViewState }) {
  const inspector = state.inspector;
  return inspector ? (
    <div class="metrics-grid">
      <Metric label="Run" value={inspector.run_id} />
      <Metric label="Status" value={inspector.status} />
      <Metric label="Elapsed" value={formatDuration(inspector.elapsed_ns)} />
    </div>
  ) : <EmptyState title="Nothing selected for inspection" detail="Detailed runtime evidence will appear here after selecting a run." />;
}

export function App() {
  const [state, setState] = useState<ApplicationViewState | null>(null);
  const [screen, setScreen] = useState<Screen>("home");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    let stream: StateStream | null = null;
    let pollId: number | undefined;

    const refresh = async () => {
      try {
        const next = await fetchState(abort.signal);
        setState(next);
        setError(null);
      } catch (reason) {
        if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load Mukha state.");
      }
    };

    void refresh();
    stream = subscribeState(
      (next) => { setState(next); setError(null); },
      (isConnected) => setConnected(isConnected),
    );
    pollId = window.setInterval(() => { if (!connected) void refresh(); }, 2000);

    return () => {
      abort.abort();
      stream?.close();
      if (pollId !== undefined) window.clearInterval(pollId);
    };
  }, []);

  return (
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand"><div class="brand-mark">S</div><div><strong>Sarathi</strong><span>V3 · Local Intelligence</span></div></div>
        <nav aria-label="Main navigation">
          {screens.map((item) => (
            <button class={screen === item.id ? "nav-item active" : "nav-item"} onClick={() => setScreen(item.id)} type="button" key={item.id}>
              <span class="nav-glyph">{item.label.slice(0, 1)}</span>{item.label}
            </button>
          ))}
        </nav>
        <div class="sidebar-footer"><span class={connected ? "connection connection--live" : "connection"} /><span>{connected ? "Live state" : "Polling"}</span></div>
      </aside>

      <main class="workspace">
        <header class="topbar">
          <div><span class="eyebrow">Mukha</span><h1>{screens.find((item) => item.id === screen)?.label}</h1></div>
          <div class="topbar-meta"><span class="badge">{state?.requirement || "No requirement"}</span><span class="revision">rev {state?.state_revision ?? "—"}</span></div>
        </header>

        {error ? <div class="error-banner" role="alert">{error}</div> : null}
        {!state ? (
          <div class="loading"><div class="spinner" /><strong>Connecting to Sarathi…</strong></div>
        ) : (
          <div class="screen">
            {screen === "home" && <Home state={state} />}
            {screen === "monitor" && <Monitor state={state} />}
            {screen === "review" && <Review state={state} />}
            {screen === "summary" && <Summary state={state} />}
            {screen === "inspector" && <Inspector state={state} />}
          </div>
        )}
      </main>
    </div>
  );
}
