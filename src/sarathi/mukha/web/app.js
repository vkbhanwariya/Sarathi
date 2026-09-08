/**
 * Sarathi V2 — Mukha Web Application Controller (Modular ES Root)
 *
 * Coordinates screen switching, presentation state updates, keyboard shortcuts,
 * and lifecycle events across modular native ES components.
 */

import { initSSE, pollState } from "./js/api.js";
import { elements, hideError, initDom, renderProgressBar } from "./js/dom.js";
import { formatStatus } from "./js/formatters.js";
import { initHomeScreen, renderAvailableActions } from "./js/screens/home.js";
import { initInspectorScreen, loadInspector } from "./js/screens/inspector.js";
import { initMonitorScreen, renderMonitor } from "./js/screens/monitor.js";
import { initReviewScreen, loadReviewQueue } from "./js/screens/review.js";
import { initSummaryScreen, renderSummary } from "./js/screens/summary.js";
import { initCommandPalette, openCommandPalette } from "./js/palette.js";
import { closeDocumentPreview, initPreviewDialog } from "./js/preview.js";
import { registerScreenCallback, state, switchScreen } from "./js/state.js";

function updatePresentation(appState) {
    if (!appState) return;

    // Initial Hydration from canonical backend state on browser reload
    if (!state.isHydrated) {
        if (appState.requirement) {
            state.currentRequirement = appState.requirement;
        }
        if (appState.terminal_summary && appState.terminal_summary.run_id) {
            state.viewedRunId = appState.terminal_summary.run_id;
        }
        if (appState.active_run && appState.active_run.run_id) {
            state.activeRunId = appState.active_run.run_id;
            state.activeRunStatus = appState.active_run.status;
        }
        if (appState.active_run && appState.active_run.status === "RUNNING") {
            switchScreen("monitor");
        } else if (appState.current_screen && appState.current_screen !== "home") {
            switchScreen(appState.current_screen);
        } else if (appState.terminal_summary && !appState.active_run) {
            switchScreen("summary");
        }
        state.isHydrated = true;
    }

    // Header Review Queue Pending Badge
    if (elements.headerReviewBadge) {
        const reviewCount = (appState.review_queue || []).length;
        elements.headerReviewBadge.textContent = reviewCount > 0 ? `${reviewCount} Pending` : "";
        elements.headerReviewBadge.classList.toggle("hidden", reviewCount === 0);
    }

    // Header Status Dot & Label
    if (elements.systemStatusDot && elements.systemStatusText) {
        const curStatus = state.activeRunStatus || (appState.active_run ? appState.active_run.status : "idle");
        const statusInfo = formatStatus(curStatus);
        elements.systemStatusDot.className = statusInfo.dotClass;
        elements.systemStatusText.textContent = statusInfo.label;
    }

    // Top-Level Global Progress Bar
    if (elements.topProgressContainer) {
        const activeRun = appState.active_run;
        if (activeRun && activeRun.status === "RUNNING") {
            const stageText = activeRun.current_focus && activeRun.current_focus.stage
                ? `${activeRun.current_focus.stage}${activeRun.current_focus.operation_name ? ' — ' + activeRun.current_focus.operation_name : ''}`
                : "Processing documents...";
            const progState = activeRun.progress || { kind: "known", completed: activeRun.terminal_files || 0, total: activeRun.total_files || 0 };
            renderProgressBar(elements.topProgressContainer, elements.topProgressBar, elements.topProgressStage, elements.topProgressPct, progState, { stageText });
        } else if (activeRun && (activeRun.status === "SUCCESS" || activeRun.status === "PARTIAL")) {
            renderProgressBar(elements.topProgressContainer, elements.topProgressBar, elements.topProgressStage, elements.topProgressPct, { kind: "known", percentage: 100 }, { stageText: `Completed (${activeRun.status})` });
            setTimeout(() => {
                if (elements.topProgressContainer && (!state.activeRunStatus || state.activeRunStatus !== "RUNNING")) {
                    elements.topProgressContainer.classList.add("hidden");
                }
            }, 2500);
        } else {
            elements.topProgressContainer.classList.add("hidden");
        }
    }

    // Dynamic Capability & Available Actions Synchronization
    if (appState.available_actions !== undefined) {
        renderAvailableActions(appState.available_actions || []);
    }

    // Aarambha Startup Overlay
    if (elements.aarambhaOverlay) {
        if (appState.startup && appState.startup.is_initializing && appState.startup.elapsed_ns > 5_000_000_000) {
            elements.aarambhaOverlay.classList.remove("hidden");
            if (elements.aarambhaStage) {
                elements.aarambhaStage.textContent = appState.startup.current_stage || "Initializing...";
            }
        } else {
            elements.aarambhaOverlay.classList.add("hidden");
        }
    }

    // Pravritti Monitor Updates
    const activeRun = appState.active_run;
    if (activeRun) {
        state.activeRunId = activeRun.run_id;
        state.activeRunStatus = activeRun.status;
        renderMonitor(activeRun);
    }

    // Auto Navigation to Samapti Summary upon Run Completion (strictly when followLive is active)
    const summary = appState.terminal_summary;
    if (summary) {
        if (state.followLive) {
            renderSummary(summary);
        }
        if (state.followLive && state.lastAutoNavigatedRunId !== summary.run_id && state.currentScreen === "monitor") {
            state.lastAutoNavigatedRunId = summary.run_id;
            state.viewedRunId = summary.run_id;
            switchScreen("summary");
        }
    }

    // Live Inspector updates if currently viewing Nirikshana and following live
    if (state.currentScreen === "inspector" && (state.followLive || !state.viewedRunId)) {
        loadInspector();
    }
}

// Keyboard Shortcuts (F1-F5, Escape, Ctrl+H)
function setupKeyboardShortcuts() {
    window.addEventListener("keydown", (e) => {
        if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") {
            return;
        }
        if (e.key === "F1") { e.preventDefault(); switchScreen("home"); }
        else if (e.key === "F2") { e.preventDefault(); switchScreen("monitor"); }
        else if (e.key === "F3") { e.preventDefault(); switchScreen("review"); }
        else if (e.key === "F4") { e.preventDefault(); switchScreen("summary"); }
        else if (e.key === "F5") { e.preventDefault(); switchScreen("inspector"); }
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "h") {
            e.preventDefault();
            if (elements.btnOpenHistory) elements.btnOpenHistory.click();
        } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "p") {
            e.preventDefault();
            openCommandPalette();
        } else if (e.key === "Escape") {
            closeDocumentPreview();
            if (elements.historyDrawer && elements.historyDrawer.classList.contains("open")) {
                elements.historyDrawer.classList.remove("open");
            }
            const pal = document.getElementById("command-palette-dialog");
            if (pal && pal.open) pal.close();
        }
    });
}

function init() {
    initDom();

    // Register screen lazy-loaders
    registerScreenCallback("review", () => loadReviewQueue());
    registerScreenCallback("inspector", () => loadInspector());

    // Initialize individual screen controllers
    initHomeScreen();
    initMonitorScreen();
    initReviewScreen();
    initSummaryScreen();
    initInspectorScreen();
    initCommandPalette();

    // Navigation Tab Switching
    if (elements.navTabs) {
        elements.navTabs.forEach((tab) => {
            tab.addEventListener("click", () => {
                switchScreen(tab.dataset.screen);
            });
        });
    }

    initPreviewDialog();

    // Error banner dismiss button
    if (elements.btnDismissError) {
        elements.btnDismissError.addEventListener("click", hideError);
    }

    setupKeyboardShortcuts();

    // Start Real-Time SSE Stream with adaptive fallback
    initSSE(updatePresentation);
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
} else {
    init();
}
