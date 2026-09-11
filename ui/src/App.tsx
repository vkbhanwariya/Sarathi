import { useEffect, useRef, useState } from "preact/hooks";

import {
  browseFiles,
  browseFolder,
  cancelRun,
  fetchState,
  intakePaths,
  previewPlan,
  startRun,
  submitReview,
  subscribeState,
  type StateStream,
} from "./api";
import type {
  ActionParameterView,
  ApplicationViewState,
  AvailableActionView,
  InputSelectionView,
  PlanPreview,
  PreflightView,
  RunRequest,
} from "./types";

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
  if (parameter.kind === "toggle") {
    return (
      <label class="toggle-row">
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.currentTarget.checked)} />
        <span><strong>{parameter.display_name}</strong>{parameter.description ? <small>{parameter.description}</small> : null}</span>
      </label>
    );
  }
  if (parameter.kind === "select") {
    return (
      <label class="field">
        <span>{parameter.display_name}</span>
        <select value={String(value ?? "")} onChange={(event) => onChange(event.currentTarget.value)}>
          {parameter.options.map(([optionValue, label]) => <option value={optionValue} key={optionValue}>{label}</option>)}
        </select>
      </label>
    );
  }
  return (
    <label class="field">
      <span>{parameter.display_name}</span>
      <input value={String(value ?? "")} onInput={(event) => onChange(event.currentTarget.value)} />
    </label>
  );
}

function Home({
  state,
  onStarted,
  onError,
}: {
  state: ApplicationViewState;
  onStarted: (runId: string) => void;
  onError: (message: string | null) => void;
}) {
  const initialRoots = state.input_selection.items.flatMap((item) => item.source_path ? [item.source_path] : []);
  const firstEnabled = state.available_actions.find((action) => action.is_enabled);
  const initialRequirement = state.available_actions.some((action) => action.action_id === state.requirement && action.is_enabled)
    ? state.requirement
    : firstEnabled?.action_id ?? "";
  const [roots, setRoots] = useState<string[]>(initialRoots);
  const [selection, setSelection] = useState<InputSelectionView>(state.input_selection);
  const [preflight, setPreflight] = useState<PreflightView | null>(state.preflight);
  const [recursive, setRecursive] = useState(false);
  const [manualPath, setManualPath] = useState("");
  const [requirement, setRequirement] = useState(initialRequirement);
  const [parameters, setParameters] = useState<Record<string, unknown>>(
    actionDefaults(state.available_actions.find((action) => action.action_id === initialRequirement)),
  );
  const [plan, setPlan] = useState<PlanPreview | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    setSelection(state.input_selection);
    setPreflight(state.preflight);
  }, [state.input_selection, state.preflight]);

  const activeAction = state.available_actions.find((action) => action.action_id === requirement);
  const eligiblePaths = selection.items.flatMap((item) => item.is_eligible && item.source_path ? [item.source_path] : []);

  const buildRequest = (): RunRequest => {
    const profileValue = activeAction?.parameters.find((parameter) => parameter.parameter_id === "profile");
    const profile = profileValue ? String(parameters.profile ?? profileValue.default_value ?? "instant") : "instant";
    const customOptions: Record<string, unknown> = {};
    for (const parameter of activeAction?.parameters ?? []) {
      if (parameter.parameter_id === "profile") continue;
      const value = parameters[parameter.parameter_id] ?? parameter.default_value;
      if (parameter.kind === "toggle") customOptions[parameter.parameter_id] = Boolean(value);
      else if (value !== undefined && value !== null && value !== "") customOptions[parameter.parameter_id] = value;
    }
    if (requirement === "ocr" && profile === "custom") customOptions.engine = "rapidocr";
    return { paths: eligiblePaths, requirement, profile, recursive, custom_options: customOptions };
  };

  const refreshIntake = async (nextRoots: readonly string[]) => {
    setWorking(true);
    onError(null);
    try {
      const result = await intakePaths(nextRoots, recursive);
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
    const next = [...new Set([...roots, ...paths.filter(Boolean)])];
    if (next.length) await refreshIntake(next);
  };

  useEffect(() => {
    if (!activeAction?.is_enabled || !eligiblePaths.length) {
      setPlan(null);
      setPlanError(null);
      return;
    }
    const timer = window.setTimeout(() => {
      void previewPlan(buildRequest())
        .then((next) => { setPlan(next); setPlanError(null); })
        .catch((reason) => { setPlan(null); setPlanError(reason instanceof Error ? reason.message : "Unable to preview plan."); });
    }, 200);
    return () => window.clearTimeout(timer);
  }, [requirement, JSON.stringify(parameters), recursive, eligiblePaths.join("\n"), activeAction?.is_enabled]);

  const chooseAction = (action: AvailableActionView) => {
    if (!action.is_enabled) return;
    setRequirement(action.action_id);
    setParameters(actionDefaults(action));
  };

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
    if (!activeAction?.is_enabled || !eligiblePaths.length || planError) return;
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

  return (
    <div class="screen-grid">
      <section class="hero panel">
        <div><span class="eyebrow">Document intelligence workspace</span><h2>Process documents without losing sight of the evidence.</h2><p>Sarathi keeps intake, execution, review and artifacts in one local workflow.</p></div>
        <div class="hero__status"><span class="status-dot" /><div><strong>{state.startup?.is_initializing ? "Initializing" : "Ready"}</strong><span>{state.policy_label || "Local runtime"}</span></div></div>
      </section>

      <div class="metrics-grid">
        <Metric label="Selected files" value={selection.total_files} detail={formatBytes(selection.total_size_bytes)} />
        <Metric label="Eligible" value={preflight?.eligible_count ?? 0} />
        <Metric label="Issues" value={preflight?.issue_count ?? 0} />
        <Metric label="Review queue" value={state.review_queue.length} />
      </div>

      <section class="panel span-2">
        <div class="section-heading"><div><span class="eyebrow">Intake</span><h3>Select documents</h3></div><div class="button-row"><button class="button secondary" disabled={working} onClick={() => void handleBrowse(false)} type="button">Add files</button><button class="button secondary" disabled={working} onClick={() => void handleBrowse(true)} type="button">Add folder</button><button class="button ghost" disabled={working || selection.total_files === 0} onClick={() => void refreshIntake([])} type="button">Clear</button></div></div>
        <div class="intake-controls">
          <label class="field grow"><span>Path</span><input placeholder="Paste a file or folder path" value={manualPath} onInput={(event) => setManualPath(event.currentTarget.value)} onKeyDown={(event) => { if (event.key === "Enter" && manualPath.trim()) { void addRoots([manualPath.trim()]); setManualPath(""); } }} /></label>
          <button class="button secondary" disabled={working || !manualPath.trim()} onClick={() => { void addRoots([manualPath.trim()]); setManualPath(""); }} type="button">Add path</button>
          <label class="toggle-row compact"><input type="checkbox" checked={recursive} onChange={(event) => { const checked = event.currentTarget.checked; setRecursive(checked); if (roots.length) void intakePaths(roots, checked).then((result) => { setSelection(result.input_selection); setPreflight(result.preflight); }).catch((reason) => onError(reason instanceof Error ? reason.message : "Unable to refresh intake.")); }} /><span><strong>Recursive folders</strong></span></label>
        </div>
        {selection.items.length ? <div class="file-list">{selection.items.slice(0, 20).map((item) => <div class="file-row" key={item.input_id}><div class="file-icon">{item.is_eligible ? "DOC" : "!"}</div><div class="file-main"><strong>{item.display_name}</strong><span>{item.media_type || "Unknown type"} · {formatBytes(item.size_bytes)}{item.issue_reason ? ` · ${item.issue_reason}` : ""}</span></div><span class={item.is_eligible ? "badge badge--ok" : "badge badge--warn"}>{item.is_eligible ? "Eligible" : "Issue"}</span></div>)}</div> : <EmptyState title="No documents selected" detail="Add files, a folder, or paste a path to begin." />}
        {selection.items.length > 20 ? <p class="quiet">Showing first 20 of {selection.items.length} inputs.</p> : null}
      </section>

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">Capabilities</span><h3>Processing action</h3></div></div>
        <div class="action-list">{state.available_actions.map((action) => <button class={action.action_id === requirement ? "action-card selected" : "action-card"} disabled={!action.is_enabled} key={action.action_id} onClick={() => chooseAction(action)} type="button"><span>{action.label}</span><small>{action.is_enabled ? action.description || action.action_id : action.disabled_reason || "Unavailable"}</small></button>)}</div>
        {activeAction?.parameters.length ? <div class="parameter-list">{activeAction.parameters.map((parameter) => <ActionParameter key={parameter.parameter_id} parameter={parameter} value={parameters[parameter.parameter_id] ?? parameter.default_value} onChange={(value) => setParameters((current) => ({ ...current, [parameter.parameter_id]: value }))} />)}</div> : null}
      </section>

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">Preflight</span><h3>Execution plan</h3></div></div>
        <p class="quiet">{preflight ? `${preflight.eligible_count} eligible · ${preflight.issue_count} issues` : "Select inputs to validate the run."}</p>
        {plan ? <div class="plan"><strong>{plan.document_count} document{plan.document_count === 1 ? "" : "s"}</strong><span>{plan.stages.map((stage) => stage.name).join(" → ")}</span>{plan.devices.length ? <small>{plan.devices.map((device) => `${device.device_type}${device.is_available ? "" : " unavailable"}`).join(" · ")}</small> : null}</div> : null}
        {planError ? <div class="inline-error">{planError}</div> : null}
        <button class="button primary full" disabled={working || !eligiblePaths.length || !activeAction?.is_enabled || Boolean(planError)} onClick={() => void handleStart()} type="button">{working ? "Working…" : "Start document processing"}</button>
      </section>
    </div>
  );
}

function Monitor({ state, onError }: { state: ApplicationViewState; onError: (message: string | null) => void }) {
  const run = state.active_run;
  const [cancelling, setCancelling] = useState(false);
  if (!run) return <EmptyState title="No active run" detail="The live execution view appears automatically when processing starts." />;
  const progress = run.progress?.percentage;
  const canCancel = run.status === "RUNNING";
  return (
    <div class="screen-grid"><section class="panel span-2"><div class="section-heading"><div><span class="eyebrow">Live run</span><h3>{run.run_id}</h3></div><div class="button-row"><span class="badge badge--active">{run.status}</span>{canCancel ? <button class="button danger" disabled={cancelling} onClick={() => { setCancelling(true); void cancelRun(run.run_id).catch((reason) => onError(reason instanceof Error ? reason.message : "Unable to cancel run.")).finally(() => setCancelling(false)); }} type="button">{cancelling ? "Cancelling…" : "Cancel"}</button> : null}</div></div><div class="progress-track" aria-label="Run progress"><div class="progress-track__fill" style={{ width: `${progress ?? 0}%` }} /></div><div class="metrics-grid compact"><Metric label="Progress" value={progress == null ? "Live" : `${progress.toFixed(0)}%`} /><Metric label="Files" value={`${run.terminal_files}/${run.total_files}`} /><Metric label="Elapsed" value={formatDuration(run.elapsed_ns)} /></div></section></div>
  );
}

function Review({ state, onRefresh, onError }: { state: ApplicationViewState; onRefresh: () => Promise<void>; onError: (message: string | null) => void }) {
  const [workingItem, setWorkingItem] = useState<string | null>(null);
  if (!state.review_queue.length) return <EmptyState title="Review queue is clear" detail="Low-confidence or unresolved items will be surfaced here." />;
  const apply = async (itemId: string, attemptId: string, action: "accept" | "unresolved", runId: string) => {
    setWorkingItem(itemId); onError(null);
    try { await submitReview(runId, itemId, attemptId, action); await onRefresh(); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "Unable to submit review action."); }
    finally { setWorkingItem(null); }
  };
  const runId = state.active_run?.run_id ?? state.terminal_summary?.run_id ?? "";
  return <section class="panel"><div class="section-heading"><div><span class="eyebrow">Human review</span><h3>{state.review_queue.length} items need attention</h3></div></div><div class="file-list">{state.review_queue.map((item) => <div class="review-card" key={item.item_id}><div class="file-row"><div class="file-icon">REV</div><div class="file-main"><strong>{item.file_display_name}</strong><span>{item.stage} · {item.issue_reason}</span></div><span class="badge badge--warn">{item.confidence == null ? "Review" : `${Math.round(item.confidence * 100)}%`}</span></div>{item.source_text || item.output_text ? <div class="review-text"><div><span>Source</span><p>{item.source_text || "—"}</p></div><div><span>Output</span><p>{item.output_text || "—"}</p></div></div> : null}<div class="button-row"><button class="button primary" disabled={workingItem === item.item_id || !runId || !item.available_actions.includes("accept")} onClick={() => void apply(item.item_id, item.attempt_id, "accept", runId)} type="button">Accept</button><button class="button secondary" disabled={workingItem === item.item_id || !runId || !item.available_actions.includes("unresolved")} onClick={() => void apply(item.item_id, item.attempt_id, "unresolved", runId)} type="button">Mark unresolved</button></div></div>)}</div></section>;
}

function Summary({ state }: { state: ApplicationViewState }) {
  const summary = state.terminal_summary;
  if (!summary) return <EmptyState title="No completed run" detail="Run outcomes and confirmed artifacts will appear here." />;
  return <div class="screen-grid"><div class="metrics-grid span-2"><Metric label="Status" value={summary.status} /><Metric label="Inputs" value={summary.total_inputs} /><Metric label="Successful" value={summary.successful_files ?? "—"} /><Metric label="Wall time" value={formatDuration(summary.wall_time_ns)} /></div><section class="panel span-2"><div class="section-heading"><div><span class="eyebrow">Output</span><h3>Confirmed artifacts</h3></div></div>{summary.artifacts.length ? <div class="file-list">{summary.artifacts.map((artifact) => <div class="file-row" key={artifact.artifact_id}><div class="file-icon">OUT</div><div class="file-main"><strong>{artifact.display_name}</strong><span>{artifact.role}</span></div><span class="quiet">{artifact.size_bytes == null ? "" : formatBytes(artifact.size_bytes)}</span><div class="button-row"><a class="button ghost" href={`/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/raw`} target="_blank">Open</a><a class="button secondary" href={`/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}`}>Download</a></div></div>)}</div> : <EmptyState title="No confirmed artifacts" detail="Only committed outputs are presented as final." />}</section>{summary.warnings.length || summary.failures.length ? <section class="panel span-2"><div class="section-heading"><div><span class="eyebrow">Run notes</span><h3>Warnings and failures</h3></div></div>{summary.warnings.map((warning) => <p class="note warning" key={warning}>{warning}</p>)}{summary.failures.map((failure) => <p class="note failure" key={failure}>{failure}</p>)}</section> : null}</div>;
}

function Inspector({ state }: { state: ApplicationViewState }) {
  const inspector = state.inspector;
  return inspector ? <div class="metrics-grid"><Metric label="Run" value={inspector.run_id} /><Metric label="Status" value={inspector.status} /><Metric label="Elapsed" value={formatDuration(inspector.elapsed_ns)} /></div> : <EmptyState title="Nothing selected for inspection" detail="Detailed runtime evidence remains available through the canonical inspector state." />;
}

export function App() {
  const [state, setState] = useState<ApplicationViewState | null>(null);
  const [screen, setScreen] = useState<Screen>("home");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const connectedRef = useRef(false);

  const refresh = async () => {
    const next = await fetchState();
    setState(next);
    setError(null);
  };

  useEffect(() => {
    const abort = new AbortController();
    let stream: StateStream | null = null;
    const initialRefresh = async () => {
      try { const next = await fetchState(abort.signal); setState(next); setError(null); }
      catch (reason) { if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load Mukha state."); }
    };
    void initialRefresh();
    stream = subscribeState(
      (next) => { setState(next); setError(null); },
      (isConnected) => { connectedRef.current = isConnected; setConnected(isConnected); },
    );
    const pollId = window.setInterval(() => {
      if (!connectedRef.current) void fetchState(abort.signal).then((next) => { setState(next); setError(null); }).catch((reason) => { if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to refresh Mukha state."); });
    }, 2000);
    return () => { abort.abort(); stream?.close(); window.clearInterval(pollId); };
  }, []);

  return <div class="app-shell"><aside class="sidebar"><div class="brand"><div class="brand-mark">S</div><div><strong>Sarathi</strong><span>V3 · Local Intelligence</span></div></div><nav aria-label="Main navigation">{screens.map((item) => <button class={screen === item.id ? "nav-item active" : "nav-item"} onClick={() => setScreen(item.id)} type="button" key={item.id}><span class="nav-glyph">{item.label.slice(0, 1)}</span>{item.label}</button>)}</nav><div class="sidebar-footer"><span class={connected ? "connection connection--live" : "connection"} /><span>{connected ? "Live state" : "Polling"}</span></div></aside><main class="workspace"><header class="topbar"><div><span class="eyebrow">Mukha</span><h1>{screens.find((item) => item.id === screen)?.label}</h1></div><div class="topbar-meta"><span class="badge">{state?.requirement || "No requirement"}</span><span class="revision">rev {state?.state_revision ?? "—"}</span></div></header>{error ? <div class="error-banner" role="alert">{error}</div> : null}{!state ? <div class="loading"><div class="spinner" /><strong>Connecting to Sarathi…</strong></div> : <div class="screen">{screen === "home" && <Home state={state} onError={setError} onStarted={(runId) => { setScreen("monitor"); void refresh().catch(() => undefined); if (!runId) setError("Run started without an identifier."); }} />}{screen === "monitor" && <Monitor state={state} onError={setError} />}{screen === "review" && <Review state={state} onError={setError} onRefresh={refresh} />}{screen === "summary" && <Summary state={state} />}{screen === "inspector" && <Inspector state={state} />}</div>}</main></div>;
}
