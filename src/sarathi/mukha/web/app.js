/**
 * Sarathi V2 — Mukha Web Application Controller (Vanilla JS)
 * Drives 5-screen navigation, native Windows picker triggers, typed presentation state polling,
 * run lifecycle dispatch, cancellation, and confirmed artifact downloads.
 */

(function () {
    "use strict";

    // Application State
    const state = {
        currentScreen: "home",
        selectedPaths: [],
        currentRequirement: "read_native",
        currentProfile: "instant",
        isRecursive: true,
        activeRunId: null,
        activeRunStatus: "idle",
        lastState: null,
        pollIntervalMs: 500,
        pollTimer: null,
    };

    // DOM Elements
    const elements = {
        navTabs: document.querySelectorAll(".nav-tab"),
        screens: document.querySelectorAll(".screen-view"),
        systemStatusDot: document.getElementById("system-status-dot"),
        systemStatusText: document.getElementById("system-status-text"),
        
        // Home Elements
        btnBrowseFiles: document.getElementById("btn-browse-files"),
        btnBrowseFolder: document.getElementById("btn-browse-folder"),
        btnClearInputs: document.getElementById("btn-clear-inputs"),
        inputManualPath: document.getElementById("input-manual-path"),
        btnAddManualPath: document.getElementById("btn-add-manual-path"),
        chkRecursive: document.getElementById("chk-recursive"),
        selectedInputsTbody: document.getElementById("selected-inputs-tbody"),
        inputCountsBadge: document.getElementById("input-counts-badge"),
        reqCards: document.querySelectorAll(".req-card"),
        selectProfile: document.getElementById("select-profile"),
        preflightSummary: document.getElementById("preflight-summary"),
        preflightIssues: document.getElementById("preflight-issues"),
        btnStartRun: document.getElementById("btn-start-run"),
        
        // Monitor Elements
        monitorRunId: document.getElementById("monitor-run-id"),
        monitorStatusBadge: document.getElementById("monitor-status-badge"),
        monitorElapsedTime: document.getElementById("monitor-elapsed-time"),
        monitorProgressBar: document.getElementById("monitor-progress-bar"),
        btnCancelRun: document.getElementById("btn-cancel-run"),
        longRunningAlert: document.getElementById("long-running-alert"),
        longRunningDesc: document.getElementById("long-running-desc"),
        focusStageName: document.getElementById("focus-stage-name"),
        focusFileName: document.getElementById("focus-file-name"),
        focusDeviceType: document.getElementById("focus-device-type"),
        focusDuration: document.getElementById("focus-duration"),
        deviceThroughputTbody: document.getElementById("device-throughput-tbody"),
        pipelineCounts: document.getElementById("pipeline-counts"),
        filePipelineTbody: document.getElementById("file-pipeline-tbody"),

        // Review Elements
        reviewBadge: document.getElementById("review-badge"),
        reviewQueueCount: document.getElementById("review-queue-count"),
        reviewQueueTbody: document.getElementById("review-queue-tbody"),

        // Summary Elements
        summaryHero: document.getElementById("summary-hero"),
        summaryStatusBadge: document.getElementById("summary-status-badge"),
        summaryTitle: document.getElementById("summary-title"),
        summaryRunMeta: document.getElementById("summary-run-meta"),
        summaryFailureReason: document.getElementById("summary-failure-reason"),
        btnOpenOutputFolder: document.getElementById("btn-open-output-folder"),
        btnReturnHome: document.getElementById("btn-return-home"),
        statTotalFiles: document.getElementById("stat-total-files"),
        statSuccessFiles: document.getElementById("stat-success-files"),
        statWarningFiles: document.getElementById("stat-warning-files"),
        statFailedFiles: document.getElementById("stat-failed-files"),
        artifactsGrid: document.getElementById("artifacts-grid"),
        summaryStagesTbody: document.getElementById("summary-stages-tbody"),

        // Inspector Elements
        inspectorDeviceTbody: document.getElementById("inspector-device-tbody"),
        inspectorLogs: document.getElementById("inspector-logs"),

        // Overlay
        aarambhaOverlay: document.getElementById("aarambha-overlay"),
        aarambhaStage: document.getElementById("aarambha-stage"),
    };

    // Helper: Format Bytes
    function formatBytes(bytes) {
        if (!bytes || bytes === 0) return "0 B";
        const k = 1024;
        const sizes = ["B", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
    }

    // Helper: Format Duration (nanoseconds to human string)
    function formatDuration(ns) {
        if (ns == null || ns === 0) return "0.0s";
        const ms = ns / 1_000_000;
        if (ms < 1000) return `${ms.toFixed(0)}ms`;
        const sec = ms / 1000;
        if (sec < 60) return `${sec.toFixed(1)}s`;
        const min = Math.floor(sec / 60);
        const remSec = (sec % 60).toFixed(0);
        return `${min}m ${remSec}s`;
    }

    // Navigation Switcher
    function switchScreen(screenName) {
        state.currentScreen = screenName;
        elements.navTabs.forEach((tab) => {
            tab.classList.toggle("active", tab.dataset.screen === screenName);
        });
        elements.screens.forEach((view) => {
            view.classList.toggle("active", view.id === `screen-${screenName}`);
        });
    }

    // Setup Global Keyboard Shortcuts (F1 - F5)
    function setupKeyboardShortcuts() {
        window.addEventListener("keydown", (e) => {
            const keyMap = {
                F1: "home",
                F2: "monitor",
                F3: "review",
                F4: "summary",
                F5: "inspector",
            };
            if (keyMap[e.key]) {
                e.preventDefault();
                switchScreen(keyMap[e.key]);
            }
        });
    }

    // API Calls
    async function apiPost(url, data = {}) {
        try {
            const res = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
            });
            return await res.json();
        } catch (err) {
            console.error(`API POST failed for ${url}:`, err);
            return { ok: false, error: err.message };
        }
    }

    async function apiGet(url) {
        try {
            const res = await fetch(url);
            return await res.json();
        } catch (err) {
            console.error(`API GET failed for ${url}:`, err);
            return { ok: false, error: err.message };
        }
    }

    // Action: Browse Files via Native Dialog
    async function handleBrowseFiles() {
        elements.btnBrowseFiles.disabled = true;
        const res = await apiPost("/api/browse/files");
        elements.btnBrowseFiles.disabled = false;
        if (res.ok && res.paths && res.paths.length > 0) {
            addSelectedPaths(res.paths);
        } else if (res.error) {
            alert(res.error);
        }
    }

    // Action: Browse Folder via Native Dialog
    async function handleBrowseFolder() {
        elements.btnBrowseFolder.disabled = true;
        const res = await apiPost("/api/browse/folder");
        elements.btnBrowseFolder.disabled = false;
        if (res.ok && res.paths && res.paths.length > 0) {
            addSelectedPaths(res.paths);
        } else if (res.error) {
            alert(res.error);
        }
    }

    // Action: Add Manual Path
    function handleAddManualPath() {
        const val = elements.inputManualPath.value.trim();
        if (val) {
            addSelectedPaths([val]);
            elements.inputManualPath.value = "";
        }
    }

    // Action: Add and Intake Paths
    async function addSelectedPaths(newPaths) {
        const set = new Set([...state.selectedPaths, ...newPaths]);
        state.selectedPaths = Array.from(set);
        await refreshIntake();
    }

    // Action: Clear Selected Inputs
    async function handleClearInputs() {
        state.selectedPaths = [];
        await refreshIntake();
    }

    // Intake & Preflight Refresh
    async function refreshIntake() {
        if (state.selectedPaths.length === 0) {
            renderInputsTable([]);
            renderPreflight({ eligible_count: 0, issue_count: 0, issues: [] });
            elements.btnStartRun.disabled = true;
            elements.inputCountsBadge.textContent = "0 files";
            return;
        }

        const res = await apiPost("/api/intake", {
            paths: state.selectedPaths,
            recursive: state.isRecursive,
        });

        if (res.ok && res.input_selection) {
            renderInputsTable(res.input_selection.items || []);
            elements.inputCountsBadge.textContent = `${res.input_selection.total_files || 0} files (${formatBytes(res.input_selection.total_size_bytes || 0)})`;
            renderPreflight(res.preflight || { eligible_count: 0, issue_count: 0, issues: [] });
            elements.btnStartRun.disabled = (res.preflight?.eligible_count || 0) === 0;
        } else if (res.error) {
            alert(res.error);
        }
    }

    // Render Inputs Table in Griha
    function renderInputsTable(items) {
        if (!items || items.length === 0) {
            elements.selectedInputsTbody.innerHTML = '<tr class="empty-row"><td colspan="3">No documents selected. Click "Add Files" or "Add Folder" to begin.</td></tr>';
            return;
        }

        elements.selectedInputsTbody.innerHTML = items
            .map((item) => {
                const badge = item.is_eligible
                    ? '<span class="badge badge-emerald">Eligible</span>'
                    : `<span class="badge badge-amber" title="${item.issue_reason || 'Ineligible'}">Issue</span>`;
                return `<tr>
                    <td><strong>${escapeHtml(item.display_name)}</strong></td>
                    <td>${formatBytes(item.size_bytes)}</td>
                    <td>${badge}</td>
                </tr>`;
            })
            .join("");
    }

    // Render Preflight Summary in Griha
    function renderPreflight(preflight) {
        elements.preflightSummary.textContent = `${preflight.eligible_count} eligible, ${preflight.issue_count} issues`;
        if (preflight.issues && preflight.issues.length > 0) {
            elements.preflightIssues.classList.remove("hidden");
            elements.preflightIssues.innerHTML = preflight.issues
                .map(([name, reason]) => `<div>⚠ <strong>${escapeHtml(name)}</strong>: ${escapeHtml(reason)}</div>`)
                .join("");
        } else {
            elements.preflightIssues.classList.add("hidden");
            elements.preflightIssues.innerHTML = "";
        }
    }

    // Action: Start Processing Run
    async function handleStartRun() {
        if (state.selectedPaths.length === 0) return;

        elements.btnStartRun.disabled = true;
        const res = await apiPost("/api/runs", {
            paths: state.selectedPaths,
            requirement: state.currentRequirement,
            profile: state.currentProfile,
            recursive: state.isRecursive,
        });

        if (res.ok && res.run_id) {
            state.activeRunId = res.run_id;
            state.activeRunStatus = "RUNNING";
            switchScreen("monitor");
            pollState();
        } else {
            alert(res.error || "Failed to start document processing.");
            elements.btnStartRun.disabled = false;
        }
    }

    // Action: Cancel Active Run
    async function handleCancelRun() {
        if (!state.activeRunId) return;
        elements.btnCancelRun.disabled = true;
        await apiPost(`/api/runs/${state.activeRunId}/cancel`);
    }

    // Action: Open Output Folder
    async function handleOpenOutputFolder() {
        if (!state.activeRunId) return;
        await apiPost(`/api/runs/${state.activeRunId}/reveal`);
    }

    // State Polling Loop
    async function pollState() {
        const res = await apiGet("/api/state");
        if (res.ok && res.state) {
            state.lastState = res.state;
            updatePresentation(res.state);
        }

        // Adjust polling frequency: fast when run is active, steady when idle
        clearTimeout(state.pollTimer);
        const interval = state.activeRunStatus === "RUNNING" ? 400 : 1500;
        state.pollTimer = setTimeout(pollState, interval);
    }

    // Update Presentation from View State Projection
    function updatePresentation(appState) {
        if (!appState) return;

        // 0. Update Processing Requirements from Available Actions Facts
        if (appState.available_actions && appState.available_actions.length > 0) {
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

        // 1. Aarambha Startup Overlay
        if (appState.startup && appState.startup.is_initializing && appState.startup.elapsed_ns > 5_000_000_000) {
            elements.aarambhaOverlay.classList.remove("hidden");
            elements.aarambhaStage.textContent = appState.startup.current_stage || "Initializing...";
        } else {
            elements.aarambhaOverlay.classList.add("hidden");
        }

        // 2. Pravritti Monitor Updates
        const activeRun = appState.active_run;
        if (activeRun) {
            state.activeRunId = activeRun.run_id;
            state.activeRunStatus = activeRun.status;
            elements.monitorRunId.textContent = activeRun.run_id;
            elements.monitorStatusBadge.textContent = activeRun.status;
            elements.monitorElapsedTime.textContent = formatDuration(activeRun.elapsed_ns);
            elements.btnCancelRun.disabled = activeRun.status !== "RUNNING";

            // Progress Bar
            const total = activeRun.total_files || 1;
            const done = activeRun.terminal_files || 0;
            const pct = Math.min(100, Math.round((done / total) * 100));
            elements.monitorProgressBar.style.width = `${pct}%`;

            // Focus Stage
            if (activeRun.current_focus) {
                elements.focusStageName.textContent = activeRun.current_focus.stage || "—";
                elements.focusFileName.textContent = activeRun.current_focus.operation_name || "—";
                elements.focusDeviceType.textContent = activeRun.current_focus.device_type || "CPU";
                elements.focusDuration.textContent = formatDuration(activeRun.current_focus.elapsed_ns);
            }

            // Long-running Alert (>5s)
            if (activeRun.long_running && activeRun.long_running.length > 0) {
                elements.longRunningAlert.classList.remove("hidden");
                elements.longRunningDesc.textContent = activeRun.long_running
                    .map((lr) => `${lr.operation_name} (${formatDuration(lr.elapsed_ns)})`)
                    .join(", ");
            } else {
                elements.longRunningAlert.classList.add("hidden");
            }

            // Device Throughput Table
            if (activeRun.device_progress && activeRun.device_progress.length > 0) {
                elements.deviceThroughputTbody.innerHTML = activeRun.device_progress
                    .map((dp) => `<tr>
                        <td><strong>${escapeHtml(dp.device_type)}</strong></td>
                        <td>${dp.execution_count} units</td>
                        <td>${formatDuration(dp.total_duration_ns)}</td>
                        <td>${formatDuration(dp.avg_duration_ns)}</td>
                    </tr>`)
                    .join("");
            }

            // Document Pipeline Table
            if (activeRun.files && activeRun.files.length > 0) {
                elements.pipelineCounts.textContent = `${activeRun.terminal_files} / ${activeRun.total_files} completed`;
                elements.filePipelineTbody.innerHTML = activeRun.files
                    .map((f) => {
                        const statusBadge = f.status === "completed"
                            ? '<span class="badge badge-emerald">Done</span>'
                            : f.status === "running"
                            ? '<span class="badge badge-indigo">Running</span>'
                            : `<span class="badge">${f.status}</span>`;
                        return `<tr>
                            <td>${f.ordinal + 1}</td>
                            <td><strong>${escapeHtml(f.display_name)}</strong></td>
                            <td>${escapeHtml(f.current_stage || "—")}</td>
                            <td>${statusBadge}</td>
                            <td>${formatDuration(f.elapsed_ns)}</td>
                            <td>${f.warning_count > 0 ? `<span class="badge badge-amber">${f.warning_count}</span>` : "—"}</td>
                        </tr>`;
                    })
                    .join("");
            }

            // Auto-transition to summary upon completion
            if (activeRun.status !== "RUNNING" && state.currentScreen === "monitor" && appState.terminal_summary) {
                switchScreen("summary");
            }
        }

        // 3. Pariksha Review Queue
        const reviewItems = appState.review_queue || [];
        if (reviewItems.length > 0) {
            elements.reviewBadge.classList.remove("hidden");
            elements.reviewBadge.textContent = reviewItems.length;
            elements.reviewQueueCount.textContent = `${reviewItems.length} items`;
            elements.reviewQueueTbody.innerHTML = reviewItems
                .map((it) => `<tr>
                    <td><code>${escapeHtml(it.item_id)}</code></td>
                    <td>${escapeHtml(it.file_display_name)}</td>
                    <td>${escapeHtml(it.stage)}</td>
                    <td>${it.confidence ? (it.confidence * 100).toFixed(1) + "%" : "—"}</td>
                    <td><span class="text-amber">${escapeHtml(it.issue_reason)}</span></td>
                    <td><button class="btn btn-outline btn-sm">Inspect</button></td>
                </tr>`)
                .join("");
        } else {
            elements.reviewBadge.classList.add("hidden");
            elements.reviewQueueCount.textContent = "0 items";
            elements.reviewQueueTbody.innerHTML = '<tr class="empty-row"><td colspan="6">No items currently require human review.</td></tr>';
        }

        // 4. Samapti Terminal Summary
        const summary = appState.terminal_summary;
        if (summary) {
            elements.summaryStatusBadge.textContent = summary.status;
            elements.summaryTitle.textContent = `Run Completed (${summary.status})`;
            elements.summaryRunMeta.textContent = `Run ID: ${summary.run_id} | Total Time: ${formatDuration(summary.wall_time_ns)}`;

            if (elements.summaryFailureReason) {
                if (summary.failures && summary.failures.length > 0) {
                    elements.summaryFailureReason.classList.remove("hidden");
                    elements.summaryFailureReason.textContent = summary.failures.join(" | ");
                } else {
                    elements.summaryFailureReason.classList.add("hidden");
                    elements.summaryFailureReason.textContent = "";
                }
            }

            elements.summaryHero.className = `summary-hero status-${summary.status.toLowerCase()}`;
            elements.statTotalFiles.textContent = summary.total_inputs;
            elements.statSuccessFiles.textContent = summary.successful_files != null ? summary.successful_files : "—";
            elements.statWarningFiles.textContent = summary.warning_files != null ? summary.warning_files : "—";
            elements.statFailedFiles.textContent = summary.failed_files != null ? summary.failed_files : (summary.status === "FAILED" ? summary.total_inputs : "—");

            // Confirmed Artifacts Cards
            if (summary.artifacts && summary.artifacts.length > 0) {
                elements.artifactsGrid.innerHTML = summary.artifacts
                    .map((art) => `
                        <div class="artifact-card">
                            <span class="badge badge-emerald">${escapeHtml(art.role)}</span>
                            <div class="artifact-title">${escapeHtml(art.display_name)}</div>
                            <div class="artifact-meta">
                                <span>${formatBytes(art.size_bytes)}</span>
                                <a href="/api/runs/${summary.run_id}/artifacts/${encodeURIComponent(art.artifact_id)}" class="btn btn-primary btn-sm" download>📥 Download</a>
                            </div>
                        </div>
                    `)
                    .join("");
            } else {
                elements.artifactsGrid.innerHTML = '<div class="empty-card">No output artifacts generated.</div>';
            }

            // Summary Stages Table
            if (summary.stage_timings && summary.stage_timings.length > 0) {
                elements.summaryStagesTbody.innerHTML = summary.stage_timings
                    .map((st) => `<tr>
                        <td><strong>${escapeHtml(st.stage_name)}</strong></td>
                        <td>${st.call_count}</td>
                        <td>${formatDuration(st.duration_ns)}</td>
                        <td>${formatDuration(st.call_count > 0 ? Math.round(st.duration_ns / st.call_count) : 0)}</td>
                    </tr>`)
                    .join("");
            }
        }

        // 5. Nirikshana Inspector
        const inspector = appState.inspector;
        if (inspector) {
            if (inspector.device_summaries && inspector.device_summaries.length > 0) {
                elements.inspectorDeviceTbody.innerHTML = inspector.device_summaries
                    .map((ds) => `<tr>
                        <td><strong>${escapeHtml(ds.device_type)}</strong></td>
                        <td>${ds.execution_count}</td>
                        <td>${formatDuration(ds.avg_duration_ns)}</td>
                        <td>${formatDuration(ds.p95_duration_ns)}</td>
                    </tr>`)
                    .join("");
            }
            if (inspector.activity_logs && inspector.activity_logs.length > 0) {
                elements.inspectorLogs.innerHTML = inspector.activity_logs
                    .map(([ts, comp, phase, msg]) => `<div class="log-entry"><span class="text-muted">[${ts}]</span> <strong>${escapeHtml(comp)}</strong>.${escapeHtml(phase)}: ${escapeHtml(msg)}</div>`)
                    .join("");
            }
        }
    }

    // Helper: HTML Escaping
    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Initialize Event Listeners
    function init() {
        setupKeyboardShortcuts();

        // Nav tabs
        elements.navTabs.forEach((tab) => {
            tab.addEventListener("click", () => switchScreen(tab.dataset.screen));
        });

        // File Selection Buttons
        elements.btnBrowseFiles.addEventListener("click", handleBrowseFiles);
        elements.btnBrowseFolder.addEventListener("click", handleBrowseFolder);
        elements.btnClearInputs.addEventListener("click", handleClearInputs);
        elements.btnAddManualPath.addEventListener("click", handleAddManualPath);
        elements.inputManualPath.addEventListener("keydown", (e) => {
            if (e.key === "Enter") handleAddManualPath();
        });
        elements.chkRecursive.addEventListener("change", (e) => {
            state.isRecursive = e.target.checked;
            refreshIntake();
        });

        // Requirement Cards
        elements.reqCards.forEach((card) => {
            card.addEventListener("click", () => {
                elements.reqCards.forEach((c) => c.classList.remove("active"));
                card.classList.add("active");
                state.currentRequirement = card.dataset.req;
            });
        });

        // Profile Selector
        elements.selectProfile.addEventListener("change", (e) => {
            state.currentProfile = e.target.value;
        });

        // Run Actions
        elements.btnStartRun.addEventListener("click", handleStartRun);
        elements.btnCancelRun.addEventListener("click", handleCancelRun);
        elements.btnOpenOutputFolder.addEventListener("click", handleOpenOutputFolder);
        elements.btnReturnHome.addEventListener("click", () => switchScreen("home"));

        // Begin Initial State Polling
        pollState();
    }

    // Start on DOM Ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
