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
  revealRun,
  subscribeState,
  type StateStream,
} from "./api";
import { CommandPalette } from "./components/CommandPalette";
import { DocumentPreviewModal } from "./components/DocumentPreviewModal";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { formatBytes } from "./formatters";
import { History } from "./screens/History";
import { Home } from "./screens/Home";
import { Inspector } from "./screens/Inspector";
import { Monitor } from "./screens/Monitor";
import { Review } from "./screens/Review";
import { Summary } from "./screens/Summary";
import type {
  ApplicationViewState,
  InspectorViewState,
  RunSummaryView,
  Screen,
  TerminalRunHistoryView,
} from "./types";
import { isCloudAction } from "./workflow/taskCatalog";

// Re-exports for modular consumer compatibility
export {
  formatBytes,
  formatConfidence,
  formatDuration,
  formatStatus,
  formatSummaryTitle,
} from "./formatters";
export {
  ActionParameter,
  EmptyState,
  Metric,
  actionDefaults,
} from "./components/Common";
export { CommandPalette } from "./components/CommandPalette";
export { DocumentPreviewModal } from "./components/DocumentPreviewModal";
export { HistoryDrawer } from "./components/HistoryDrawer";
export { History } from "./screens/History";
export { Home } from "./screens/Home";
export { Inspector } from "./screens/Inspector";
export { Monitor } from "./screens/Monitor";
export { Review } from "./screens/Review";
export { Summary } from "./screens/Summary";
export {
  PRIMARY_TASKS,
  isCloudAction,
  type PrimaryTaskDef,
  type PrimaryTaskId,
} from "./workflow/taskCatalog";

const screens: readonly { id: Screen; label: string }[] = [
  { id: "home", label: "Home" },
  { id: "monitor", label: "Monitor" },
  { id: "review", label: "Review" },
  { id: "history", label: "History" },
  { id: "inspector", label: "Inspector" },
];

export function App() {
  const [screen, setScreen] = useState<Screen>("home");
  const [state, setState] = useState<ApplicationViewState | null>(null);
  const [summaryOverride, setSummaryOverride] = useState<RunSummaryView | null>(null);
  const [inspectorOverride, setInspectorOverride] = useState<InspectorViewState | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<readonly TerminalRunHistoryView[]>([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [previewTarget, setPreviewTarget] = useState<{ pathOrUrl: string; displayName: string } | null>(null);
  const connectedRef = useRef(false);
  const summaryRequest = useRef(0);
  const summarySeqRef = useRef(0);
  const inspectorRequest = useRef(0);

  const refresh = async () => {
    try {
      const next = await fetchState();
      setState(next);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to refresh Mukha state.");
    }
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "p") {
        event.preventDefault();
        setPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

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
      (next) => {
        setState(next);
        setError(null);
      },
      (isConnected) => {
        connectedRef.current = isConnected;
        setConnected(isConnected);
      }
    );
    const pollId = window.setInterval(() => {
      if (!connectedRef.current) {
        void fetchState(abort.signal)
          .then((next) => {
            setState(next);
            setError(null);
          })
          .catch((reason) => {
            if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to refresh Mukha state.");
          });
      }
    }, 2000);
    return () => {
      abort.abort();
      stream?.close();
      window.clearInterval(pollId);
    };
  }, []);

  const openHistory = async (showDrawer = true) => {
    if (showDrawer) setHistoryOpen(true);
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      setHistory(await fetchHistory(50));
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : "Unable to load run history.");
    } finally {
      setHistoryBusy(false);
    }
  };

  const loadSummary = async (runId: string) => {
    const seq = ++summarySeqRef.current;
    const requestId = ++summaryRequest.current;
    setError(null);
    try {
      const summary = await fetchRunSummary(runId);
      if (seq !== summarySeqRef.current || requestId !== summaryRequest.current) return;
      setSummaryOverride(summary);
      setInspectorOverride(null);
      setHistoryOpen(false);
      setScreen("monitor");
    } catch (reason) {
      if (seq === summarySeqRef.current && requestId === summaryRequest.current) {
        setError(reason instanceof Error ? reason.message : "Unable to load run summary.");
      }
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
      if (requestId === inspectorRequest.current)
        setError(reason instanceof Error ? reason.message : "Unable to load inspector data.");
    }
  };

  const chooseScreen = (next: Screen) => {
    if (next === "summary") {
      setSummaryOverride(null);
      setScreen("monitor");
      return;
    }
    if (next === "history") {
      void openHistory(false);
    }
    if (next === "inspector") {
      setInspectorOverride(null);
      const runId = state?.active_run?.run_id ?? state?.terminal_summary?.run_id;
      if (runId) {
        void loadInspector(runId);
        return;
      }
    }
    setScreen(next);
  };

  const handleProcessAnother = async () => {
    try {
      await intakePaths([], false);
    } catch {
      // ignore
    }
    chooseScreen("home");
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

  useEffect(() => {
    if (typeof window !== "undefined") {
      (window as any).__sarathi_load_summary = loadSummary;
      (window as any).loadRunSummary = loadSummary;
    }
  }, [loadSummary]);

  const paletteCommands = useMemo(
    () => [
      { id: "nav-home", label: "Navigate: Griha (Home - Intake / Setup)", action: () => chooseScreen("home") },
      { id: "nav-monitor", label: "Navigate: Pravritti (Monitor - Execution & Results)", action: () => chooseScreen("monitor") },
      { id: "nav-review", label: "Navigate: Pariksha (Review - Exception Queue)", action: () => chooseScreen("review") },
      { id: "nav-history", label: "Navigate: Itihasa (History - Run Ledger)", action: () => chooseScreen("history") },
      { id: "nav-inspector", label: "Navigate: Nirikshana (Inspector - Telemetry)", action: () => chooseScreen("inspector") },
      {
        id: "act-add-files",
        label: "Action: Add Input Files...",
        action: () => {
          chooseScreen("home");
          void browseFiles().then((paths) => {
            if (paths.length) void intakePaths(paths, false);
          });
        },
      },
      {
        id: "act-add-folder",
        label: "Action: Add Folder...",
        action: () => {
          chooseScreen("home");
          void browseFolder().then((paths) => {
            if (paths.length) void intakePaths(paths, true);
          });
        },
      },
      { id: "act-start-run", label: "Action: Start Document Processing", action: () => { chooseScreen("home"); } },
      {
        id: "act-cancel-run",
        label: "Action: Cancel Active Run",
        action: () => {
          if (state?.active_run?.run_id) void cancelRun(state.active_run.run_id);
        },
      },
      { id: "act-history", label: "Action: Open Run History (Ctrl+H)", action: () => void openHistory() },
      { id: "act-clear-history", label: "Action: Clear Terminal Run History", action: () => void handleClearHistory() },
      { id: "act-clear-cache", label: "Action: Clear Smriti Cache", action: () => void handleClearCache() },
      {
        id: "act-copy-logs",
        label: "Action: Copy Activity Logs to Clipboard",
        action: () => {
          const logs = inspector?.activity_logs ?? state?.inspector?.activity_logs ?? [];
          const text = logs.map((l) => `[${l.timestamp}] [${l.severity}] [${l.component}] ${l.message}`).join("\n");
          void navigator.clipboard.writeText(text || "No activity logs available.");
        },
      },
      {
        id: "act-export-diag",
        label: "Action: Export Run Diagnostics (JSON)",
        action: () => {
          const runId = inspector?.run_id ?? state?.active_run?.run_id ?? summary?.run_id;
          if (runId) {
            const link = document.createElement("a");
            link.href = `/api/runs/${encodeURIComponent(runId)}/diagnostics?download=1`;
            link.download = `diagnostics_${runId}.json`;
            document.body.appendChild(link);
            link.click();
            link.remove();
          }
        },
      },
    ],
    [state, summary, inspector]
  );

  const docCount = state?.input_selection?.items?.length ?? 0;
  const eligibleCount = state?.input_selection?.items?.filter((i) => i.is_eligible).length ?? 0;
  const totalSize = state?.input_selection?.items?.reduce((acc, i) => acc + (i.size_bytes || 0), 0) ?? 0;
  const policyLabel = state?.policy_label || (state?.requirement && isCloudAction(state.requirement) ? "Cloud" : "Local");

  return (
    <div class="app-shell app-container">
      <aside class="sidebar" data-purpose="main-sidebar">
        <div class="sidebar-top">
          {/* Branding & Creator Tag */}
          <div class="brand">
            <div class="brand-mark">S</div>
            <div class="brand-text">
              <h1>Sarathi</h1>
              <span class="brand-subtitle">Local Intelligence</span>
            </div>
          </div>

          {/* Navigation Views */}
          <nav class="sidebar-nav" aria-label="Primary Navigation">
            {screens.map((item) => (
              <button
                class={screen === item.id ? "nav-item nav-tab active" : "nav-item nav-tab"}
                data-screen={item.id}
                onClick={() => chooseScreen(item.id)}
                type="button"
                key={item.id}
                aria-label={item.label}
                aria-current={screen === item.id ? "page" : undefined}
              >
                <span class="nav-glyph">{item.label.slice(0, 1)}</span>
                <span>{item.label}</span>
              </button>
            ))}
          </nav>

          {/* Action Utilities */}
          <div class="sidebar-actions">
            <button
              id="btn-command-palette"
              class="sidebar-action-btn"
              onClick={() => setPaletteOpen(true)}
              title="Command Palette (Ctrl+P)"
              type="button"
            >
              <svg class="icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16m-7 6h7" />
              </svg>
              <span>Commands</span>
            </button>
            <button
              id="btn-open-history"
              class="sidebar-action-btn"
              onClick={() => void openHistory()}
              title="Activity History"
              type="button"
            >
              <svg class="icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>History</span>
            </button>
          </div>

          {/* Workspace Pill Card */}
          <div class="sidebar-workspace-card">
            <div class="workspace-card-header">
              <span class="workspace-card-title">Workspace</span>
              <span class="workspace-card-badge">{eligibleCount} eligible</span>
            </div>
            <div class="workspace-card-status">
              <span class="workspace-dot" />
              <span>Ready</span>
              <span class="workspace-sep">·</span>
              <span class="workspace-mode">{policyLabel}</span>
            </div>
            <div class="workspace-card-stats">
              {docCount} docs · {formatBytes(totalSize)}
            </div>
          </div>
        </div>

        {/* Engine Telemetry / Status Footer */}
        <div class="sidebar-footer">
          <div class="telemetry-engine-row">
            <span class="telemetry-ping-wrap">
              <span class="telemetry-ping" />
              <span class="telemetry-dot" />
            </span>
            <span class="telemetry-label">Local Engine</span>
            <span class="telemetry-badge">Ready</span>
          </div>
          <div class="telemetry-detail-row">
            <span>{state?.requirement ? state.requirement.replace(/_/g, " ") : "read_native"}</span>
            <span>rev {state?.state_revision ?? "1"}</span>
          </div>
        </div>
      </aside>

      <main class={`workspace app-main ${screen === "home" ? "workspace--home" : ""}`}>
        <header class="topbar app-header">
          <div class="topbar-left">
            <span class="eyebrow">Mukha</span>
            <h2 class="screen-title">{screens.find((item) => item.id === screen)?.label}</h2>
          </div>
          <div class="topbar-meta">
            <span class="badge">{state?.requirement || "No requirement"}</span>
            <span class="revision">rev {state?.state_revision ?? "—"}</span>
          </div>
        </header>

        {error ? (
          <div class="error-banner" role="alert">
            {error}
          </div>
        ) : null}
        {!state ? (
          <div class="loading">
            <div class="spinner" />
            <strong>Connecting to Sarathi…</strong>
          </div>
        ) : (
          <div class="screen">
            <div id="screen-home" class={`screen-view ${screen === "home" ? "active" : "hidden"}`}>
              <Home
                state={state}
                onError={setError}
                onStarted={(runId) => {
                  setSummaryOverride(null);
                  setInspectorOverride(null);
                  chooseScreen("monitor");
                  void refresh().catch(() => undefined);
                  if (!runId) setError("Run started without an identifier.");
                }}
                onPreview={(pathOrUrl, displayName) => setPreviewTarget({ pathOrUrl, displayName })}
              />
            </div>
            <div
              id="screen-monitor"
              class={`screen-view ${screen === "monitor" || screen === "summary" ? "active" : "hidden"}`}
              data-run-id={summary?.run_id ?? state?.active_run?.run_id ?? ""}
            >
              <Monitor
                state={state}
                summary={summary}
                onError={setError}
                onReveal={revealRun}
                onPreview={(pathOrUrl, displayName) => setPreviewTarget({ pathOrUrl, displayName })}
                onNavigate={(scr) => {
                  if (scr === "home") void handleProcessAnother();
                  else chooseScreen(scr);
                }}
              />
            </div>
            <div id="screen-review" class={`screen-view ${screen === "review" ? "active" : "hidden"}`}>
              <Review state={state} onError={setError} onRefresh={refresh} />
            </div>
            <div id="screen-history" class={`screen-view ${screen === "history" ? "active" : "hidden"}`}>
              <History
                history={history}
                busy={historyBusy}
                error={historyError}
                onRefresh={async () => {
                  setHistoryBusy(true);
                  try {
                    setHistory(await fetchHistory(50));
                  } catch (e) {
                    setHistoryError(e instanceof Error ? e.message : "Failed to load history.");
                  } finally {
                    setHistoryBusy(false);
                  }
                }}
                onSummary={(runId) => void loadSummary(runId)}
                onInspector={(runId) => void loadInspector(runId)}
                onClearHistory={() => void handleClearHistory()}
                onClearCache={() => void handleClearCache()}
                onReveal={revealRun}
                onNavigateHome={() => chooseScreen("home")}
              />
            </div>
            <div id="screen-inspector" class={`screen-view ${screen === "inspector" ? "active" : "hidden"}`}>
              <Inspector inspector={inspector} />
            </div>
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

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={paletteCommands} />
      <DocumentPreviewModal target={previewTarget} onClose={() => setPreviewTarget(null)} />
    </div>
  );
}
