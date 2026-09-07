/**
 * Sarathi V2 — Mukha Web Application Controller (Modular ES Root)
 *
 * Coordinates screen switching, presentation state updates, keyboard shortcuts,
 * and lifecycle events across modular native ES components.
 */

import { initSSE, pollState } from "./js/api.js";
import { elements, hideError, initDom } from "./js/dom.js";
import { initHomeScreen, renderAvailableActions } from "./js/screens/home.js";
import { initInspectorScreen, loadInspector } from "./js/screens/inspector.js";
import { initMonitorScreen, renderMonitor } from "./js/screens/monitor.js";
import { initReviewScreen, loadReviewQueue } from "./js/screens/review.js";
import { initSummaryScreen, renderSummary } from "./js/screens/summary.js";
import { initCommandPalette, openCommandPalette } from "./js/palette.js";
import { registerScreenCallback, state, switchScreen } from "./js/state.js";

// Presentation View State Projection
function updatePresentation(appState) {
    if (!appState) return;

    // Header Status Dot & Label
    if (elements.systemStatusDot && elements.systemStatusText) {
        const curStatus = (state.activeRunStatus || "idle").toUpperCase();
        if (curStatus === "RUNNING") {
            elements.systemStatusDot.className = "status-dot running";
            elements.systemStatusText.textContent = "Processing...";
        } else if (curStatus === "FAILED") {
            elements.systemStatusDot.className = "status-dot error";
            elements.systemStatusText.textContent = "Failed";
        } else if (curStatus === "CANCELLED") {
            elements.systemStatusDot.className = "status-dot warning";
            elements.systemStatusText.textContent = "Cancelled";
        } else {
            elements.systemStatusDot.className = "status-dot online";
            elements.systemStatusText.textContent = "Ready";
        }
    }

    // Dynamic Capability & Available Actions Synchronization
    if (appState.available_actions && appState.available_actions.length > 0) {
        renderAvailableActions(appState.available_actions);
        appState.available_actions.forEach((act) => {
            const card = document.querySelector(`.req-card[data-req="${act.action_id}"]`);
            if (card) {
                card.disabled = !act.is_enabled;
                card.classList.toggle("disabled", !act.is_enabled);
                const badge = card.querySelector(".req-status");
                if (badge) {
                    if (act.is_enabled) {
                        badge.className = "req-status badge badge-emerald";
                        badge.textContent = "Ready";
                        badge.title = "";
                    } else {
                        badge.className = "req-status badge badge-amber";
                        badge.textContent = "Unavailable";
                        badge.title = act.disabled_reason || "Unavailable";
                    }
                }
            }
        });
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
        renderMonitor(activeRun);
    }

    // Auto Navigation to Samapti Summary upon Run Completion
    const summary = appState.terminal_summary;
    if (summary) {
        renderSummary(summary);
        if (state.lastAutoNavigatedRunId !== summary.run_id && state.currentScreen === "monitor") {
            state.lastAutoNavigatedRunId = summary.run_id;
            switchScreen("summary");
        }
    }

    // Live Inspector updates if currently viewing Nirikshana
    if (state.currentScreen === "inspector" && state.activeRunId) {
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
            if (elements.docPreviewDialog && elements.docPreviewDialog.open) {
                elements.docPreviewDialog.close();
            }
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

    // Preview close button
    if (elements.btnClosePreview && elements.docPreviewDialog) {
        elements.btnClosePreview.addEventListener("click", () => {
            if (typeof elements.docPreviewDialog.close === "function") {
                elements.docPreviewDialog.close();
            }
        });
    }

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
