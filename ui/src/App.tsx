import { useEffect, useMemo, useRef, useState } from "preact/hooks";

import {
  browseFiles,
  browseFolder,
  cancelRun,
  clearCache,
  clearHistory,
  fetchHistory,
  fetchInspector,
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
  InputItemView,
  InputSelectionView,
  InspectorViewState,
  PlanPreview,
  PreflightView,
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

function formatBytes(bytes: number | null | undefined): string {
  if (!Number.isFinite(bytes) || !bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"] as const;
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDuration(ns: number | null | undefined): string {
  if (!Number.isFinite(ns) || !ns || ns <= 0) return "—";
  const seconds = ns / 1_000_000_000;
  if (seconds < 1) return `${Math.round(ns / 1_000_000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function formatConfidence(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
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
        <select value={String(value ?? "")} onChange={(event) => onChange(event.currentTarget.value)}>
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
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [recursive, setRecursive] = useState(false);
  const [manualPath, setManualPath] = useState("");
  const [requirement, setRequirement] = useState(initialRequirement);
  const [parameters, setParameters] = useState<Record<string, unknown>>(
    actionDefaults(state.available_actions.find((action) => action.action_id === initialRequirement)),
  );
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

  const activeAction = state.available_actions.find((action) => action.action_id === requirement);
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

  useEffect(() => setPage(1), [query, filter]);

  const buildRequest = (): RunRequest => {
    const profileParameter = activeAction?.parameters.find((parameter) => parameter.parameter_id === "profile");
    const profile = profileParameter
      ? String(parameters.profile ?? profileParameter.default_value ?? "instant")
      : "instant";
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
    if (!activeAction?.is_enabled || !eligiblePaths.length) {
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
        <div>
          <span class="eyebrow">Document intelligence workspace</span>
          <h2>Process documents without losing sight of the evidence.</h2>
          <p>Sarathi keeps intake, execution, review and artifacts in one local workflow.</p>
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
        <Metric label="Selected files" value={visibleItems.length} detail={formatBytes(totalSize)} />
        <Metric label="Eligible" value={eligibleCount} />
        <Metric label="Issues" value={issueCount} />
        <Metric label="Review queue" value={state.review_queue.length} />
      </div>

      <section class="panel span-2">
        <div class="section-heading">
          <div><span class="eyebrow">Intake</span><h3>Select documents</h3></div>
          <div class="button-row">
            <button class="button secondary" disabled={working} onClick={() => void handleBrowse(false)} type="button">Add files</button>
            <button class="button secondary" disabled={working} onClick={() => void handleBrowse(true)} type="button">Add folder</button>
            <button class="button ghost" disabled={working || visibleItems.length === 0} onClick={() => { setExcluded(new Set()); void refreshIntake([]); }} type="button">Clear</button>
          </div>
        </div>

        <div class="intake-controls">
          <label class="field grow">
            <span>Path</span>
            <input
              placeholder="Paste a file or folder path"
              value={manualPath}
              onInput={(event) => setManualPath(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && manualPath.trim()) {
                  void addRoots([manualPath.trim()]);
                  setManualPath("");
                }
              }}
            />
          </label>
          <button class="button secondary" disabled={working || !manualPath.trim()} onClick={() => { void addRoots([manualPath.trim()]); setManualPath(""); }} type="button">Add path</button>
          <label class="toggle-row compact">
            <input
              type="checkbox"
              checked={recursive}
              onChange={(event) => {
                const checked = event.currentTarget.checked;
                setRecursive(checked);
                if (roots.length) void refreshIntake(roots, checked);
              }}
            />
            <span><strong>Recursive folders</strong></span>
          </label>
        </div>

        {visibleItems.length ? (
          <>
            <div class="filter-bar">
              <input class="search-input" placeholder="Search selected documents" value={query} onInput={(event) => setQuery(event.currentTarget.value)} />
              <div class="segmented">
                <button class={filter === "all" ? "active" : ""} onClick={() => setFilter("all")} type="button">All {visibleItems.length}</button>
                <button class={filter === "eligible" ? "active" : ""} onClick={() => setFilter("eligible")} type="button">Eligible {eligibleCount}</button>
                <button class={filter === "issues" ? "active" : ""} onClick={() => setFilter("issues")} type="button">Issues {issueCount}</button>
              </div>
            </div>
            <div class="file-list">
              {pagedItems.map((item) => (
                <div class="file-row" key={item.input_id}>
                  <div class="file-icon">{item.is_eligible ? "DOC" : "!"}</div>
                  <div class="file-main">
                    <strong>{item.display_name}</strong>
                    <span>{item.media_type || "Unknown type"} · {formatBytes(item.size_bytes)}{item.issue_reason ? ` · ${item.issue_reason}` : ""}</span>
                  </div>
                  <span class={item.is_eligible ? "badge badge--ok" : "badge badge--warn"}>{item.is_eligible ? "Eligible" : "Issue"}</span>
                  <div class="button-row">
                    <a class="button ghost small" href={`/api/inputs/${encodeURIComponent(item.input_id)}/raw`} target="_blank">Open</a>
                    <button class="button ghost small" onClick={() => void removeItem(item)} type="button">Remove</button>
                  </div>
                </div>
              ))}
            </div>
            {filteredItems.length === 0 ? <p class="quiet">No documents match the current filter.</p> : null}
            {filteredItems.length > pageSize ? (
              <div class="pagination">
                <button class="button ghost small" disabled={currentPage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))} type="button">Previous</button>
                <span>Page {currentPage} of {pageCount} · {filteredItems.length} matching</span>
                <button class="button ghost small" disabled={currentPage >= pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))} type="button">Next</button>
              </div>
            ) : null}
          </>
        ) : (
          <EmptyState title="No documents selected" detail="Add files, a folder, or paste a path to begin." />
        )}
      </section>

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">Capabilities</span><h3>Processing action</h3></div></div>
        <div class="action-list">
          {state.available_actions.map((action) => (
            <button
              class={action.action_id === requirement ? "action-card selected" : "action-card"}
              disabled={!action.is_enabled}
              key={action.action_id}
              onClick={() => chooseAction(action)}
              type="button"
            >
              <span>{action.label}</span>
              <small>{action.is_enabled ? action.description || action.action_id : action.disabled_reason || "Unavailable"}</small>
            </button>
          ))}
        </div>
        {activeAction?.parameters.length ? (
          <div class="parameter-list">
            {activeAction.parameters.map((parameter) => (
              <ActionParameter
                key={parameter.parameter_id}
                parameter={parameter}
                value={parameters[parameter.parameter_id] ?? parameter.default_value}
                onChange={(value) => setParameters((current) => ({ ...current, [parameter.parameter_id]: value }))}
              />
            ))}
          </div>
        ) : null}
      </section>

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">Preflight</span><h3>Execution plan</h3></div></div>
        <p class="quiet">{preflight ? `${eligibleCount} eligible · ${issueCount} issues` : "Select inputs to validate the run."}</p>
        {plan ? (
          <div class="plan">
            <strong>{plan.document_count} document{plan.document_count === 1 ? "" : "s"}</strong>
            <span>{plan.stages.map((stage) => stage.name).join(" → ")}</span>
            {plan.devices.length ? <small>{plan.devices.map((device) => `${device.device_type}${device.is_available ? "" : " unavailable"}`).join(" · ")}</small> : null}
          </div>
        ) : null}
        {planError ? <div class="inline-error">{planError}</div> : null}
        <button class="button primary full" disabled={working || !eligiblePaths.length || !activeAction?.is_enabled || Boolean(planError)} onClick={() => void handleStart()} type="button">
          {working ? "Working…" : "Start document processing"}
        </button>
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
    <div class="screen-grid">
      <section class="panel span-2">
        <div class="section-heading">
          <div><span class="eyebrow">Live run</span><h3>{run.run_id}</h3></div>
          <div class="button-row">
            <span class="badge badge--active">{run.status}</span>
            {canCancel ? (
              <button
                class="button danger"
                disabled={cancelling}
                onClick={() => {
                  setCancelling(true);
                  void cancelRun(run.run_id)
                    .catch((reason) => onError(reason instanceof Error ? reason.message : "Unable to cancel run."))
                    .finally(() => setCancelling(false));
                }}
                type="button"
              >
                {cancelling ? "Cancelling…" : "Cancel"}
              </button>
            ) : null}
          </div>
        </div>
        <div class="progress-track" aria-label="Run progress"><div class="progress-track__fill" style={{ width: `${progress ?? 0}%` }} /></div>
        <div class="metrics-grid compact">
          <Metric label="Progress" value={progress == null ? "Live" : `${progress.toFixed(0)}%`} />
          <Metric label="Files" value={`${run.terminal_files}/${run.total_files}`} />
          <Metric label="Elapsed" value={formatDuration(run.elapsed_ns)} />
          <Metric label="Workers" value={run.active_workers.length} />
        </div>
      </section>

      {run.current_focus ? (
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
        {run.device_progress.length ? (
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
        {run.files.length ? (
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
  const [selectedId, setSelectedId] = useState<string | null>(state.review_queue[0]?.item_id ?? null);
  const [workingItem, setWorkingItem] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savedDrafts, setSavedDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!state.review_queue.some((item) => item.item_id === selectedId)) {
      setSelectedId(state.review_queue[0]?.item_id ?? null);
    }
  }, [state.review_queue, selectedId]);

  if (!state.review_queue.length) return <EmptyState title="Review queue is clear" detail="Low-confidence or unresolved items will be surfaced here." />;

  const selectedIndex = Math.max(0, state.review_queue.findIndex((item) => item.item_id === selectedId));
  const item = state.review_queue[selectedIndex];
  if (!item) return null;
  const runId = state.active_run?.run_id ?? state.terminal_summary?.run_id ?? "";
  const draftValue = drafts[item.item_id] ?? item.draft_proposal ?? item.output_text;

  const apply = async (action: "accept" | "unresolved") => {
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

  return (
    <div class="screen-grid">
      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">Human review</span><h3>{state.review_queue.length} items</h3></div></div>
        <div class="review-list">
          {state.review_queue.map((reviewItem) => (
            <button class={reviewItem.item_id === item.item_id ? "review-list-item active" : "review-list-item"} key={reviewItem.item_id} onClick={() => setSelectedId(reviewItem.item_id)} type="button">
              <strong>{reviewItem.file_display_name}</strong>
              <span>{reviewItem.stage} · {reviewItem.status}</span>
            </button>
          ))}
        </div>
      </section>

      <section class="panel">
        <div class="section-heading">
          <div><span class="eyebrow">Review item</span><h3>{item.item_id}</h3></div>
          <span class="badge badge--warn">{item.status.toUpperCase()}</span>
        </div>
        <p class="quiet">{item.issue_reason}</p>
        <div class="review-text">
          <div><span>Source</span><p>{item.source_text || "—"}</p></div>
          <div><span>Output</span><p>{item.output_text || "—"}</p></div>
        </div>
        <label class="field">
          <span>Draft proposal</span>
          <textarea value={draftValue} onInput={(event) => setDrafts((current) => ({ ...current, [item.item_id]: event.currentTarget.value }))} />
        </label>
        <div class="button-row between">
          <div class="button-row">
            <button class="button ghost" disabled={selectedIndex <= 0} onClick={() => setSelectedId(state.review_queue[selectedIndex - 1]?.item_id ?? item.item_id)} type="button">Previous</button>
            <button class="button ghost" disabled={selectedIndex >= state.review_queue.length - 1} onClick={() => setSelectedId(state.review_queue[selectedIndex + 1]?.item_id ?? item.item_id)} type="button">Next</button>
          </div>
          <button class="button secondary" onClick={() => setSavedDrafts((current) => ({ ...current, [item.item_id]: draftValue }))} type="button">Save draft</button>
        </div>
        {savedDrafts[item.item_id] ? <div class="draft-note">Proposed: {savedDrafts[item.item_id]}</div> : null}
        <div class="button-row action-row">
          <button class="button primary" disabled={workingItem === item.item_id || !runId || !item.available_actions.includes("accept")} onClick={() => void apply("accept")} type="button">Accept</button>
          <button class="button secondary" disabled={workingItem === item.item_id || !runId || !item.available_actions.includes("unresolved")} onClick={() => void apply("unresolved")} type="button">Mark unresolved</button>
        </div>
      </section>
    </div>
  );
}

function Summary({ summary, onReveal, onError }: { summary: RunSummaryView | null; onReveal: (runId: string) => Promise<boolean>; onError: (message: string | null) => void }) {
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
          <div><span class="eyebrow">Terminal run</span><h3>{summary.run_id}</h3></div>
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
        {summary.artifacts.length ? (
          <div class="file-list">
            {summary.artifacts.map((artifact) => (
              <div class="file-row" key={artifact.artifact_id}>
                <div class="file-icon">OUT</div>
                <div class="file-main"><strong>{artifact.display_name}</strong><span>{artifact.role} · {formatBytes(artifact.size_bytes)}</span></div>
                <div class="button-row">
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
        {summary.stage_timings.length ? <div class="data-list">{summary.stage_timings.map((stage) => <div class="data-row" key={stage.stage_name}><strong>{stage.stage_name}</strong><span>{stage.call_count} calls</span><span>{formatDuration(stage.duration_ns)}</span></div>)}</div> : <p class="quiet">No stage timing records.</p>}
      </section>

      <section class="panel">
        <div class="section-heading"><div><span class="eyebrow">Hardware</span><h3>Device summary</h3></div></div>
        {summary.device_summaries.length ? <div class="data-list">{summary.device_summaries.map((device) => <div class="data-row" key={device.device_type}><strong>{device.device_type}</strong><span>{device.execution_count} executions</span><span>{formatDuration(device.avg_duration_ns)}</span><span>{formatConfidence(device.avg_confidence)}</span></div>)}</div> : <p class="quiet">No hardware execution records.</p>}
      </section>

      {summary.warnings.length || summary.failures.length ? (
        <section class="panel span-2">
          <div class="section-heading"><div><span class="eyebrow">Run notes</span><h3>Warnings and failures</h3></div></div>
          {summary.warnings.map((warning) => <p class="note warning" key={`w-${warning}`}>{warning}</p>)}
          {summary.failures.map((failure) => <p class="note failure" key={`f-${failure}`}>{failure}</p>)}
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
    const target = `${region.region_id} ${region.file_display_name} ${region.page_number} ${region.region_type} ${region.method} ${region.fallback_engine ?? ""}`.toLowerCase();
    return !regionQuery || target.includes(regionQuery.toLowerCase());
  });

  return (
    <div class="screen-grid">
      <section class="panel span-2">
        <div class="section-heading">
          <div><span class="eyebrow">Technical inspector</span><h3>{inspector.run_id}</h3></div>
          <div class="button-row"><span class="badge badge--active">{inspector.status}</span><a class="button secondary" href={`/api/runs/${encodeURIComponent(inspector.run_id)}/diagnostics?download=1`}>Export diagnostics</a></div>
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
          <input class="search-input" placeholder="Search logs" value={logQuery} onInput={(event) => setLogQuery(event.currentTarget.value)} />
          <select value={logLevel} onChange={(event) => setLogLevel(event.currentTarget.value)}><option>ALL</option><option>INFO</option><option>WARN</option><option>ERROR</option><option>FAILED</option></select>
          <button class="button ghost small" onClick={() => void navigator.clipboard.writeText(inspector.activity_logs.map((entry) => `[${entry.timestamp}] [${entry.severity}] ${entry.component}: ${entry.message}`).join("\n"))} type="button">Copy logs</button>
        </div>
        <div class="log-list">{logs.length ? logs.map((entry, index) => <div class="log-entry" key={`${entry.timestamp}-${index}`}><span>{entry.timestamp}</span><strong>{entry.severity}</strong><span>{entry.component}: {entry.message}</span></div>) : <p class="quiet">No logs match the current filter.</p>}</div>
      </section>

      <section class="panel span-2">
        <div class="section-heading"><div><span class="eyebrow">Pages</span><h3>Confidence</h3></div></div>
        <div class="data-list">{inspector.page_confidence.length ? inspector.page_confidence.map((page) => <div class="data-row wide" key={`${page.file_display_name}-${page.page_number}`}><strong>{page.file_display_name}</strong><span>Page {page.page_number}</span><span>{formatConfidence(page.confidence_score)}</span><span>{page.region_count} regions</span><span>{page.review_recommended ? "Review" : "OK"}</span></div>) : <p class="quiet">No page confidence records.</p>}</div>
      </section>

      <section class="panel span-2">
        <div class="section-heading"><div><span class="eyebrow">Regions</span><h3>Confidence details</h3></div></div>
        <input class="search-input" placeholder="Filter regions" value={regionQuery} onInput={(event) => setRegionQuery(event.currentTarget.value)} />
        <div class="data-list spaced">{regions.length ? regions.map((region) => <div class="data-row wide" key={region.region_id}><strong>{region.region_id}</strong><span>{region.file_display_name} · P{region.page_number}</span><span>{region.region_type}</span><span>{formatConfidence(region.confidence_score)}</span><span>{region.fallback_engine || region.method}</span></div>) : <p class="quiet">No region confidence records match the filter.</p>}</div>
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
    <div class="drawer-backdrop" onClick={onClose}>
      <aside class="history-drawer" onClick={(event) => event.stopPropagation()}>
        <div class="section-heading"><div><span class="eyebrow">History</span><h3>Terminal runs</h3></div><button class="button ghost small" onClick={onClose} type="button">Close</button></div>
        {busy ? <div class="loading compact"><div class="spinner" /><span>Loading history…</span></div> : null}
        {error ? <div class="inline-error">{error}</div> : null}
        {!busy && !history.length ? <p class="quiet">No previous terminal runs found.</p> : null}
        <div class="history-list">
          {history.map((run) => (
            <article class="history-card" key={run.run_id}>
              <div class="button-row between"><strong>{run.run_id}</strong><span class="badge">{run.status}</span></div>
              <p>{run.requirement} · {run.profile}</p>
              <small>{run.duration_ms} ms · {run.artifact_count} artifacts · {run.warning_count} warnings</small>
              <div class="button-row"><button class="button primary small" onClick={() => onSummary(run.run_id)} type="button">View result</button><button class="button secondary small" onClick={() => onInspector(run.run_id)} type="button">Telemetry</button></div>
            </article>
          ))}
        </div>
        <div class="maintenance">
          <span class="eyebrow">Maintenance</span>
          <div class="button-row"><button class="button danger small" onClick={onClearHistory} type="button">Clear history</button><button class="button secondary small" onClick={onClearCache} type="button">Clear cache</button></div>
        </div>
      </aside>
    </div>
  );
}

export function App() {
  const [state, setState] = useState<ApplicationViewState | null>(null);
  const [screen, setScreen] = useState<Screen>("home");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<readonly TerminalRunHistoryView[]>([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [summaryOverride, setSummaryOverride] = useState<RunSummaryView | null>(null);
  const [inspectorOverride, setInspectorOverride] = useState<InspectorViewState | null>(null);
  const connectedRef = useRef(false);
  const summaryRequest = useRef(0);
  const inspectorRequest = useRef(0);

  const refresh = async () => {
    const next = await fetchState();
    setState(next);
    setError(null);
  };

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
    const requestId = ++summaryRequest.current;
    setError(null);
    try {
      const summary = await fetchRunSummary(runId);
      if (requestId !== summaryRequest.current) return;
      setSummaryOverride(summary);
      setInspectorOverride(null);
      setHistoryOpen(false);
      setScreen("summary");
    } catch (reason) {
      if (requestId === summaryRequest.current) setError(reason instanceof Error ? reason.message : "Unable to load run summary.");
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

  return (
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand"><div class="brand-mark">S</div><div><strong>Sarathi</strong><span>V3 · Local Intelligence</span></div></div>
        <nav aria-label="Main navigation">
          {screens.map((item) => (
            <button class={screen === item.id ? "nav-item active" : "nav-item"} onClick={() => chooseScreen(item.id)} type="button" key={item.id}>
              <span class="nav-glyph">{item.label.slice(0, 1)}</span>{item.label}
            </button>
          ))}
        </nav>
        <div class="sidebar-footer"><span class={connected ? "connection connection--live" : "connection"} /><span>{connected ? "Live state" : "Polling"}</span></div>
      </aside>

      <main class="workspace">
        <header class="topbar">
          <div><span class="eyebrow">Mukha</span><h1>{screens.find((item) => item.id === screen)?.label}</h1></div>
          <div class="topbar-meta"><button class="button ghost small" onClick={() => void openHistory()} type="button">History</button><span class="badge">{state?.requirement || "No requirement"}</span><span class="revision">rev {state?.state_revision ?? "—"}</span></div>
        </header>

        {error ? <div class="error-banner" role="alert">{error}</div> : null}
        {!state ? (
          <div class="loading"><div class="spinner" /><strong>Connecting to Sarathi…</strong></div>
        ) : (
          <div class="screen">
            {screen === "home" && <Home state={state} onError={setError} onStarted={(runId) => { setSummaryOverride(null); setInspectorOverride(null); setScreen("monitor"); void refresh().catch(() => undefined); if (!runId) setError("Run started without an identifier."); }} />}
            {screen === "monitor" && <Monitor state={state} onError={setError} />}
            {screen === "review" && <Review state={state} onError={setError} onRefresh={refresh} />}
            {screen === "summary" && <Summary summary={summary} onError={setError} onReveal={revealRun} />}
            {screen === "inspector" && <Inspector inspector={inspector} />}
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
    </div>
  );
}
