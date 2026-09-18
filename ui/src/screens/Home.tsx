import { useEffect, useMemo, useRef, useState } from "preact/hooks";

import {
  browseFiles,
  browseFolder,
  fetchInspector,
  fetchRunSummary,
  fetchState,
  intakePaths,
  previewPlan,
  startRun,
} from "../api";
import {
  ActionParameter,
  EmptyState,
  Metric,
  actionDefaults,
} from "../components/Common";
import { formatBytes } from "../formatters";
import type {
  ActionParameterView,
  ApplicationViewState,
  AvailableActionView,
  InputFilter,
  InputItemView,
  InputSelectionView,
  PlanPreview,
  PreflightView,
  RunRequest,
} from "../types";
import {
  PRIMARY_TASKS,
  isCloudAction,
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
  const initialRoots = state.input_selection.items.flatMap((item) => item.source_path ? [item.source_path] : []);

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
    documents_extraction: state.requirement === "ocr" ? "instant_ocr" : state.requirement.endsWith("_ocr") ? "cloud_ocr" : "native",
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

  const currentBackendMapping = useMemo<{
    requirement: string;
    profile: string;
  } | null>(() => {
    if (!primaryTask || !currentSubtask) return null;
    if (primaryTask === "documents_extraction") {
      if (currentSubtask === "native") return { requirement: "read_native", profile: layoutAnalysis ? "layout_preserving" : "instant" };
      if (currentSubtask === "instant_ocr") return { requirement: "ocr", profile: "instant" };
      if (currentSubtask === "accurate_ocr") return { requirement: "ocr", profile: preserveLayout ? "layout_preserving" : "accurate" };
      if (currentSubtask === "cloud_ocr") return { requirement: cloudOcrProvider, profile: "instant" };
      if (currentSubtask === "custom_ocr") {
        const p = String(ocrCustomParams.profile || "custom");
        return { requirement: "ocr", profile: p };
      }
      return { requirement: "read_native", profile: "instant" };
    }
    if (primaryTask === "bank_consolidation") {
      return { requirement: "bank_statements", profile: currentSubtask === "accurate" ? "accurate" : "instant" };
    }
    if (primaryTask === "font_conversion") {
      return { requirement: "font_conversion", profile: "instant" };
    }
    if (primaryTask === "translation") {
      if (currentSubtask === "opus_mt") return { requirement: "translation", profile: "instant" };
      if (currentSubtask === "gemini") return { requirement: "gemini_translation", profile: "instant" };
      if (currentSubtask === "mistral") return { requirement: "mistral_translation", profile: "instant" };
      if (currentSubtask === "azure") return { requirement: "azure_translation", profile: "instant" };
      return { requirement: "translation", profile: "instant" };
    }
    return { requirement: "read_native", profile: "instant" };
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
        testPreflight?: PreflightView,
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
        .then((next) => { setPlan(next); setPlanError(null); })
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
            <span class="count-badge">{visibleItems.length} selected ({formatBytes(totalSize)})</span>
            <button class="icon-toggle-btn" onClick={() => setIntakeExpanded(!intakeExpanded)} type="button" aria-label="Toggle Intake Section">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={intakeExpanded ? "M5 15l7-7 7 7" : "M19 9l-7 7-7-7"} />
              </svg>
            </button>
          </div>
        </div>

        {intakeExpanded ? (
          <div class="panel-body intake-panel-body">
            {/* Quick Action Bar */}
            <div class="intake-actions-toolbar">
              <div class="intake-btn-group">
                <button id="btn-browse-files" class="btn-action" disabled={working} onClick={() => void handleBrowse(false)} type="button">
                  + Add files
                </button>
                <button id="btn-browse-folder" class="btn-action" disabled={working} onClick={() => void handleBrowse(true)} type="button">
                  + Add folder
                </button>
                <button class="btn-clear" disabled={working || visibleItems.length === 0} onClick={() => { setExcluded(new Set()); void refreshIntake([]); }} type="button">
                  Clear
                </button>
              </div>
              <label class="recursive-label">
                <input
                  type="checkbox"
                  checked={recursive}
                  onChange={(event) => {
                    const checked = event.currentTarget.checked;
                    setRecursive(checked);
                    if (roots.length) void refreshIntake(roots, checked);
                  }}
                />
                <span>Recursive folders</span>
              </label>
            </div>

            {/* Path Input Bar */}
            <div class="path-input-bar">
              <input
                class="path-input"
                placeholder="Paste a file or folder path and press Enter"
                value={manualPath}
                onInput={(event) => setManualPath(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && manualPath.trim()) {
                    void addRoots([manualPath.trim()]);
                    setManualPath("");
                  }
                }}
              />
              <button
                class="btn-add-path"
                disabled={working || !manualPath.trim()}
                onClick={() => { void addRoots([manualPath.trim()]); setManualPath(""); }}
                type="button"
              >
                Add
              </button>
            </div>

            {/* Search & Filter Badges */}
            <div class="intake-search-filter-row">
              <div class="search-input-wrap">
                <svg class="search-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input
                  id="input-files-filter"
                  class="filter-search-input"
                  placeholder="Search selected documents..."
                  value={query}
                  onInput={(event) => setQuery(event.currentTarget.value)}
                />
              </div>
              <div class="filter-segmented-group">
                <button
                  id="btn-filter-all"
                  class={filter === "all" ? "filter-seg-btn active" : "filter-seg-btn"}
                  onClick={() => setFilter("all")}
                  type="button"
                >
                  All <span id="filter-all-count">{visibleItems.length}</span>
                </button>
                <button
                  id="btn-filter-eligible"
                  class={filter === "eligible" ? "filter-seg-btn active" : "filter-seg-btn"}
                  onClick={() => setFilter("eligible")}
                  type="button"
                >
                  Eligible <span id="filter-eligible-count">{eligibleCount}</span>
                </button>
                <button
                  id="btn-filter-issues"
                  class={filter === "issues" ? "filter-seg-btn active" : "filter-seg-btn"}
                  onClick={() => setFilter("issues")}
                  type="button"
                >
                  Issues <span id="filter-issues-count">{issueCount}</span>
                </button>
              </div>
            </div>

            {/* Intake Queue Summary */}
            <div id="input-grouped-summary" class={`grouped-summary-card ${showGroupedSummary ? "" : "hidden"}`}>
              <span class="grouped-summary-text">
                <strong>{visibleItems.length} documents selected</strong>
                <span class="quiet"> · {formatBytes(totalSize)}</span>
              </span>
              <button id="btn-view-all-inputs" class="btn-view-all" onClick={() => setShowAllInputsTable(true)} type="button">
                View All ({visibleItems.length} files)
              </button>
            </div>

            {/* Intake Table */}
            <div class={`table-container input-table-container ${showGroupedSummary ? "hidden" : ""}`}>
              {visibleItems.length > 10 && showAllInputsTable ? (
                <div class="collapse-summary-wrap">
                  <button id="btn-collapse-inputs" class="btn-collapse-summary" onClick={() => setShowAllInputsTable(false)} type="button">
                    Collapse to summary
                  </button>
                </div>
              ) : null}

              {checkedPaths.size > 0 ? (
                <div id="selection-scope-banner" class="selection-scope-banner">
                  <span id="selection-scope-text">
                    {checkedPaths.size === filteredItems.length && filteredItems.length > pagedItems.length
                      ? `All ${filteredItems.length} matching documents selected`
                      : `All ${pagedItems.filter((i) => checkedPaths.has(i.source_path || i.display_name)).length} documents on this page selected`}
                  </span>
                  <div class="button-row">
                    {checkedPaths.size < filteredItems.length ? (
                      <button id="btn-select-all-matching" class="button ghost small" onClick={() => setCheckedPaths(new Set(filteredItems.map((i) => i.source_path || i.display_name)))} type="button">
                        Select all {filteredItems.length} matching
                      </button>
                    ) : null}
                    <button id="btn-clear-selection-scope" class="button ghost small" onClick={() => setCheckedPaths(new Set())} type="button">
                      Clear
                    </button>
                  </div>
                </div>
              ) : null}

              <table class="data-table compact-table">
                <thead>
                  <tr>
                    <th style="width: 36px; text-align: center;">
                      <input
                        id="chk-select-all-inputs"
                        ref={selectAllRef}
                        type="checkbox"
                        checked={isAllPagedChecked}
                        onChange={(e) => {
                          const checked = e.currentTarget.checked;
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
                      />
                    </th>
                    <th>Document</th>
                    <th>Status</th>
                    <th style="text-align: right;">Actions</th>
                  </tr>
                </thead>
                <tbody id="selected-inputs-tbody">
                  {visibleItems.length === 0 ? (
                    <tr class="empty-row"><td colSpan={4} class="empty-cell">No documents selected. Click Add files or paste a path above.</td></tr>
                  ) : filteredItems.length === 0 ? (
                    <tr class="empty-row"><td colSpan={4} class="empty-cell">No documents match the filter query</td></tr>
                  ) : (
                    pagedItems.map((item) => {
                      const itemKey = item.source_path || item.display_name;
                      const isChecked = checkedPaths.has(itemKey);
                      return (
                        <tr key={item.input_id} data-path={itemKey}>
                          <td style="text-align: center;">
                            <input
                              type="checkbox"
                              class="input-row-chk"
                              checked={isChecked}
                              onChange={(e) => {
                                const checked = e.currentTarget.checked;
                                const next = new Set(checkedPathsRef.current);
                                if (checked) next.add(itemKey);
                                else next.delete(itemKey);
                                checkedPathsRef.current = next;
                                setCheckedPaths(next);
                                if (selectAllRef.current) {
                                  const pCount = pagedItems.filter((i) => next.has(i.source_path || i.display_name)).length;
                                  selectAllRef.current.indeterminate = pCount > 0 && pCount < pagedItems.length;
                                }
                              }}
                            />
                          </td>
                          <td>
                            <div class="doc-item-cell">
                              <strong class="doc-name">{item.display_name}</strong>
                              <span class="doc-size">{item.source_path ? `${item.source_path} · ` : ""}{formatBytes(item.size_bytes)}</span>
                            </div>
                          </td>
                          <td>
                            {item.is_eligible ? (
                              <span class="badge badge-emerald">Eligible</span>
                            ) : (
                              <button
                                class="btn-issue-info badge badge-crimson"
                                tabIndex={0}
                                aria-label={`Issue: ${item.issue_reason || "Ineligible document"}`}
                                type="button"
                              >
                                {item.issue_reason || "Issue"}
                              </button>
                            )}
                          </td>
                          <td style="text-align: right;">
                            <div class="button-row compact" style="justify-content: flex-end;">
                              <button class="button ghost mini" onClick={() => onPreview(`/api/inputs/${encodeURIComponent(item.input_id)}/preview`, item.display_name)} type="button">Preview</button>
                              <a class="button ghost mini" href={`/api/inputs/${encodeURIComponent(item.input_id)}/raw`} target="_blank">Open</a>
                              <button class="button ghost mini text-danger" onClick={() => void removeItem(item)} type="button">Remove</button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>

              {filteredItems.length > pageSize ? (
                <div class="pagination" style="margin-top: 10px; display: flex; align-items: center; justify-content: space-between; padding: 4px 8px;">
                  <button id="btn-input-prev" class="button ghost small" disabled={currentPage <= 1} onClick={() => setPage((v) => Math.max(1, v - 1))} type="button">Previous</button>
                  <span id="input-page-indicator" style="font-size: 11px;">Page {currentPage} of {pageCount} ({filteredItems.length} total)</span>
                  <button id="btn-input-next" class="button ghost small" disabled={currentPage >= pageCount} onClick={() => setPage((v) => Math.min(pageCount, v + 1))} type="button">Next</button>
                </div>
              ) : null}
            </div>
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

          {/* Level 1: Primary Task Hierarchy Accordion (Collapsible Level 1 & Level 2) */}
          <div class="tasks-accordion" role="tablist" aria-label="Primary Tasks">
            {PRIMARY_TASKS.map((task) => {
              const isSelected = primaryTask === task.id;
              return (
                <div
                  key={task.id}
                  class={`accordion-item ${isSelected ? "expanded" : "collapsed"}`}
                  data-task={task.id}
                >
                  <button
                    id={`btn-task-${task.id.replace(/_/g, "-")}`}
                    data-task={task.id}
                    class={`primary-task-tab-btn accordion-header-btn ${isSelected ? "active" : ""}`}
                    role="tab"
                    aria-selected={isSelected}
                    aria-expanded={isSelected}
                    type="button"
                    onClick={() => setPrimaryTask(isSelected ? null : task.id)}
                  >
                    <div class="accordion-header-left">
                      <span class="primary-task-icon">{task.icon}</span>
                      <div class="primary-task-info">
                        <span class="primary-task-label">{task.label}</span>
                        <span class="primary-task-desc">{task.description}</span>
                      </div>
                    </div>
                    <div class="accordion-header-right">
                      {isSelected ? (
                        <span class="accordion-badge accordion-badge--active">Active</span>
                      ) : (
                        <span class="accordion-badge accordion-badge--hint">Click to expand</span>
                      )}
                      <span class={`accordion-chevron ${isSelected ? "open" : ""}`} aria-hidden="true">
                        ▾
                      </span>
                    </div>
                  </button>

                  {/* Level 2: Second-Level Progressive Choices Collapsing under this Level 1 Task */}
                  {isSelected && (
                    <div class="accordion-body">
                      {task.id === "documents_extraction" && (
                        <div class="subtasks-container">
                          <div class="subtasks-grid">
                            {/* 1.1 Native Extraction */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "read_native");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "native";
                              return (
                                <div
                                  key="native"
                                  id="subtask-native"
                                  data-subtask="native"
                                  data-req="read_native"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "native" }))}
                                  title={isEnabled ? "Direct digital extraction from PDF, DOCX, XLSX, XLS, CSV." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Native Extraction</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>DIGITAL</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Direct digital extraction from PDF, DOCX, XLSX, XLS, CSV. Automatically invokes statutory/legal extraction.
                                  </p>
                                  <div class="subtask-options-row" onClick={(e) => e.stopPropagation()}>
                                    <label class="toggle-row mini">
                                      <input
                                        id="param-convert-legacy-fonts"
                                        type="checkbox"
                                        checked={convertLegacyFonts}
                                        onChange={(e) => {
                                          setConvertLegacyFonts(e.currentTarget.checked);
                                          setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "native" }));
                                        }}
                                      />
                                      <span>
                                        <strong>Convert Legacy Fonts to Unicode</strong>
                                      </span>
                                    </label>
                                    <label class="toggle-row mini" title="Use Graph Neural Networks for multi-column flow, table grids, and semantic headers">
                                      <input
                                        id="param-layout-analysis"
                                        type="checkbox"
                                        checked={layoutAnalysis}
                                        onChange={(e) => {
                                          setLayoutAnalysis(e.currentTarget.checked);
                                          setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "native" }));
                                        }}
                                      />
                                      <span>
                                        <strong>Deep Layout Analysis (GNN)</strong>
                                      </span>
                                    </label>
                                    <label class="toggle-row mini">
                                      <input
                                        id="param-statutory"
                                        type="checkbox"
                                        checked={statutoryEnabled}
                                        onChange={(e) => {
                                          setStatutoryEnabled(e.currentTarget.checked);
                                          setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "native" }));
                                        }}
                                      />
                                      <span>
                                        <strong>Statutory Extraction</strong>
                                      </span>
                                    </label>
                                    <label class="toggle-row mini" title="Detect and separate running page headers and footers from continuous narrative text">
                                      <input
                                        id="param-skip-header-footer"
                                        type="checkbox"
                                        checked={skipHeaderFooter}
                                        onChange={(e) => {
                                          setSkipHeaderFooter(e.currentTarget.checked);
                                          setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "native" }));
                                        }}
                                      />
                                      <span>
                                        <strong>Clean Output: Separate Running Headers/Footers</strong>
                                      </span>
                                    </label>
                                  </div>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">read_native</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 1.2 Instant OCR */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "ocr");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "instant_ocr";
                              return (
                                <div
                                  key="instant_ocr"
                                  id="subtask-instant-ocr"
                                  data-subtask="instant_ocr"
                                  data-req="ocr"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "instant_ocr" }))}
                                  title={isEnabled ? "RapidOCR inference with OpenVINO acceleration." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Instant OCR</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>RAPIDOCR</span>
                                  </div>
                                  <p class="action-card-desc">
                                    RapidOCR inference with OpenVINO acceleration. Single pass, bypasses heavy preprocessing.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">ocr:instant</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 1.3 Accurate OCR */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "ocr");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "accurate_ocr";
                              return (
                                <div
                                  key="accurate_ocr"
                                  id="subtask-accurate-ocr"
                                  data-subtask="accurate_ocr"
                                  data-req="ocr"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "accurate_ocr" }))}
                                  title={isEnabled ? "Quality-optimized OCR with full preprocessing." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Accurate OCR</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>ACCURATE</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Quality-optimized OCR with CLAHE, deskew, binarization, and selective NE-OCR fallback.
                                  </p>
                                  <div class="subtask-options-row" onClick={(e) => e.stopPropagation()}>
                                    <label class="toggle-row mini">
                                      <input
                                        id="param-preserve-layout"
                                        type="checkbox"
                                        checked={preserveLayout}
                                        onChange={(e) => {
                                          setPreserveLayout(e.currentTarget.checked);
                                          setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "accurate_ocr" }));
                                        }}
                                      />
                                      <span>
                                        <strong>Preserve Layout</strong>
                                      </span>
                                    </label>
                                    <label class="toggle-row mini" title="Detect and separate running page headers and footers from continuous narrative text">
                                      <input
                                        id="param-ocr-skip-header-footer"
                                        type="checkbox"
                                        checked={skipHeaderFooter}
                                        onChange={(e) => {
                                          setSkipHeaderFooter(e.currentTarget.checked);
                                          setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "accurate_ocr" }));
                                        }}
                                      />
                                      <span>
                                        <strong>Clean Output: Separate Running Headers/Footers</strong>
                                      </span>
                                    </label>
                                  </div>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">ocr:accurate</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 1.4 Cloud OCR */}
                            {(() => {
                              const cloudActs = [
                                { id: "gemini_ocr", label: "Gemini" },
                                { id: "mistral_ocr", label: "Mistral" },
                                { id: "azure_ocr", label: "Azure" },
                              ];
                              const curCloudAct = state.available_actions.find((a) => a.action_id === cloudOcrProvider);
                              const isEnabled = curCloudAct ? curCloudAct.is_enabled : false;
                              const isSel = currentSubtask === "cloud_ocr";
                              return (
                                <div
                                  key="cloud_ocr"
                                  id="subtask-cloud-ocr"
                                  data-subtask="cloud_ocr"
                                  data-req="cloud_ocr"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "cloud_ocr" }))}
                                  title={isEnabled ? "External cloud multimodal document recognition." : (curCloudAct?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Cloud Document AI</h4>
                                    <span class={`action-tag action-tag--cloud ${isSel ? "active" : ""}`}>CLOUD</span>
                                  </div>
                                  <p class="action-card-desc">
                                    External cloud multimodal document recognition with fail-closed Kavacha authorization.
                                  </p>
                                  <div class="cloud-provider-chips" onClick={(e) => e.stopPropagation()}>
                                    {cloudActs.map((cp) => {
                                      const act = state.available_actions.find((a) => a.action_id === cp.id);
                                      const isChipAvail = act ? act.is_enabled : false;
                                      const isChipActive = cloudOcrProvider === cp.id;
                                      return (
                                        <button
                                          key={cp.id}
                                          id={`chip-${cp.id.replace(/_/g, "-")}`}
                                          class={`cloud-chip ${isChipActive ? "active" : ""} ${!isChipAvail ? "disabled" : ""}`}
                                          disabled={!isChipAvail}
                                          title={isChipAvail ? cp.label : (act?.disabled_reason || "Unavailable")}
                                          type="button"
                                          onClick={() => {
                                            setCloudOcrProvider(cp.id);
                                            setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "cloud_ocr" }));
                                          }}
                                        >
                                          {cp.label}
                                        </button>
                                      );
                                    })}
                                  </div>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">{cloudOcrProvider}</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 1.5 Custom OCR */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "ocr");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "custom_ocr";
                              return (
                                <div
                                  key="custom_ocr"
                                  id="subtask-custom-ocr"
                                  data-subtask="custom_ocr"
                                  data-req="ocr"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, documents_extraction: "custom_ocr" }))}
                                  title={isEnabled ? "Fine-grained control over OCR parameters." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Custom OCR</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>CUSTOM</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Fine-grained parameter control over OCR engine, language, and preprocessing toggles.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">ocr:custom</code>
                                  </div>
                                </div>
                              );
                            })()}
                          </div>

                          {/* Custom OCR Parameter Panel */}
                          {currentSubtask === "custom_ocr" && ocrAction?.parameters.length ? (
                            <div class="parameter-section">
                              <div class="parameter-header">
                                <span class="eyebrow">Parameters</span>
                                <h4>Custom OCR Options</h4>
                              </div>
                              <div class="parameter-list">
                                {ocrAction.parameters.map((parameter) => (
                                  <ActionParameter
                                    key={parameter.parameter_id}
                                    parameter={parameter}
                                    value={ocrCustomParams[parameter.parameter_id] ?? parameter.default_value}
                                    onChange={(value) => {
                                      setOcrCustomParams((prev) => ({ ...prev, [parameter.parameter_id]: value }));
                                    }}
                                  />
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      )}

                      {task.id === "bank_consolidation" && (
                        <div class="subtasks-container">
                          <div class="subtasks-grid">
                            {/* 2.1 Instant Consolidation */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "bank_statements");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "instant";
                              return (
                                <div
                                  key="instant"
                                  id="subtask-instant-consolidation"
                                  data-subtask="instant"
                                  data-req="bank_statements"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, bank_consolidation: "instant" }))}
                                  title={isEnabled ? "Throughput-optimized financial statement parsing." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Instant Consolidation</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>FAST</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Throughput-optimized parsing and standard reconciliation heuristics across financial statements.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">bank_statements:instant</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 2.2 Accurate Consolidation */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "bank_statements");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "accurate";
                              return (
                                <div
                                  key="accurate"
                                  id="subtask-accurate-consolidation"
                                  data-subtask="accurate"
                                  data-req="bank_statements"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, bank_consolidation: "accurate" }))}
                                  title={isEnabled ? "Strict running balance verification and deduplication." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Accurate Consolidation</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>ACCURATE</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Strict running balance verification, debit/credit inversion detection, and multi-page pagination deduplication.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">bank_statements:accurate</code>
                                  </div>
                                </div>
                              );
                            })()}
                          </div>
                        </div>
                      )}

                      {task.id === "font_conversion" && (
                        <div class="subtasks-container">
                          <div class="subtasks-grid">
                            {/* 3.1 Legacy to Unicode */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "font_conversion");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "legacy_to_unicode";
                              return (
                                <div
                                  key="legacy_to_unicode"
                                  id="subtask-legacy-to-unicode"
                                  data-subtask="legacy_to_unicode"
                                  data-req="font_conversion"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, font_conversion: "legacy_to_unicode" }))}
                                  title={isEnabled ? "Auto-detects legacy Hindi font encodings and converts to Unicode." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Legacy to Unicode</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>UNICODE</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Auto-detects non-Unicode Indian font encodings (KrutiDev, DevLys, Chanakya, Shusha, Shivaji) and converts to standardized Unicode Devanagari.
                                  </p>
                                  <div class="subtask-options-row" onClick={(e) => e.stopPropagation()}>
                                    <label class="field mini" style={{ margin: 0 }}>
                                      <span style={{ fontSize: "11px" }}>Source Font Hint</span>
                                      <select
                                        id="param-source-font"
                                        value={sourceFont}
                                        onChange={(e) => setSourceFont(e.currentTarget.value)}
                                        style={{ padding: "3px 6px", fontSize: "11px" }}
                                      >
                                        <option value="">Auto-Detect Source Font</option>
                                        <option value="krutidev010">KrutiDev 010 / DevLys</option>
                                        <option value="chanakya010">Chanakya</option>
                                        <option value="shusha010">Shusha</option>
                                        <option value="shivaji010">Shivaji</option>
                                      </select>
                                    </label>
                                  </div>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">font_conversion:auto_unicode</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 3.2 Unicode to KrutiDev */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "font_conversion");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "unicode_to_krutidev";
                              return (
                                <div
                                  key="unicode_to_krutidev"
                                  id="subtask-unicode-to-krutidev"
                                  data-subtask="unicode_to_krutidev"
                                  data-req="font_conversion"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, font_conversion: "unicode_to_krutidev" }))}
                                  title={isEnabled ? "Reverses Unicode Devanagari text into legacy KrutiDev 010." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Unicode to KrutiDev</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>KRUTIDEV</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Reverses Unicode Devanagari text into legacy KrutiDev 010 typewriter encoding using precompiled reverse transducers.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">font_conversion:to_krutidev</code>
                                  </div>
                                </div>
                              );
                            })()}

                            {/* 3.3 Unicode to DevLys */}
                            {(() => {
                              const act = state.available_actions.find((a) => a.action_id === "font_conversion");
                              const isEnabled = act ? act.is_enabled : true;
                              const isSel = currentSubtask === "unicode_to_devlys";
                              return (
                                <div
                                  key="unicode_to_devlys"
                                  id="subtask-unicode-to-devlys"
                                  data-subtask="unicode_to_devlys"
                                  data-req="font_conversion"
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => setSubtaskByPrimary((prev) => ({ ...prev, font_conversion: "unicode_to_devlys" }))}
                                  title={isEnabled ? "Reverses Unicode Devanagari text into legacy DevLys 010." : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">Unicode to DevLys</h4>
                                    <span class={`action-tag ${isSel ? "active" : ""}`}>DEVLYS</span>
                                  </div>
                                  <p class="action-card-desc">
                                    Reverses Unicode Devanagari text into legacy DevLys 010 typewriter encoding using precompiled reverse transducers.
                                  </p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">font_conversion:to_devlys</code>
                                  </div>
                                </div>
                              );
                            })()}
                          </div>
                        </div>
                      )}

                      {task.id === "translation" && (
                        <div class="subtasks-container">
                          {/* Direction selector first */}
                          <div class="translation-direction-toolbar" role="group" aria-label="Translation Direction">
                            <button
                              id="btn-direction-auto"
                              data-dir=""
                              class={`direction-seg-btn ${transDirection === "" ? "active" : ""}`}
                              type="button"
                              onClick={() => setTransDirection("")}
                            >
                              ⚡ Auto-Detect Language Direction
                            </button>
                            <button
                              id="btn-direction-hi-en"
                              data-dir="hi_en"
                              class={`direction-seg-btn ${transDirection === "hi_en" ? "active" : ""}`}
                              type="button"
                              onClick={() => setTransDirection("hi_en")}
                            >
                              Hindi → English
                            </button>
                            <button
                              id="btn-direction-en-hi"
                              data-dir="en_hi"
                              class={`direction-seg-btn ${transDirection === "en_hi" ? "active" : ""}`}
                              type="button"
                              onClick={() => setTransDirection("en_hi")}
                            >
                              English → Hindi
                            </button>
                          </div>

                          {/* 6 Engine Choices */}
                          <div class="subtasks-grid">
                            {[
                              {
                                id: "indictrans2",
                                actionId: "translation",
                                label: "IndicTrans2 (Local)",
                                tag: "INDICTRANS2",
                                isCloud: false,
                                desc: "AI4Bharat IndicTrans2 local Transformer. Optimized for high-fidelity 22 Indian languages.",
                                code: "translation:indictrans2",
                              },
                              {
                                id: "opus_mt",
                                actionId: "translation",
                                label: "Helsinki OPUS-MT (Local)",
                                tag: "OPUS-MT",
                                isCloud: false,
                                desc: "Fast Marian-based neural translation engine running fully offline and local.",
                                code: "translation:opus_mt",
                              },
                              {
                                id: "gemini",
                                actionId: "gemini_translation",
                                label: "Google Gemini (Cloud)",
                                tag: "GEMINI",
                                isCloud: true,
                                desc: "Google Gemini multimodal translation adapter. High context multilingual reasoning.",
                                code: "gemini_translation",
                              },
                              {
                                id: "mistral",
                                actionId: "mistral_translation",
                                label: "Mistral (Cloud)",
                                tag: "MISTRAL",
                                isCloud: true,
                                desc: "Mistral AI European cloud translation adapter. Authorized by Kavacha.",
                                code: "mistral_translation",
                              },
                              {
                                id: "azure",
                                actionId: "azure_translation",
                                label: "Azure AI (Cloud)",
                                tag: "AZURE",
                                isCloud: true,
                                desc: "Microsoft Azure AI Translator cloud service. Enterprise translation backbone.",
                                code: "azure_translation",
                              },
                            ].map((eng) => {
                              const act = state.available_actions.find((a) => a.action_id === eng.actionId);
                              const isEnabled = act ? act.is_enabled : false;
                              const isSel = currentSubtask === eng.id;
                              return (
                                <div
                                  key={eng.id}
                                  id={`subtask-engine-${eng.id.replace(/_/g, "-")}`}
                                  data-subtask={eng.id}
                                  data-req={eng.actionId}
                                  class={`subtask-card req-card ${isSel ? "selected" : ""} ${!isEnabled ? "disabled" : ""}`}
                                  onClick={() => {
                                    setSubtaskByPrimary((prev) => ({ ...prev, translation: eng.id }));
                                  }}
                                  title={isEnabled ? eng.desc : (act?.disabled_reason || "Unavailable")}
                                >
                                  <div class="action-card-header">
                                    <h4 class="action-card-name">{eng.label}</h4>
                                    <span class={`action-tag ${eng.isCloud ? "action-tag--cloud" : ""} ${isSel ? "active" : ""}`}>
                                      {eng.tag}
                                    </span>
                                  </div>
                                  <p class="action-card-desc">{isEnabled ? eng.desc : (act?.disabled_reason || "Unavailable")}</p>
                                  <div class="action-card-footer">
                                    <span class={`action-dot ${isSel ? "active" : ""}`} />
                                    <code class="action-code">{eng.code}</code>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* If no Level 1 task is selected, show instructional prompt */}
          {!primaryTask && (
            <div id="level1-empty-prompt" class="level1-empty-prompt">
              <span class="level1-prompt-icon">👆</span>
              <div class="level1-prompt-text">
                <strong>Select a Primary Task Above</strong>
                <p>Choose one of the four primary tasks above to view its specific methods, engines, and configuration options.</p>
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
              {!primaryTask ? "Select a task above" : preflight ? `${eligibleCount} eligible · ${issueCount} issues` : "Select inputs to validate"}
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
                <strong>{plan.document_count} document{plan.document_count === 1 ? "" : "s"}</strong>
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
                  {plan.devices.map((device) => `${device.device_type}${device.is_available ? "" : " unavailable"}`).join(" · ")}
                </small>
              ) : null}
            </div>
          ) : null}

          {planError ? <div class="inline-error">{planError}</div> : null}

          <button
            id="btn-start-run"
            class="button primary btn-primary btn-start-run"
            disabled={working || !primaryTask || !eligiblePaths.length || !activeAction?.is_enabled || Boolean(planError)}
            onClick={() => void handleStart()}
            type="button"
          >
            <span>{working ? "Working…" : !primaryTask ? "Select a Task to Start" : "Start document processing"}</span>
            <span class="btn-bolt">⚡</span>
          </button>
        </section>
      </div>
    </div>
  );
}
