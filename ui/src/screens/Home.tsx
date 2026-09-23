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
  const [passwords, setPasswords] = useState<Record<string, string>>({});

  const handleSetPassword = (nameOrPath: string, pass: string, applyToAll: boolean) => {
    setPasswords((prev) => {
      const next = { ...prev, [nameOrPath]: pass };
      if (applyToAll) {
        for (const item of selection.items) {
          if (item.display_name.toLowerCase().endsWith(".pdf")) {
            next[item.source_path || item.display_name] = pass;
          }
        }
      }
      return next;
    });
  };

  const [primaryTask, setPrimaryTask] = useState<PrimaryTaskId | null>(null);

  const [subtaskByPrimary, setSubtaskByPrimary] = useState<Record<PrimaryTaskId, string>>(() => ({
    documents_extraction:
      state.requirement === "ocr" || state.requirement.endsWith("_ocr")
        ? "ocr"
        : "native",
    bank_consolidation: (state as any).profile === "accurate" ? "accurate" : "instant",
    font_conversion: "legacy_to_unicode",
    translation: state.requirement.endsWith("_translation")
      ? state.requirement.replace("_translation", "")
      : "indictrans2",
  }));

  const [ocrEngineType, setOcrEngineType] = useState<"local" | "cloud">(
    state.requirement.endsWith("_ocr") && state.requirement !== "ocr" ? "cloud" : "local"
  );
  const [ocrModelLang, setOcrModelLang] = useState<"devanagari" | "en_v6">("devanagari");
  const [ocrProfile, setOcrProfile] = useState<"accurate" | "instant">("instant");
  const [ocrFallbackToLocal, setOcrFallbackToLocal] = useState<boolean>(true);

  const [cloudOcrProvider, setCloudOcrProvider] = useState<string>(
    state.requirement.endsWith("_ocr") && state.requirement !== "ocr" ? state.requirement : "mistral_ocr"
  );
  const [transDirection, setTransDirection] = useState<string>("");
  const [statutoryEnabled, setStatutoryEnabled] = useState<boolean>(true);
  const [convertLegacyFonts, setConvertLegacyFonts] = useState<boolean>(true);
  const [layoutAnalysis, setLayoutAnalysis] = useState<boolean>(false);
  const [preserveLayout, setPreserveLayout] = useState<boolean>(false);
  const [sourceFont, setSourceFont] = useState<string>("");
  const [skipHeaderFooter, setSkipHeaderFooter] = useState<boolean>(true);
  const [removeStamps, setRemoveStamps] = useState<boolean>(false);
  const [transPreserveProperNouns, setTransPreserveProperNouns] = useState<boolean>(true);
  const [forcedFreshRun, setForcedFreshRun] = useState<boolean>(false);

  const ocrAction = state.available_actions.find((a) => a.action_id === "ocr");
  const [ocrCustomParams, setOcrCustomParams] = useState<Record<string, unknown>>(() => {
    const d = actionDefaults(ocrAction);
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
      ocrProfile,
      ocrEngineType,
    });
  }, [primaryTask, currentSubtask, layoutAnalysis, preserveLayout, cloudOcrProvider, ocrProfile, ocrEngineType]);

  const activeAction = currentBackendMapping
    ? state.available_actions.find((action) => action.action_id === currentBackendMapping.requirement)
    : undefined;

  const buildRequest = (): RunRequest => {
    const req = currentBackendMapping?.requirement ?? "read_native";
    const prof = currentBackendMapping?.profile ?? "instant";
    const customOptions: Record<string, unknown> = {};

    if (primaryTask === "documents_extraction") {
      if (currentSubtask === "native") {
        customOptions.statutory = statutoryEnabled;
        customOptions.convert_legacy_fonts = convertLegacyFonts;
        if (layoutAnalysis) {
          customOptions.layout_analysis = true;
        }
        customOptions.skip_header_footer = skipHeaderFooter;
      } else if (
        currentSubtask === "ocr" ||
        currentSubtask === "accurate_ocr" ||
        currentSubtask === "instant_ocr" ||
        currentSubtask === "custom_ocr" ||
        currentSubtask === "cloud_ocr"
      ) {
        if (preserveLayout) {
          customOptions.preserve_layout = true;
        }
        customOptions.skip_header_footer = skipHeaderFooter;

        if (statutoryEnabled) {
          customOptions.statutory = true;
        }
        if (convertLegacyFonts) {
          customOptions.convert_legacy_fonts = true;
        }
        if (removeStamps) {
          customOptions.remove_stamps = true;
          customOptions.stamp_mode = "remove";
        }

        if (ocrEngineType === "cloud" || currentSubtask === "cloud_ocr") {
          customOptions.engine = cloudOcrProvider;
          if (ocrFallbackToLocal) {
            customOptions.fallback_to_local = true;
          }
        } else {
          customOptions.engine = "rapidocr";
          customOptions.lang = ocrModelLang;
        }

        const ocrAct = state.available_actions.find((a) => a.action_id === "ocr");
        for (const parameter of ocrAct?.parameters ?? []) {
          if (
            parameter.parameter_id === "profile" ||
            parameter.parameter_id === "binarize" ||
            parameter.parameter_id === "lang" ||
            parameter.parameter_id === "preprocess" ||
            parameter.parameter_id === "remove_stamps"
          ) {
            continue;
          }
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
        if (sourceFont) customOptions.source_font = sourceFont;
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
      customOptions.statutory = statutoryEnabled;
      customOptions.preserve_proper_nouns = transPreserveProperNouns;
    }

    if (Object.keys(passwords).length > 0) {
      customOptions.passwords = passwords;
      const firstPass = Object.values(passwords).find((p) => Boolean(p.trim()));
      if (firstPass) customOptions.pdf_password = firstPass;
    }

    if (forcedFreshRun) {
      customOptions.forced_fresh_run = true;
      customOptions.bypass_cache = true;
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
      (window as any).__sarathi_set_trans_statutory = (e: boolean) => setStatutoryEnabled(e);
      (window as any).__sarathi_set_trans_proper_nouns = (e: boolean) => setTransPreserveProperNouns(e);
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

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") {
        e.preventDefault();
        void handleBrowse(false);
      } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        void handleStart();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [roots, recursive, primaryTask, eligiblePaths.length, planError]);

  const showGroupedSummary = visibleItems.length > 10 && !showAllInputsTable;

  return (
    <div class="screen-grid home-cockpit" data-purpose="dual-pane-workspace">
      {/* Column 1: Document Intake */}
      <section class="panel intake-panel" data-purpose="document-intake">
        <div class="panel-header">
          <div class="panel-title-wrap">
            <h2 class="panel-heading">1. Add documents</h2>
          </div>
          {visibleItems.length > 0 && <span class="count-badge">
            {visibleItems.length} selected ({formatBytes(totalSize)})
          </span>}
        </div>

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
              passwords={passwords}
              onSetPassword={handleSetPassword}
            />
        </div>
      </section>

        {/* Column 2: Processing Capability & Execution Plan */}
      <div class="column-action">
        {/* Processing Action / Workflow Studio Panel */}
        <section class="panel capability-panel" data-purpose="task-selection">
          <div class="panel-header studio-panel-header">
            <h2 class="panel-heading">2. Choose a task</h2>
          </div>

          <div class="panel-body capability-panel-body">
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
              ocrEngineType={ocrEngineType}
              ocrModelLang={ocrModelLang}
              ocrFallbackToLocal={ocrFallbackToLocal}
              ocrProfile={ocrProfile}
              onSetOcrProfile={setOcrProfile}
              removeStamps={removeStamps}
              preserveProperNouns={transPreserveProperNouns}
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
              onSetRemoveStamps={(enabled) => setRemoveStamps(enabled)}
              onSetPreserveProperNouns={(enabled) => setTransPreserveProperNouns(enabled)}
              onSetOcrCustomParam={(key, val) =>
                setOcrCustomParams((prev) => ({ ...prev, [key]: val }))
              }
              onSetOcrEngineType={(engType) => setOcrEngineType(engType)}
              onSetOcrModelLang={(lang) => setOcrModelLang(lang)}
              onSetOcrFallbackToLocal={(fb) => setOcrFallbackToLocal(fb)}
            />

            {/* Integrated Cockpit Action & Hardware Telemetry Footer */}
            <div class="cockpit-action-footer">
              <div class="footer-telemetry">
                {!primaryTask ? (
                  <span class="footer-status-quiet">Choose a task to continue</span>
                ) : plan ? (
                  <div class="footer-hw-group">
                    <span class="footer-doc-pill">
                      {plan.document_count} doc{plan.document_count === 1 ? "" : "s"} ({formatBytes(totalSize)})
                    </span>
                    <span class="footer-device-chip" title="Target Hardware Accelerator">
                      ⚡ {plan.devices.length ? plan.devices.map((d) => d.device_type).join(" · ") : "Intel Arc iGPU (OpenVINO FP16)"}
                    </span>
                    <label
                      class={`footer-fresh-toggle ${forcedFreshRun ? "active" : ""}`}
                      title="Bypass Smriti cache and force fresh execution"
                    >
                      <input
                        id="toggle-forced-fresh-run"
                        type="checkbox"
                        checked={forcedFreshRun}
                        onChange={(e) => setForcedFreshRun(e.currentTarget.checked)}
                      />
                      <span>⚡ Forced fresh run</span>
                    </label>
                  </div>
                ) : (
                  <span class="footer-status-quiet">
                    {eligibleCount ? `${eligibleCount} eligible · ${issueCount} issues` : "Select eligible files in intake"}
                  </span>
                )}
                {planError && <div class="inline-error">{planError}</div>}
              </div>

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
                <span class="btn-run-content">
                  <span>
                    {working
                      ? "Working…"
                      : eligiblePaths.length
                      ? `Start Processing (${eligiblePaths.length})`
                      : "Start Processing"}
                  </span>
                  <svg class="btn-bolt-icon" width="15" height="15" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                </span>
                <kbd class="btn-kbd-hint">Ctrl+Enter</kbd>
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
