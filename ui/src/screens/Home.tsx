import { useEffect, useMemo, useRef, useState } from "preact/hooks";

import {
  browseFiles,
  browseFolder,
  intakePaths,
  previewPlan,
  startRun,
} from "../api";
import { actionDefaults } from "../components/Common";
import { IntakeDropzone } from "../components/IntakeDropzone";
import { IntakeTable } from "../components/IntakeTable";
import { TaskSelector } from "../components/TaskSelector";
import { formatBytes } from "../formatters";
import type {
  ApplicationViewState,
  InputFilter,
  InputItemView,
  InputSelectionView,
  PlanPreview,
  PreflightView,
  RunRequest,
} from "../types";
import {
  PRIMARY_TASKS,
  resolveBackendMapping,
  type PrimaryTaskId,
} from "../workflow/taskCatalog";

export function Home({
  state,
  onStarted,
  onError,
  onPreview,
}: {
  state: ApplicationViewState;
  onStarted: (runId: string) => void;
  onError: (message: string | null) => void;
  onPreview: (pathOrUrl: string, displayName: string) => void;
}) {
  const initialRoots = state.input_selection.items.flatMap((item) =>
    item.source_path ? [item.source_path] : []
  );

  const [roots, setRoots] = useState<string[]>(initialRoots);
  const [selection, setSelection] = useState<InputSelectionView>(state.input_selection);
  const [preflight, setPreflight] = useState<PreflightView | null>(state.preflight);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [checkedPaths, setCheckedPaths] = useState<Set<string>>(new Set());
  const excludedRef = useRef(excluded);
  excludedRef.current = excluded;
  const checkedPathsRef = useRef(checkedPaths);
  checkedPathsRef.current = checkedPaths;
  const [showAllInputsTable, setShowAllInputsTable] = useState(false);
  const [intakeExpanded, setIntakeExpanded] = useState(true);
  const [recursive, setRecursive] = useState(false);
  const [manualPath, setManualPath] = useState("");

  const [primaryTask, setPrimaryTask] = useState<PrimaryTaskId | null>(null);

  const [subtaskByPrimary, setSubtaskByPrimary] = useState<Record<PrimaryTaskId, string>>(() => ({
    documents_extraction:
      state.requirement === "ocr"
        ? "instant_ocr"
        : state.requirement.endsWith("_ocr")
        ? "cloud_ocr"
        : "native",
    bank_consolidation: (state as any).profile === "accurate" ? "accurate" : "instant",
    font_conversion: "legacy_to_unicode",
    translation: state.requirement.endsWith("_translation")
      ? state.requirement.replace("_translation", "")
      : "indictrans2",
  }));

  const [cloudOcrProvider, setCloudOcrProvider] = useState<string>(
    state.requirement.endsWith("_ocr") ? state.requirement : "gemini_ocr"
  );
  const [transDirection, setTransDirection] = useState<string>("");
  const [statutoryEnabled, setStatutoryEnabled] = useState<boolean>(true);
  const [convertLegacyFonts, setConvertLegacyFonts] = useState<boolean>(true);
  const [layoutAnalysis, setLayoutAnalysis] = useState<boolean>(false);
  const [preserveLayout, setPreserveLayout] = useState<boolean>(false);
  const [sourceFont, setSourceFont] = useState<string>("");
  const [skipHeaderFooter, setSkipHeaderFooter] = useState<boolean>(true);

  const ocrAction = state.available_actions.find((a) => a.action_id === "ocr");
  const [ocrCustomParams, setOcrCustomParams] = useState<Record<string, unknown>>(() => {
    const d = actionDefaults(ocrAction);
    d.profile = "custom";
    d.engine = "rapidocr";
    return d;
  });

  const [plan, setPlan] = useState<PlanPreview | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<InputFilter>("all");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (working) return;
    setSelection(state.input_selection);
    setPreflight(state.preflight);
    const newItems = state.input_selection.items;
    if (newItems.length === 0) {
      setRoots([]);
      setExcluded(new Set());
    } else if (!roots.length || roots.every((r) => !r)) {
      setRoots(newItems.flatMap((item) => (item.source_path ? [item.source_path] : [])));
    } else {
      const hasAnyMatch = roots.some((r) =>
        newItems.some((item) => item.source_path && (item.source_path === r || item.source_path.startsWith(r)))
      );
      if (!hasAnyMatch) {
        setRoots(newItems.flatMap((item) => (item.source_path ? [item.source_path] : [])));
        setExcluded(new Set());
      }
    }
  }, [state.input_selection, state.preflight, working]);

  const visibleItems = useMemo(
    () => selection.items.filter((item) => !item.source_path || !excluded.has(item.source_path)),
    [selection.items, excluded]
  );
  const eligiblePaths = visibleItems.flatMap((item) =>
    item.is_eligible && item.source_path ? [item.source_path] : []
  );
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

  const selectAllRef = useRef<HTMLInputElement>(null);
  const pagedCheckedCount = pagedItems.filter((i) => checkedPaths.has(i.source_path || i.display_name)).length;
  const isAllPagedChecked = pagedItems.length > 0 && pagedCheckedCount === pagedItems.length;
  const isIndeterminate = pagedCheckedCount > 0 && !isAllPagedChecked;

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = isIndeterminate;
    }
  }, [isIndeterminate]);

  useEffect(() => setPage(1), [query, filter]);

  const currentSubtask = primaryTask ? subtaskByPrimary[primaryTask] : undefined;

  const currentBackendMapping = useMemo(() => {
    return resolveBackendMapping(primaryTask, currentSubtask, {
      layoutAnalysis,
      preserveLayout,
      cloudOcrProvider,
      ocrProfile: String(ocrCustomParams.profile || "custom"),
    });
  }, [primaryTask, currentSubtask, layoutAnalysis, preserveLayout, cloudOcrProvider, ocrCustomParams.profile]);

  const activeAction = currentBackendMapping
    ? state.available_actions.find((action) => action.action_id === currentBackendMapping.requirement)
    : undefined;

  const buildRequest = (): RunRequest => {
    const req = currentBackendMapping?.requirement ?? "read_native";
    const prof = currentBackendMapping?.profile ?? "instant";
    const customOptions: Record<string, unknown> = {};

    if (primaryTask === "documents_extraction") {
      if (currentSubtask === "native") {
        const statEl = typeof document !== "undefined" ? (document.getElementById("param-statutory") as HTMLInputElement | null) : null;
        customOptions.statutory = statEl ? statEl.checked : statutoryEnabled;
        const legacyEl = typeof document !== "undefined" ? (document.getElementById("param-convert-legacy-fonts") as HTMLInputElement | null) : null;
        customOptions.convert_legacy_fonts = legacyEl ? legacyEl.checked : convertLegacyFonts;
        const layoutEl = typeof document !== "undefined" ? (document.getElementById("param-layout-analysis") as HTMLInputElement | null) : null;
        const isLayout = layoutEl ? layoutEl.checked : layoutAnalysis;
        if (isLayout) {
          customOptions.layout_analysis = true;
        }
        const skipHdrEl = typeof document !== "undefined" ? (document.getElementById("param-skip-header-footer") as HTMLInputElement | null) : null;
        customOptions.skip_header_footer = skipHdrEl ? skipHdrEl.checked : skipHeaderFooter;
      } else if (currentSubtask === "accurate_ocr") {
        const layEl = typeof document !== "undefined" ? (document.getElementById("param-preserve-layout") as HTMLInputElement | null) : null;
        if (layEl ? layEl.checked : preserveLayout) {
          customOptions.preserve_layout = true;
        }
        const ocrSkipHdrEl = typeof document !== "undefined" ? (document.getElementById("param-ocr-skip-header-footer") as HTMLInputElement | null) : null;
        customOptions.skip_header_footer = ocrSkipHdrEl ? ocrSkipHdrEl.checked : skipHeaderFooter;
      } else if (currentSubtask === "instant_ocr") {
        customOptions.skip_header_footer = skipHeaderFooter;
      } else if (currentSubtask === "custom_ocr") {
        customOptions.engine = "rapidocr";
        const ocrAct = state.available_actions.find((a) => a.action_id === "ocr");
        for (const parameter of ocrAct?.parameters ?? []) {
          if (parameter.parameter_id === "profile") continue;
          const el = typeof document !== "undefined" ? (document.getElementById(`param-${parameter.parameter_id}`) as HTMLInputElement | null) : null;
          const domVal = parameter.kind === "toggle" ? el?.checked : el?.value;
          const val = domVal !== undefined ? domVal : (ocrCustomParams[parameter.parameter_id] ?? parameter.default_value);
          if (parameter.kind === "toggle") customOptions[parameter.parameter_id] = Boolean(val);
          else if (val !== undefined && val !== null && val !== "") customOptions[parameter.parameter_id] = val;
        }
      }
    } else if (primaryTask === "font_conversion") {
      if (currentSubtask === "unicode_to_krutidev") {
        customOptions.font_mode = "to_krutidev";
        customOptions.target_script = "legacy";
        customOptions.target_profile_id = "to_krutidev";
      } else if (currentSubtask === "unicode_to_devlys") {
        customOptions.font_mode = "to_devlys";
        customOptions.target_script = "legacy";
        customOptions.target_profile_id = "to_devlys";
      } else {
        customOptions.font_mode = "auto_unicode";
        const fontEl = typeof document !== "undefined" ? (document.getElementById("param-source-font") as HTMLSelectElement | null) : null;
        const fontVal = fontEl ? fontEl.value : sourceFont;
        if (fontVal) customOptions.source_font = fontVal;
      }
    } else if (primaryTask === "translation") {
      if (transDirection) {
        customOptions.direction = transDirection;
      }
      if (currentSubtask === "opus_mt") {
        customOptions.engine = "opus_mt";
      } else if (currentSubtask === "indictrans2") {
        customOptions.engine = "indictrans2";
      }
    }

    return {
      paths: eligiblePaths,
      requirement: req,
      profile: prof,
      recursive,
      custom_options: customOptions,
    };
  };

  const buildRequestRef = useRef(buildRequest);
  buildRequestRef.current = buildRequest;

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
    if (typeof window !== "undefined") {
      (window as any).__sarathi_set_intake = (
        testItems: InputItemView[],
        testPreflight?: PreflightView
      ) => {
        setSelection({
          total_files: testItems.length,
          total_size_bytes: testItems.reduce((acc, i) => acc + (i.size_bytes || 0), 0),
          is_grouped: false,
          groups: [],
          items: testItems,
        });
        if (testPreflight) setPreflight(testPreflight);
        setCheckedPaths(new Set());
      };
      (window as any).__sarathi_build_request = () => buildRequestRef.current();
      (window as any).__sarathi_remove_path = (paths: string[]) => {
        const next = new Set(excludedRef.current);
        for (const p of paths) next.add(p);
        excludedRef.current = next;
        setExcluded(next);
      };
      (window as any).__sarathi_add_path = (paths: string[]) => {
        const next = new Set(excludedRef.current);
        for (const p of paths) next.delete(p);
        excludedRef.current = next;
        setExcluded(next);
      };
      (window as any).__sarathi_is_excluded = (p: string) => excludedRef.current.has(p);
      (window as any).__sarathi_get_checked_paths = () => Array.from(checkedPathsRef.current);
      (window as any).__sarathi_clear_checked = () => {
        checkedPathsRef.current = new Set();
        setCheckedPaths(new Set());
      };
      (window as any).__sarathi_add_checked = (p: string) => {
        const next = new Set(checkedPathsRef.current);
        next.add(p);
        checkedPathsRef.current = next;
        setCheckedPaths(next);
      };
      (window as any).__sarathi_set_input_page = (p: number) => setPage(p);
      (window as any).__sarathi_set_show_all = (show: boolean) => setShowAllInputsTable(show);
      (window as any).__sarathi_set_filter = (f: "all" | "eligible" | "issues") => setFilter(f);
      (window as any).__sarathi_set_primary_task = (t: PrimaryTaskId) => setPrimaryTask(t);
      (window as any).__sarathi_get_primary_task = () => primaryTask;
      (window as any).__sarathi_set_subtask = (t: PrimaryTaskId, s: string) => {
        setSubtaskByPrimary((prev) => ({ ...prev, [t]: s }));
      };
      (window as any).__sarathi_get_subtask = (t: PrimaryTaskId) => subtaskByPrimary[t];
      (window as any).__sarathi_set_cloud_ocr_provider = (p: string) => setCloudOcrProvider(p);
      (window as any).__sarathi_set_translation_direction = (d: string) => setTransDirection(d);
      (window as any).__sarathi_set_skip_header_footer = (v: boolean) => setSkipHeaderFooter(v);
      (window as any).__sarathi_set_ocr_param = (key: string, val: unknown) => {
        setOcrCustomParams((prev) => ({ ...prev, [key]: val }));
      };
    }
  });

  useEffect(() => {
    if (!primaryTask || !activeAction?.is_enabled || !eligiblePaths.length) {
      setPlan(null);
      setPlanError(null);
      return;
    }
    const timer = window.setTimeout(() => {
      void previewPlan(buildRequest())
        .then((next) => {
          setPlan(next);
          setPlanError(null);
        })
        .catch((reason) => {
          setPlan(null);
          setPlanError(reason instanceof Error ? reason.message : "Unable to preview plan.");
        });
    }, 200);
    return () => window.clearTimeout(timer);
  }, [
    primaryTask,
    currentSubtask,
    cloudOcrProvider,
    transDirection,
    statutoryEnabled,
    convertLegacyFonts,
    layoutAnalysis,
    preserveLayout,
    skipHeaderFooter,
    sourceFont,
    JSON.stringify(ocrCustomParams),
    recursive,
    eligiblePaths.join("\n"),
    activeAction?.is_enabled,
  ]);

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
    if (!primaryTask || !activeAction?.is_enabled || !eligiblePaths.length || planError) return;
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

  const showGroupedSummary = visibleItems.length > 10 && !showAllInputsTable;

  return (
    <div class="screen-grid home-cockpit">
      {/* Column 1: Document Intake */}
      <section class="panel intake-panel">
        <div class="panel-header">
          <div class="panel-title-wrap">
            <span class="panel-icon panel-icon--amber">
              <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
              </svg>
            </span>
            <h2 class="panel-heading">Document Intake</h2>
          </div>
          <div class="panel-header-meta">
            <span class="count-badge">
              {visibleItems.length} selected ({formatBytes(totalSize)})
            </span>
            <button
              class="icon-toggle-btn"
              onClick={() => setIntakeExpanded(!intakeExpanded)}
              type="button"
              aria-label="Toggle Intake Section"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d={intakeExpanded ? "M5 15l7-7 7 7" : "M19 9l-7 7-7-7"}
                />
              </svg>
            </button>
          </div>
        </div>

        {intakeExpanded ? (
          <div class="panel-body intake-panel-body">
            <IntakeDropzone
              working={working}
              hasItems={visibleItems.length > 0}
              recursive={recursive}
              manualPath={manualPath}
              onBrowseFiles={() => void handleBrowse(false)}
              onBrowseFolder={() => void handleBrowse(true)}
              onClear={() => {
                setExcluded(new Set());
                void refreshIntake([]);
              }}
              onToggleRecursive={(checked) => {
                setRecursive(checked);
                if (roots.length) void refreshIntake(roots, checked);
              }}
              onManualPathChange={(val) => setManualPath(val)}
              onAddManualPath={() => {
                if (manualPath.trim()) {
                  void addRoots([manualPath.trim()]);
                  setManualPath("");
                }
              }}
            />

            <IntakeTable
              visibleItems={visibleItems}
              filteredItems={filteredItems}
              pagedItems={pagedItems}
              checkedPaths={checkedPaths}
              totalSize={totalSize}
              eligibleCount={eligibleCount}
              issueCount={issueCount}
              query={query}
              filter={filter}
              page={page}
              pageCount={pageCount}
              showAllInputsTable={showAllInputsTable}
              showGroupedSummary={showGroupedSummary}
              selectAllRef={selectAllRef}
              isAllPagedChecked={isAllPagedChecked}
              onQueryChange={(q) => setQuery(q)}
              onFilterChange={(f) => setFilter(f)}
              onSetShowAll={(show) => setShowAllInputsTable(show)}
              onSetPage={(p) => setPage(p)}
              onToggleSelectAllPaged={(checked) => {
                setCheckedPaths((prev) => {
                  const next = new Set(prev);
                  for (const item of pagedItems) {
                    const key = item.source_path || item.display_name;
                    if (checked) next.add(key);
                    else next.delete(key);
                  }
                  return next;
                });
              }}
              onToggleItemChecked={(itemKey, checked) => {
                const next = new Set(checkedPathsRef.current);
                if (checked) next.add(itemKey);
                else next.delete(itemKey);
                checkedPathsRef.current = next;
                setCheckedPaths(next);
                if (selectAllRef.current) {
                  const pCount = pagedItems.filter((i) =>
                    next.has(i.source_path || i.display_name)
                  ).length;
                  selectAllRef.current.indeterminate = pCount > 0 && pCount < pagedItems.length;
                }
              }}
              onSelectAllMatching={() =>
                setCheckedPaths(new Set(filteredItems.map((i) => i.source_path || i.display_name)))
              }
              onClearChecked={() => setCheckedPaths(new Set())}
              onPreview={onPreview}
              onRemoveItem={(item) => void removeItem(item)}
            />
          </div>
        ) : null}
      </section>

      {/* Column 2: Processing Capability & Execution Plan */}
      <div class="column-action">
        {/* Processing Action Panel */}
        <section class="panel capability-panel">
          <div class="panel-header">
            <div class="panel-title-wrap">
              <div>
                <span class="capability-eyebrow">Task Selection</span>
                <div class="capability-title-row">
                  <span class="panel-icon panel-icon--amber">⚡</span>
                  <h2 class="panel-heading">Processing Action</h2>
                </div>
              </div>
            </div>
            {primaryTask ? (
              <div class="active-task-badge-pill">
                <span>Active:</span>
                <strong>{PRIMARY_TASKS.find((t) => t.id === primaryTask)?.label}</strong>
                <button
                  id="btn-deselect-task"
                  class="btn-deselect-task"
                  type="button"
                  title="Deselect task and view all primary tasks"
                  onClick={() => setPrimaryTask(null)}
                >
                  ✕
                </button>
              </div>
            ) : (
              <span class="step-guide-badge">Step 1: Choose Primary Task</span>
            )}
          </div>

          <TaskSelector
            primaryTask={primaryTask}
            currentSubtask={currentSubtask}
            subtaskByPrimary={subtaskByPrimary}
            availableActions={state.available_actions}
            cloudOcrProvider={cloudOcrProvider}
            transDirection={transDirection}
            statutoryEnabled={statutoryEnabled}
            convertLegacyFonts={convertLegacyFonts}
            layoutAnalysis={layoutAnalysis}
            preserveLayout={preserveLayout}
            sourceFont={sourceFont}
            skipHeaderFooter={skipHeaderFooter}
            ocrCustomParams={ocrCustomParams}
            onSelectPrimaryTask={(task) => setPrimaryTask(task)}
            onSelectSubtask={(primary, subtask) =>
              setSubtaskByPrimary((prev) => ({ ...prev, [primary]: subtask }))
            }
            onSetCloudOcrProvider={(provider) => setCloudOcrProvider(provider)}
            onSetTransDirection={(dir) => setTransDirection(dir)}
            onSetStatutoryEnabled={(enabled) => setStatutoryEnabled(enabled)}
            onSetConvertLegacyFonts={(enabled) => setConvertLegacyFonts(enabled)}
            onSetLayoutAnalysis={(enabled) => setLayoutAnalysis(enabled)}
            onSetPreserveLayout={(enabled) => setPreserveLayout(enabled)}
            onSetSourceFont={(font) => setSourceFont(font)}
            onSetSkipHeaderFooter={(enabled) => setSkipHeaderFooter(enabled)}
            onSetOcrCustomParam={(key, val) =>
              setOcrCustomParams((prev) => ({ ...prev, [key]: val }))
            }
          />

          {/* If no Level 1 task is selected, show instructional prompt */}
          {!primaryTask && (
            <div id="level1-empty-prompt" class="level1-empty-prompt">
              <span class="level1-prompt-icon">👆</span>
              <div class="level1-prompt-text">
                <strong>Select a Primary Task Above</strong>
                <p>
                  Choose one of the four primary tasks above to view its specific methods, engines,
                  and configuration options.
                </p>
              </div>
            </div>
          )}
        </section>

        {/* Preflight Execution Plan Card */}
        <section class="panel execution-plan-card">
          <div class="execution-plan-header">
            <div>
              <span class="preflight-eyebrow">Preflight</span>
              <h3 class="execution-plan-title">Execution Plan</h3>
            </div>
            <span class="preflight-status-text">
              {!primaryTask
                ? "Select a task above"
                : preflight
                ? `${eligibleCount} eligible · ${issueCount} issues`
                : "Select inputs to validate"}
            </span>
          </div>

          {!primaryTask ? (
            <div class="empty-state" style={{ padding: "20px 14px" }}>
              <strong>No Task Selected</strong>
              <p class="quiet" style={{ margin: "4px 0 0 0", fontSize: "12px" }}>
                Select a primary task above to view options and preview execution.
              </p>
            </div>
          ) : plan ? (
            <div class="plan-details-box">
              <div class="plan-header-row">
                <strong>
                  {plan.document_count} document{plan.document_count === 1 ? "" : "s"}
                </strong>
                <span class="badge badge-emerald">Plan ready</span>
              </div>
              <div class="plan-stages-row">
                {plan.stages.map((stage, idx) => (
                  <span key={stage.name} class="stage-chip">
                    {stage.name}
                    {idx < plan.stages.length - 1 ? <span class="stage-arrow">→</span> : null}
                  </span>
                ))}
              </div>
              {plan.devices.length ? (
                <small class="plan-devices">
                  {plan.devices
                    .map(
                      (device) =>
                        `${device.device_type}${device.is_available ? "" : " unavailable"}`
                    )
                    .join(" · ")}
                </small>
              ) : null}
            </div>
          ) : null}

          {planError ? <div class="inline-error">{planError}</div> : null}

          <button
            id="btn-start-run"
            class="button primary btn-primary btn-start-run"
            disabled={
              working ||
              !primaryTask ||
              !eligiblePaths.length ||
              !activeAction?.is_enabled ||
              Boolean(planError)
            }
            onClick={() => void handleStart()}
            type="button"
          >
            <span>
              {working
                ? "Working…"
                : !primaryTask
                ? "Select a Task to Start"
                : "Start document processing"}
            </span>
            <span class="btn-bolt">⚡</span>
          </button>
        </section>
      </div>
    </div>
  );
}
