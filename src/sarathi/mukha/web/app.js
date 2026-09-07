/**
 * Sarathi V2 — Mukha Web Application Controller (Vanilla JS)
 * Drives 5-screen navigation, native Windows picker triggers, typed presentation state,
 * real-time SSE stream processing, document preview, and interactive run inspection.
 */

(function () {
    "use strict";

    // Application State
    const state = {
        currentScreen: "home",
        selectedRoots: [],
        selectedPaths: [],
        excludedPaths: new Set(),
        currentRequirement: "read_native",
        currentProfile: "instant",
        isRecursive: true,
        activeRunId: null,
        activeRunStatus: "idle",
        lastAutoNavigatedRunId: null,
        lastState: null,
        pollIntervalMs: 500,
        pollTimer: null,
        checkedInputPaths: new Set(),
        intakeItems: [],
        sseSource: null,
        sseActive: false,
        activeInspectorTab: "activity",
        logFilterLevel: "ALL",
        logSearchQuery: "",
        allActivityLogs: [],
        selectedReviewItem: null,
        imageZoomLevel: 1.0,
        regionSearchQuery: "",
        allRegionConfidence: [],
    };

    // DOM Elements Mapping
    const elements = {
        navTabs: document.querySelectorAll(".nav-tab"),
        screens: document.querySelectorAll(".screen-view"),
        systemStatusDot: document.getElementById("system-status-dot"),
        systemStatusText: document.getElementById("system-status-text"),
        sseStatusBadge: document.getElementById("sse-status-badge"),
        sseStatusLabel: document.getElementById("sse-status-label"),
        btnOpenHistory: document.getElementById("btn-open-history"),
        btnCommandPalette: document.getElementById("btn-command-palette"),
        
        // Home Elements
        btnBrowseFiles: document.getElementById("btn-browse-files"),
        btnBrowseFolder: document.getElementById("btn-browse-folder"),
        btnClearSelected: document.getElementById("btn-clear-selected"),
        btnClearInputs: document.getElementById("btn-clear-inputs"),
        inputManualPath: document.getElementById("input-manual-path"),
        btnAddManualPath: document.getElementById("btn-add-manual-path"),
        chkRecursive: document.getElementById("chk-recursive"),
        chkSelectAllInputs: document.getElementById("chk-select-all-inputs"),
        selectedInputsTbody: document.getElementById("selected-inputs-tbody"),
        inputGroupsContainer: document.getElementById("input-groups-container"),
        inputCountsBadge: document.getElementById("input-counts-badge"),
        reqCards: document.querySelectorAll(".req-card"),
        profileRow: document.getElementById("profile-row"),
        selectProfile: document.getElementById("select-profile"),
        ocrLangRow: document.getElementById("ocr-lang-row"),
        selectOcrLang: document.getElementById("select-ocr-lang"),
        ocrCustomControls: document.getElementById("ocr-custom-controls"),
        chkOcrPreprocess: document.getElementById("chk-ocr-preprocess"),
        chkOcrDeskew: document.getElementById("chk-ocr-deskew"),
        chkOcrClahe: document.getElementById("chk-ocr-clahe"),
        chkOcrBinarize: document.getElementById("chk-ocr-binarize"),
        chkOcrFallback: document.getElementById("chk-ocr-fallback"),
        chkOcrValidation: document.getElementById("chk-ocr-validation"),
        fontModeRow: document.getElementById("font-mode-row"),
        selectFontSource: document.getElementById("select-font-source"),
        selectFontMode: document.getElementById("select-font-mode"),
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
        activeWorkersCount: document.getElementById("active-workers-count"),
        activeWorkersTbody: document.getElementById("active-workers-tbody"),
        pipelineCounts: document.getElementById("pipeline-counts"),
        filePipelineTbody: document.getElementById("file-pipeline-tbody"),

        // Review Elements
        reviewBadge: document.getElementById("review-badge"),
        reviewQueueCount: document.getElementById("review-queue-count"),
        reviewQueueTbody: document.getElementById("review-queue-tbody"),
        reviewDetailCard: document.getElementById("review-detail-card"),
        reviewActiveItemTitle: document.getElementById("review-active-item-title"),
        reviewSourceText: document.getElementById("review-source-text"),
        reviewOutputText: document.getElementById("review-output-text"),
        reviewConfidenceFill: document.getElementById("review-confidence-fill"),
        reviewConfidenceText: document.getElementById("review-confidence-text"),
        btnReviewAccept: document.getElementById("btn-review-accept"),
        btnReviewEdit: document.getElementById("btn-review-edit"),
        btnReviewDismiss: document.getElementById("btn-review-dismiss"),

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
        inspectorTabs: document.querySelectorAll(".inspector-tab"),
        inspectorTabContents: document.querySelectorAll(".inspector-tab-content"),
        inputLogSearch: document.getElementById("input-log-search"),
        logPills: document.querySelectorAll(".log-pill"),
        btnCopyLogs: document.getElementById("btn-copy-logs"),
        inspectorLogs: document.getElementById("inspector-logs"),
        inspectorDeviceTbody: document.getElementById("inspector-device-tbody"),
        inspectorStagesTbody: document.getElementById("inspector-stages-tbody"),
        inspectorWorkerTbody: document.getElementById("inspector-worker-tbody"),
        inspectorPageConfTbody: document.getElementById("inspector-page-conf-tbody"),
        inspectorRegionConfTbody: document.getElementById("inspector-region-conf-tbody"),
        inspectorRegionFilter: document.getElementById("inspector-region-filter"),
        statConfHigh: document.getElementById("stat-conf-high"),
        statConfMid: document.getElementById("stat-conf-mid"),
        statConfLow: document.getElementById("stat-conf-low"),
        statConfCrit: document.getElementById("stat-conf-crit"),
        systemFactsTbody: document.getElementById("system-facts-tbody"),

        // Document Preview Dialog
        docPreviewDialog: document.getElementById("doc-preview-dialog"),
        previewModalTitle: document.getElementById("preview-modal-title"),
        previewModalContent: document.getElementById("preview-modal-content"),
        btnClosePreview: document.getElementById("btn-close-preview"),

        // History Drawer
        historyDrawer: document.getElementById("history-drawer"),
        historyListContainer: document.getElementById("history-list-container"),
        btnCloseHistory: document.getElementById("btn-close-history"),

        // Overlay
        aarambhaOverlay: document.getElementById("aarambha-overlay"),
        aarambhaStage: document.getElementById("aarambha-stage"),

        // Alert Banner & Dialog Elements
        errorBanner: document.getElementById("error-banner"),
        errorBannerText: document.getElementById("error-banner-text"),
        btnDismissError: document.getElementById("btn-dismiss-error"),
        cancelRunDialog: document.getElementById("cancel-run-dialog"),
        btnCancelDialogConfirm: document.getElementById("btn-cancel-dialog-confirm"),
        btnCancelDialogDismiss: document.getElementById("btn-cancel-dialog-dismiss"),
    };

    // Helper: Error Notification Banner
    function showError(msg) {
        if (!elements.errorBanner || !elements.errorBannerText) return;
        elements.errorBannerText.textContent = msg;
        elements.errorBanner.classList.remove("hidden");
    }

    function hideError() {
        if (elements.errorBanner) {
            elements.errorBanner.classList.add("hidden");
        }
    }

    // Helper: Format Bytes
    function formatBytes(bytes) {
        if (!bytes || bytes === 0) return "0 B";
        const k = 1024;
        const sizes = ["B", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
    }

    // Helper: Format Nanosecond Durations
    function formatDuration(ns) {
        if (ns === null || ns === undefined || isNaN(ns)) return "—";
        const sec = ns / 1_000_000_000;
        if (sec < 0.001) return "<1ms";
        if (sec < 1.0) return `${(sec * 1000).toFixed(0)}ms`;
        if (sec < 60.0) return `${sec.toFixed(1)}s`;
        const m = Math.floor(sec / 60);
        const s = (sec % 60).toFixed(1);
        return `${m}m ${s}s`;
    }

    // API Helpers
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
        hideError();
        const res = await apiPost("/api/browse/files");
        elements.btnBrowseFiles.disabled = false;
        if (res.ok && res.paths && res.paths.length > 0) {
            addSelectedPaths(res.paths);
        } else if (res.error) {
            showError(res.error);
        }
    }

    // Action: Browse Folder via Native Dialog
    async function handleBrowseFolder() {
        elements.btnBrowseFolder.disabled = true;
        hideError();
        const res = await apiPost("/api/browse/folder");
        elements.btnBrowseFolder.disabled = false;
        if (res.ok && res.paths && res.paths.length > 0) {
            addSelectedPaths(res.paths);
        } else if (res.error) {
            showError(res.error);
        }
    }

    // Action: Add Manual Path
    function handleAddManualPath() {
        const val = elements.inputManualPath.value.trim();
        if (val) {
            hideError();
            addSelectedPaths([val]);
            elements.inputManualPath.value = "";
        }
    }

    // Action: Add and Intake Paths
    async function addSelectedPaths(newPaths) {
        const set = new Set([...state.selectedRoots, ...newPaths]);
        state.selectedRoots = Array.from(set);
        await refreshIntake();
    }

    function updateClearSelectedButton() {
        if (!elements.btnClearSelected) return;
        const count = state.checkedInputPaths.size;
        elements.btnClearSelected.disabled = count === 0;
        elements.btnClearSelected.textContent = count > 0 ? `Clear Selected (${count})` : "Clear Selected";
    }

    function removePaths(pathsToRemove) {
        const toRemoveSet = new Set(pathsToRemove);
        state.selectedRoots = state.selectedRoots.filter((p) => !toRemoveSet.has(p));
        pathsToRemove.forEach((p) => {
            state.excludedPaths.add(p);
            state.checkedInputPaths.delete(p);
        });
        updateClearSelectedButton();
        refreshIntake();
    }

    async function handleClearSelected() {
        if (state.checkedInputPaths.size === 0) return;
        removePaths(Array.from(state.checkedInputPaths));
    }

    async function handleClearInputs() {
        state.selectedRoots = [];
        state.selectedPaths = [];
        state.excludedPaths.clear();
        state.checkedInputPaths.clear();
        state.intakeItems = [];
        updateClearSelectedButton();
        if (elements.chkSelectAllInputs) elements.chkSelectAllInputs.checked = false;
        await refreshIntake();
    }

    // Intake & Preflight Refresh
    async function refreshIntake() {
        if (state.selectedRoots.length === 0) {
            state.selectedPaths = [];
            state.intakeItems = [];
            renderInputsTable([]);
            renderPreflight({ eligible_count: 0, issue_count: 0, issues: [] });
            elements.btnStartRun.disabled = true;
            elements.inputCountsBadge.textContent = "0 files";
            return;
        }

        const res = await apiPost("/api/intake", {
            paths: state.selectedRoots,
            recursive: state.isRecursive,
        });

        if (res.ok && res.input_selection) {
            const rawItems = res.input_selection.items || [];
            const filteredItems = rawItems.filter((i) => !state.excludedPaths.has(i.source_path || i.display_name));
            state.intakeItems = filteredItems;
            state.selectedPaths = filteredItems.map((i) => i.source_path || i.display_name);

            renderInputsTable(filteredItems, res.input_selection);
            const totalSize = filteredItems.reduce((acc, it) => acc + (it.size_bytes || 0), 0);
            elements.inputCountsBadge.textContent = `${filteredItems.length} files (${formatBytes(totalSize)})`;
            renderPreflight(res.preflight || { eligible_count: filteredItems.length, issue_count: 0, issues: [] });
            elements.btnStartRun.disabled = filteredItems.length === 0;
        } else if (res.error) {
            showError(res.error);
        }
    }

    // Render Inputs Table with Quick Preview Triggers
    function renderInputsTable(items, inputSelection) {
        state.intakeItems = items || [];

        if (elements.inputGroupsContainer) {
            if (inputSelection && inputSelection.groups && inputSelection.groups.length > 0) {
                elements.inputGroupsContainer.classList.remove("hidden");
                elements.inputGroupsContainer.innerHTML = inputSelection.groups
                    .map((g) => `<div class="badge badge-indigo" style="padding: 4px 10px;"><strong>${escapeHtml(g.format_name)}</strong>: ${g.file_count} files (${formatBytes(g.total_size_bytes)})</div>`)
                    .join(" ");
            } else {
                elements.inputGroupsContainer.classList.add("hidden");
                elements.inputGroupsContainer.innerHTML = "";
            }
        }

        if (!items || items.length === 0) {
            elements.selectedInputsTbody.innerHTML = '<tr class="empty-row"><td colspan="5">No documents selected. Click "Add Files" or "Add Folder" to begin.</td></tr>';
            state.checkedInputPaths.clear();
            updateClearSelectedButton();
            if (elements.chkSelectAllInputs) elements.chkSelectAllInputs.checked = false;
            return;
        }

        const MAX_RENDER_INPUTS = 100;
        const itemsToRender = items.length > MAX_RENDER_INPUTS ? items.slice(0, MAX_RENDER_INPUTS) : items;

        let rowsHtml = itemsToRender
            .map((item) => {
                const pathVal = item.source_path || item.display_name;
                const isChecked = state.checkedInputPaths.has(pathVal);
                const badge = item.is_eligible
                    ? '<span class="badge badge-emerald">Eligible</span>'
                    : `<span class="badge badge-amber" title="${item.issue_reason || 'Ineligible'}">Issue</span>`;
                return `<tr>
                    <td style="text-align: center;">
                        <input type="checkbox" class="input-row-chk" data-path="${escapeHtml(pathVal)}" ${isChecked ? "checked" : ""}>
                    </td>
                    <td><strong>${escapeHtml(item.display_name)}</strong></td>
                    <td>${formatBytes(item.size_bytes)}</td>
                    <td>${badge}</td>
                    <td style="text-align: center;">
                        <button class="btn btn-outline btn-sm btn-preview-file" data-path="${escapeHtml(pathVal)}" title="Preview Document">👁️</button>
                        <button class="btn btn-outline btn-sm btn-remove-row" data-path="${escapeHtml(pathVal)}" title="Remove" style="color: var(--accent-crimson); margin-left: 4px;">✕</button>
                    </td>
                </tr>`;
            })
            .join("");

        if (items.length > MAX_RENDER_INPUTS) {
            rowsHtml += `<tr class="empty-row"><td colspan="5">Showing first ${MAX_RENDER_INPUTS} of ${items.length} documents.</td></tr>`;
        }

        elements.selectedInputsTbody.innerHTML = rowsHtml;
        updateClearSelectedButton();
        if (elements.chkSelectAllInputs) {
            elements.chkSelectAllInputs.checked = items.length > 0 && items.every((i) => state.checkedInputPaths.has(i.source_path || i.display_name));
        }
    }

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
        hideError();
        const profileToSend = state.currentRequirement === "ocr" ? state.currentProfile : "instant";
        const payload = {
            paths: state.selectedPaths,
            requirement: state.currentRequirement,
            profile: profileToSend,
            recursive: state.isRecursive,
        };
        if (state.currentRequirement === "ocr") {
            const customOpts = {};
            if (elements.selectOcrLang) customOpts.lang = elements.selectOcrLang.value;
            if (state.currentProfile === "custom") {
                customOpts.engine = "rapidocr";
                if (elements.chkOcrPreprocess) customOpts.preprocess = elements.chkOcrPreprocess.checked;
                if (elements.chkOcrDeskew) customOpts.deskew = elements.chkOcrDeskew.checked;
                if (elements.chkOcrClahe) customOpts.clahe = elements.chkOcrClahe.checked;
                if (elements.chkOcrBinarize) customOpts.binarize = elements.chkOcrBinarize.checked;
                if (elements.chkOcrFallback) customOpts.fallback_enabled = elements.chkOcrFallback.checked;
                if (elements.chkOcrValidation) customOpts.validation_enabled = elements.chkOcrValidation.checked;
            }
            payload.custom_options = customOpts;
        } else if (state.currentRequirement === "font_conversion" && elements.selectFontMode) {
            const fontOpts = { font_mode: elements.selectFontMode.value };
            if (elements.selectFontSource && elements.selectFontSource.value) {
                fontOpts.source_font = elements.selectFontSource.value;
            }
            payload.custom_options = fontOpts;
        }

        const res = await apiPost("/api/runs", payload);

        if (res.ok && res.run_id) {
            state.activeRunId = res.run_id;
            state.activeRunStatus = "RUNNING";
            state.lastAutoNavigatedRunId = null;
            if (elements.focusStageName) elements.focusStageName.textContent = "—";
            if (elements.focusFileName) elements.focusFileName.textContent = "—";
            if (elements.focusDeviceType) elements.focusDeviceType.textContent = "—";
            if (elements.focusDuration) elements.focusDuration.textContent = "0.0s";
            switchScreen("monitor");
            pollState();
        } else {
            showError(res.error || "Failed to start document processing.");
            elements.btnStartRun.disabled = false;
        }
    }

    function handleCancelRun() {
        if (!state.activeRunId || state.activeRunStatus !== "RUNNING") return;
        if (elements.cancelRunDialog && typeof elements.cancelRunDialog.showModal === "function") {
            elements.cancelRunDialog.showModal();
        } else {
            if (confirm("Are you sure you want to cancel the active document processing run?")) {
                dispatchCancelRun();
            }
        }
    }

    async function dispatchCancelRun() {
        if (!state.activeRunId) return;
        elements.btnCancelRun.disabled = true;
        const res = await apiPost(`/api/runs/${state.activeRunId}/cancel`);
        if (!res.ok) {
            showError(res.error || "Failed to cancel run.");
            elements.btnCancelRun.disabled = false;
        }
    }

    async function handleOpenOutputFolder() {
        if (!state.activeRunId) return;
        const res = await apiPost(`/api/runs/${state.activeRunId}/reveal`);
        if (!res.ok) {
            showError(res.error || "Failed to reveal output folder.");
        }
    }

    // Screen Switching
    function switchScreen(screenId) {
        state.currentScreen = screenId;
        elements.navTabs.forEach((tab) => {
            tab.classList.toggle("active", tab.dataset.screen === screenId);
        });
        elements.screens.forEach((view) => {
            view.classList.toggle("active", view.id === `screen-${screenId}`);
        });

        if (screenId === "review") loadReviewQueue();
        if (screenId === "inspector") loadInspector();
    }

    // Keyboard Shortcuts (F1-F5, Escape, Ctrl+H, Ctrl+P)
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
                toggleHistoryDrawer();
            } else if (e.key === "Escape") {
                if (elements.docPreviewDialog && elements.docPreviewDialog.open) {
                    elements.docPreviewDialog.close();
                }
                if (elements.historyDrawer && elements.historyDrawer.classList.contains("open")) {
                    toggleHistoryDrawer(false);
                }
            }
        });
    }

    // ==========================================
    // Real-Time Server-Sent Events (SSE) Engine
    // ==========================================
    function initSSE() {
        if (typeof EventSource === "undefined") {
            setSSEBadge(false);
            pollState();
            return;
        }

        try {
            if (state.sseSource) {
                state.sseSource.close();
            }

            const es = new EventSource("/api/events");
            state.sseSource = es;

            es.onopen = () => {
                state.sseActive = true;
                setSSEBadge(true);
            };

            es.addEventListener("state", (e) => {
                try {
                    const data = JSON.parse(e.data);
                    if (data && data.ok && data.state) {
                        updatePresentation(data.state);
                    }
                } catch (err) {
                    console.error("Malformed SSE state payload:", err);
                }
            });

            es.addEventListener("ping", () => {
                // Heartbeat acknowledged
            });

            es.onerror = () => {
                state.sseActive = false;
                setSSEBadge(false);
                es.close();
                state.sseSource = null;
                // Fall back to adaptive polling and retry SSE reconnect after 5s
                pollState();
                setTimeout(initSSE, 5000);
            };
        } catch (err) {
            console.warn("Failed to initialize SSE, using polling:", err);
            setSSEBadge(false);
            pollState();
        }
    }

    function setSSEBadge(isLive) {
        if (!elements.sseStatusBadge || !elements.sseStatusLabel) return;
        if (isLive) {
            elements.sseStatusBadge.className = "sse-badge";
            elements.sseStatusLabel.textContent = "SSE LIVE";
        } else {
            elements.sseStatusBadge.className = "sse-badge polling";
            elements.sseStatusLabel.textContent = "POLLING";
        }
    }

    // Adaptive Polling Fallback
    let lastStateJson = null;
    function getPollInterval() {
        if (document.visibilityState === "hidden") return 3000;
        if (state.activeRunStatus === "RUNNING") return 500;
        return 1500;
    }

    async function pollState() {
        if (state.sseActive) return; // SSE handles active state updates

        const res = await apiGet("/api/state");
        if (res && res.ok && res.state) {
            const currentJson = JSON.stringify(res.state);
            if (currentJson !== lastStateJson) {
                lastStateJson = currentJson;
                state.lastState = res.state;
                updatePresentation(res.state);
            }
        }

        clearTimeout(state.pollTimer);
        state.pollTimer = setTimeout(pollState, getPollInterval());
    }

    // ==========================================
    // Presentation View State Projection
    // ==========================================
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

        // Available Actions Synchronization
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

        // Aarambha Startup Overlay
        if (elements.aarambhaOverlay) {
            if (appState.startup && appState.startup.is_initializing && appState.startup.elapsed_ns > 5_000_000_000) {
                elements.aarambhaOverlay.classList.remove("hidden");
                if (elements.aarambhaStage) elements.aarambhaStage.textContent = appState.startup.current_stage || "Initializing...";
            } else {
                elements.aarambhaOverlay.classList.add("hidden");
            }
        }

        // Pravritti Monitor Updates
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
            let pct = Math.min(100, Math.round((done / total) * 100));
            if (activeRun.status === "RUNNING" && pct < 100 && activeRun.files && activeRun.files.length > 0) {
                for (const f of activeRun.files) {
                    const match = (f.current_stage || "").match(/Page (\d+)\/(\d+)/);
                    if (match) {
                        const curP = parseInt(match[1], 10);
                        const totP = parseInt(match[2], 10);
                        if (totP > 0) {
                            const pageFraction = (curP - 0.5) / totP;
                            const fileBasePct = ((f.ordinal - 1) / total) * 100;
                            const fileSpanPct = (1 / total) * 100;
                            pct = Math.min(95, Math.round(fileBasePct + pageFraction * fileSpanPct));
                            break;
                        }
                    }
                }
            }
            elements.monitorProgressBar.style.width = `${pct}%`;

            // Focus Stage
            if (activeRun.current_focus) {
                elements.focusStageName.textContent = activeRun.current_focus.stage || "—";
                elements.focusFileName.textContent = activeRun.current_focus.operation_name || "—";
                elements.focusDeviceType.textContent = activeRun.current_focus.device_type || "CPU";
                elements.focusDuration.textContent = formatDuration(activeRun.current_focus.elapsed_ns);
            } else {
                elements.focusStageName.textContent = "—";
                elements.focusFileName.textContent = "—";
                elements.focusDeviceType.textContent = "—";
                elements.focusDuration.textContent = "0.0s";
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

            // Active Parallel Workers
            if (activeRun.active_workers && activeRun.active_workers.length > 0) {
                elements.activeWorkersCount.textContent = `${activeRun.active_workers.length} Active`;
                elements.activeWorkersTbody.innerHTML = activeRun.active_workers
                    .map((w) => {
                        const devBadge = (w.device_type === "GPU" || w.device_type === "NPU")
                            ? `<span class="badge badge-emerald">${escapeHtml(w.device_type)}</span>`
                            : `<span class="badge">${escapeHtml(w.device_type || "CPU")}</span>`;
                        const pageText = w.page_number ? `<span class="badge badge-indigo">Page ${w.page_number}</span>` : "—";
                        return `<tr>
                            <td><strong>Worker ${escapeHtml(w.worker_id)}</strong></td>
                            <td>${escapeHtml(w.file_display_name || "—")}</td>
                            <td>${pageText}</td>
                            <td>${escapeHtml(w.stage || "—")}</td>
                            <td>${devBadge}</td>
                            <td><span class="badge badge-indigo">${escapeHtml(w.status || "active")}</span></td>
                        </tr>`;
                    })
                    .join("");
            } else {
                elements.activeWorkersCount.textContent = "0 Active";
                elements.activeWorkersTbody.innerHTML = '<tr class="empty-row"><td colspan="6">No active workers.</td></tr>';
            }

            // Document Execution Pipeline Table
            if (activeRun.files && activeRun.files.length > 0) {
                elements.pipelineCounts.textContent = `${activeRun.terminal_files || 0} / ${activeRun.total_files || activeRun.files.length} completed`;
                elements.filePipelineTbody.innerHTML = activeRun.files
                    .map((f) => {
                        let stBadge = `<span class="badge">${escapeHtml(f.status)}</span>`;
                        if (f.status === "SUCCESS") stBadge = '<span class="badge badge-emerald">SUCCESS</span>';
                        else if (f.status === "RUNNING") stBadge = '<span class="badge badge-indigo">RUNNING</span>';
                        else if (f.status === "FAILED") stBadge = '<span class="badge badge-crimson">FAILED</span>';

                        const warns = f.warning_count > 0 ? `<span class="badge badge-amber">${f.warning_count} warns</span>` : "—";
                        return `<tr>
                            <td>${f.ordinal}</td>
                            <td><strong>${escapeHtml(f.display_name)}</strong></td>
                            <td>${escapeHtml(f.current_stage || "—")}</td>
                            <td>${stBadge}</td>
                            <td>${formatDuration(f.elapsed_ns)}</td>
                            <td>${warns}</td>
                        </tr>`;
                    })
                    .join("");
            }
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

    // Render Terminal Summary in Samapti
    function renderSummary(summary) {
        if (!summary) return;
        state.activeRunId = summary.run_id;

        elements.summaryStatusBadge.textContent = summary.status;
        elements.summaryStatusBadge.className = `badge badge-hero ${
            summary.status === "SUCCESS"
                ? "badge-emerald"
                : summary.status === "PARTIAL"
                ? "badge-amber"
                : "badge-crimson"
        }`;
        elements.summaryHero.className = `summary-hero status-${summary.status.toLowerCase()}`;
        elements.summaryTitle.textContent =
            summary.status === "SUCCESS"
                ? "Run Completed Successfully"
                : summary.status === "PARTIAL"
                ? "Run Completed with Warnings / Partial Extraction"
                : `Run Failed (${summary.status})`;

        elements.summaryRunMeta.textContent = `Run ID: ${summary.run_id} | Total Wall Time: ${formatDuration(summary.wall_time_ns)}`;

        elements.statTotalFiles.textContent = summary.total_inputs || 0;
        elements.statSuccessFiles.textContent = summary.successful_files ?? "—";
        elements.statWarningFiles.textContent = summary.warning_files ?? "—";
        elements.statFailedFiles.textContent = summary.failed_files ?? "—";

        // Output Artifacts Grid with Preview & Download Actions
        if (summary.artifacts && summary.artifacts.length > 0) {
            elements.artifactsGrid.innerHTML = summary.artifacts
                .map((art) => `
                    <div class="artifact-card">
                        <div class="artifact-title">${escapeHtml(art.display_name)}</div>
                        <div class="artifact-meta">
                            <span>Role: <strong>${escapeHtml(art.role)}</strong></span>
                            <span>${formatBytes(art.size_bytes)}</span>
                        </div>
                        <div class="artifact-actions">
                            <button class="btn btn-primary btn-sm btn-preview-artifact" data-run-id="${escapeHtml(summary.run_id)}" data-art-id="${escapeHtml(art.artifact_id)}" data-name="${escapeHtml(art.display_name)}">👁️ Preview</button>
                            <a class="btn btn-outline btn-sm" href="/api/runs/${encodeURIComponent(summary.run_id)}/artifacts/${encodeURIComponent(art.artifact_id)}" download="${escapeHtml(art.display_name)}">⬇ Download</a>
                        </div>
                    </div>
                `)
                .join("");
        } else {
            elements.artifactsGrid.innerHTML = '<div class="empty-card" style="grid-column: 1/-1; text-align: center; padding: 24px; color: var(--text-muted);">No output artifacts generated.</div>';
        }

        // Stage Breakdown Table
        if (summary.stage_timings && summary.stage_timings.length > 0) {
            elements.summaryStagesTbody.innerHTML = summary.stage_timings
                .map((st) => `<tr>
                    <td><strong>${escapeHtml(st.stage_name)}</strong></td>
                    <td>${st.call_count} calls</td>
                    <td>${formatDuration(st.duration_ns)}</td>
                    <td>${formatDuration(st.call_count > 0 ? Math.round(st.duration_ns / st.call_count) : 0)}</td>
                </tr>`)
                .join("");
        }
    }

    // ==========================================
    // Document Preview Controller
    // ==========================================
    async function openDocumentPreview(pathOrUrl, displayName) {
        if (!elements.docPreviewDialog || !elements.previewModalContent) return;
        elements.previewModalTitle.textContent = displayName || "Document Preview";
        elements.previewModalContent.innerHTML = '<div class="spinner"></div>';
        state.imageZoomLevel = 1.0;

        if (typeof elements.docPreviewDialog.showModal === "function") {
            elements.docPreviewDialog.showModal();
        }

        const res = await apiGet(`/api/preview?path=${encodeURIComponent(pathOrUrl)}`);
        if (!res.ok) {
            elements.previewModalContent.innerHTML = `<div class="alert-box alert-amber">${escapeHtml(res.error || "Failed to load document preview.")}</div>`;
            return;
        }

        if (res.type === "tabular") {
            const thead = (res.headers || []).map((h) => `<th>${escapeHtml(h)}</th>`).join("");
            const tbody = (res.rows || [])
                .map((row) => `<tr>${row.map((c) => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`)
                .join("");
            elements.previewModalContent.innerHTML = `
                <div style="margin-bottom: 10px; font-size: 12px; color: var(--text-secondary);">
                    Showing ${res.rows ? res.rows.length : 0} rows (${formatBytes(res.size)})
                </div>
                <div class="table-container" style="max-height: 500px;">
                    <table class="data-table">
                        <thead><tr>${thead}</tr></thead>
                        <tbody>${tbody}</tbody>
                    </table>
                </div>
            `;
        } else if (res.type === "image") {
            elements.previewModalContent.innerHTML = `
                <div class="preview-canvas-container">
                    <img id="preview-img" src="${res.data_url}" alt="Preview" style="transform: scale(1.0);">
                    <div class="preview-zoom-bar">
                        <button id="btn-zoom-in" class="btn btn-secondary btn-sm">➕</button>
                        <button id="btn-zoom-out" class="btn btn-secondary btn-sm">➖</button>
                        <button id="btn-zoom-reset" class="btn btn-secondary btn-sm">Reset</button>
                    </div>
                </div>
            `;
            const img = document.getElementById("preview-img");
            document.getElementById("btn-zoom-in").addEventListener("click", () => {
                state.imageZoomLevel = Math.min(3.0, state.imageZoomLevel + 0.25);
                img.style.transform = `scale(${state.imageZoomLevel})`;
            });
            document.getElementById("btn-zoom-out").addEventListener("click", () => {
                state.imageZoomLevel = Math.max(0.5, state.imageZoomLevel - 0.25);
                img.style.transform = `scale(${state.imageZoomLevel})`;
            });
            document.getElementById("btn-zoom-reset").addEventListener("click", () => {
                state.imageZoomLevel = 1.0;
                img.style.transform = "scale(1.0)";
            });
        } else if (res.type === "text") {
            const lineCount = (res.content || "").split("\n").length;
            elements.previewModalContent.innerHTML = `
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 12px; color: var(--text-secondary);">
                    <span>${lineCount} lines (${formatBytes(res.size)}) ${res.truncated ? "• Preview truncated to 256KB" : ""}</span>
                    <button id="btn-copy-preview-text" class="btn btn-outline btn-sm">📋 Copy Content</button>
                </div>
                <pre style="font-family: var(--font-mono); font-size: 12px; line-height: 1.5; color: #e2e8f0; white-space: pre-wrap; word-break: break-all; background: #04070d; padding: 14px; border-radius: var(--radius-sm); max-height: 500px; overflow-y: auto;"><code>${escapeHtml(res.content)}</code></pre>
            `;
            document.getElementById("btn-copy-preview-text").addEventListener("click", () => {
                navigator.clipboard.writeText(res.content);
            });
        } else if (res.type === "pdf") {
            elements.previewModalContent.innerHTML = `
                <div style="text-align: center; padding: 40px;">
                    <div style="font-size: 48px; margin-bottom: 12px;">📄</div>
                    <h3>${escapeHtml(res.name)}</h3>
                    <p class="text-muted" style="margin-top: 6px;">Portable Document Format (${formatBytes(res.size)})</p>
                </div>
            `;
        } else {
            elements.previewModalContent.innerHTML = `
                <div style="text-align: center; padding: 40px;">
                    <div style="font-size: 48px; margin-bottom: 12px;">📦</div>
                    <h3>${escapeHtml(res.name)}</h3>
                    <p class="text-muted" style="margin-top: 6px;">Binary file (${formatBytes(res.size)})</p>
                </div>
            `;
        }
    }

    // ==========================================
    // Pariksha (Review & Exceptions) Controller
    // ==========================================
    async function loadReviewQueue() {
        const res = await apiGet("/api/review");
        if (!res.ok) return;

        const items = res.items || [];
        elements.reviewQueueCount.textContent = `${items.length} items`;
        if (elements.reviewBadge) {
            elements.reviewBadge.textContent = items.length;
            elements.reviewBadge.classList.toggle("hidden", items.length === 0);
        }

        if (items.length === 0) {
            elements.reviewQueueTbody.innerHTML = '<tr class="empty-row"><td colspan="6">No items currently require human review.</td></tr>';
            if (elements.reviewDetailCard) elements.reviewDetailCard.classList.add("hidden");
            return;
        }

        elements.reviewQueueTbody.innerHTML = items
            .map((it, idx) => `
                <tr class="review-row" data-idx="${idx}" style="cursor: pointer;">
                    <td><strong class="code-text">${escapeHtml(it.item_id || `rev-${idx+1}`)}</strong></td>
                    <td>${escapeHtml(it.context && it.context.file ? it.context.file : "—")}</td>
                    <td><span class="badge badge-indigo">${escapeHtml(it.stage || "—")}</span></td>
                    <td>${it.context && it.context.confidence ? `${(it.context.confidence * 100).toFixed(1)}%` : "—"}</td>
                    <td>${escapeHtml(it.message || it.code || "Review needed")}</td>
                    <td style="text-align: center;">
                        <button class="btn btn-primary btn-sm btn-inspect-review" data-idx="${idx}">Inspect</button>
                    </td>
                </tr>
            `)
            .join("");

        // Select first item by default
        selectReviewItem(items[0]);
    }

    function selectReviewItem(item) {
        if (!item || !elements.reviewDetailCard) return;
        state.selectedReviewItem = item;
        elements.reviewDetailCard.classList.remove("hidden");
        elements.reviewActiveItemTitle.textContent = item.item_id || "Review Item";

        elements.reviewSourceText.textContent = item.context && item.context.source ? item.context.source : "(Source snippet unavailable)";
        elements.reviewOutputText.textContent = item.context && item.context.output ? item.context.output : (item.message || "—");

        const conf = item.context && item.context.confidence !== undefined ? item.context.confidence : 0.75;
        const pct = Math.round(conf * 100);
        elements.reviewConfidenceText.textContent = `${pct}%`;
        elements.reviewConfidenceFill.style.width = `${pct}%`;
        elements.reviewConfidenceFill.style.background = pct >= 90 ? "var(--accent-emerald)" : (pct >= 75 ? "var(--accent-amber)" : "var(--accent-crimson)");
    }

    async function handleReviewAction(action) {
        if (!state.selectedReviewItem) return;
        const itemId = state.selectedReviewItem.item_id;
        const res = await apiPost("/api/review", { item_id: itemId, action: action });
        if (res.ok) {
            loadReviewQueue();
        } else {
            showError(res.error || `Failed to apply review action ${action}`);
        }
    }

    // ==========================================
    // Nirikshana (Inspector) Controller
    // ==========================================
    async function loadInspector() {
        if (!state.activeRunId) {
            elements.inspectorLogs.innerHTML = '<div class="log-entry text-muted">[Ready] No active or recent run to inspect.</div>';
            return;
        }

        const res = await apiGet(`/api/runs/${encodeURIComponent(state.activeRunId)}/inspector`);
        if (!res.ok || !res.inspector) return;

        const insp = res.inspector;

        // Activity Logs
        if (insp.activity_logs && insp.activity_logs.length > 0) {
            state.allActivityLogs = insp.activity_logs;
            renderFilteredLogs();
        }

        // Hardware Device Summary Table
        if (insp.device_summaries && insp.device_summaries.length > 0 && elements.inspectorDeviceTbody) {
            elements.inspectorDeviceTbody.innerHTML = insp.device_summaries
                .map((ds) => `<tr>
                    <td><strong>${escapeHtml(ds.device_type)}</strong></td>
                    <td>${ds.execution_count}</td>
                    <td>${formatDuration(ds.avg_duration_ns)}</td>
                    <td>${formatDuration(ds.p95_duration_ns)}</td>
                </tr>`)
                .join("");
        }

        // Stage Timings
        if (insp.stage_timings && insp.stage_timings.length > 0 && elements.inspectorStagesTbody) {
            elements.inspectorStagesTbody.innerHTML = insp.stage_timings
                .map((st) => `<tr>
                    <td><strong>${escapeHtml(st.stage_name)}</strong></td>
                    <td>${st.call_count}</td>
                    <td>${formatDuration(st.duration_ns)}</td>
                </tr>`)
                .join("");
        }

        // Worker Execution Performance
        if (elements.inspectorWorkerTbody) {
            if (insp.worker_performance && insp.worker_performance.length > 0) {
                elements.inspectorWorkerTbody.innerHTML = insp.worker_performance
                    .map((wp) => {
                        const statusBadge = wp.status === "ACTIVE"
                            ? '<span class="badge badge-emerald">ACTIVE</span>'
                            : (wp.status === "COMPLETED"
                                ? '<span class="badge badge-cyan">COMPLETED</span>'
                                : '<span class="badge badge-indigo">IDLE</span>');
                        return `<tr>
                            <td><strong class="code-text">${escapeHtml(wp.worker_id)}</strong></td>
                            <td><span class="badge badge-indigo">${escapeHtml(wp.device_type)}</span></td>
                            <td>${escapeHtml(wp.device_id || "—")}</td>
                            <td>${wp.pages_completed}</td>
                            <td>${wp.tasks_completed}</td>
                            <td>${wp.total_duration_ms.toFixed(1)}ms</td>
                            <td>${wp.avg_duration_ms.toFixed(1)}ms</td>
                            <td><strong>${wp.throughput_per_sec.toFixed(2)} p/s</strong></td>
                            <td>${statusBadge}</td>
                        </tr>`;
                    })
                    .join("");
            } else {
                elements.inspectorWorkerTbody.innerHTML = '<tr class="empty-row"><td colspan="9">No worker telemetry recorded.</td></tr>';
            }
        }

        // Confidence Distribution Cards
        if (insp.confidence_distribution) {
            const distMap = Object.fromEntries(insp.confidence_distribution);
            if (elements.statConfHigh) elements.statConfHigh.textContent = distMap["90-100%"] ?? "0";
            if (elements.statConfMid) elements.statConfMid.textContent = distMap["75-89%"] ?? "0";
            if (elements.statConfLow) elements.statConfLow.textContent = distMap["50-74%"] ?? "0";
            if (elements.statConfCrit) elements.statConfCrit.textContent = distMap["<50%"] ?? "0";
        }

        // Page-Level Quality & Confidence
        if (elements.inspectorPageConfTbody) {
            if (insp.page_confidence && insp.page_confidence.length > 0) {
                elements.inspectorPageConfTbody.innerHTML = insp.page_confidence
                    .map((pc) => {
                        const pct = (pc.confidence_score * 100).toFixed(1);
                        const confClass = pc.confidence_score >= 0.90
                            ? "badge-emerald"
                            : (pc.confidence_score >= 0.75 ? "badge-cyan" : "badge-amber");
                        const statusBadge = pc.review_recommended
                            ? '<span class="badge badge-amber">REVIEW</span>'
                            : '<span class="badge badge-emerald">OK</span>';
                        return `<tr>
                            <td><strong>${escapeHtml(pc.file_display_name)}</strong></td>
                            <td>Page ${pc.page_number}</td>
                            <td><span class="badge ${confClass}">${pct}%</span></td>
                            <td>${pc.region_count}</td>
                            <td>${(pc.min_confidence * 100).toFixed(1)}%</td>
                            <td>${(pc.max_confidence * 100).toFixed(1)}%</td>
                            <td>${statusBadge}</td>
                        </tr>`;
                    })
                    .join("");
            } else {
                elements.inspectorPageConfTbody.innerHTML = '<tr class="empty-row"><td colspan="7">No page confidence records.</td></tr>';
            }
        }

        // Region-Level Quality & Confidence
        state.allRegionConfidence = insp.region_confidence || [];
        renderFilteredRegions();

        // System Facts
        if (insp.system_facts && insp.system_facts.length > 0 && elements.systemFactsTbody) {
            elements.systemFactsTbody.innerHTML = insp.system_facts
                .map(([prop, val]) => `<tr>
                    <td><strong>${escapeHtml(prop)}</strong></td>
                    <td>${escapeHtml(val)}</td>
                </tr>`)
                .join("");
        }
    }

    function renderFilteredLogs() {
        if (!elements.inspectorLogs) return;
        const query = (state.logSearchQuery || "").toLowerCase();
        const level = state.logFilterLevel || "ALL";

        const filtered = (state.allActivityLogs || []).filter((entry) => {
            const [ts, comp, sev, msg] = entry;
            if (level !== "ALL" && sev.toUpperCase() !== level) return false;
            if (query && !`${ts} ${comp} ${msg}`.toLowerCase().includes(query)) return false;
            return true;
        });

        if (filtered.length === 0) {
            elements.inspectorLogs.innerHTML = '<div class="log-entry text-muted">No logs match the current filter.</div>';
            return;
        }

        elements.inspectorLogs.innerHTML = filtered
            .map((entry) => {
                const [ts, comp, sev, msg] = entry;
                const sevUpper = (sev || "INFO").toUpperCase();
                const sevClass = (sevUpper === "ERROR" || sevUpper === "FAILED")
                    ? "badge-crimson"
                    : (sevUpper === "WARN" ? "badge-amber" : "badge-indigo");
                return `<div class="log-entry">
                    <span class="text-muted">[${escapeHtml(ts)}]</span>
                    <span class="badge ${sevClass}">${escapeHtml(sevUpper)}</span>
                    <strong>${escapeHtml(comp)}</strong>: ${escapeHtml(msg)}
                </div>`;
            })
            .join("");
    }

    function renderFilteredRegions() {
        if (!elements.inspectorRegionConfTbody) return;
        const query = (state.regionSearchQuery || "").toLowerCase();

        const filtered = (state.allRegionConfidence || []).filter((rc) => {
            if (!query) return true;
            const target = `${rc.region_id} ${rc.file_display_name} p${rc.page_number} ${rc.region_type} ${rc.method}`.toLowerCase();
            return target.includes(query);
        });

        if (filtered.length === 0) {
            elements.inspectorRegionConfTbody.innerHTML = '<tr class="empty-row"><td colspan="7">No region confidence records match filter.</td></tr>';
            return;
        }

        elements.inspectorRegionConfTbody.innerHTML = filtered
            .map((rc) => {
                const pct = (rc.confidence_score * 100).toFixed(1);
                const confClass = rc.confidence_score >= 0.90
                    ? "badge-emerald"
                    : (rc.confidence_score >= 0.75 ? "badge-cyan" : "badge-amber");
                const statusBadge = rc.review_recommended
                    ? '<span class="badge badge-amber">REVIEW</span>'
                    : '<span class="badge badge-emerald">OK</span>';
                return `<tr>
                    <td><strong class="code-text">${escapeHtml(rc.region_id)}</strong></td>
                    <td>${escapeHtml(rc.file_display_name)}</td>
                    <td>P${rc.page_number}</td>
                    <td><span class="badge badge-indigo">${escapeHtml(rc.region_type)}</span></td>
                    <td><span class="badge ${confClass}">${pct}%</span></td>
                    <td>${escapeHtml(rc.method)}</td>
                    <td>${statusBadge}</td>
                </tr>`;
            })
            .join("");
    }

    // ==========================================
    // Run History Drawer Controller
    // ==========================================
    async function toggleHistoryDrawer(forceState) {
        if (!elements.historyDrawer) return;
        const isOpen = forceState !== undefined ? forceState : !elements.historyDrawer.classList.contains("open");
        elements.historyDrawer.classList.toggle("open", isOpen);
        if (isOpen) {
            elements.historyListContainer.innerHTML = '<div class="spinner"></div>';
            const res = await apiGet("/api/history?limit=30");
            if (res.ok && res.history && res.history.length > 0) {
                elements.historyListContainer.innerHTML = res.history
                    .map((h) => {
                        let stBadge = '<span class="badge badge-emerald">SUCCESS</span>';
                        if (h.status === "PARTIAL") stBadge = '<span class="badge badge-amber">PARTIAL</span>';
                        else if (h.status === "FAILED") stBadge = '<span class="badge badge-crimson">FAILED</span>';

                        return `
                            <div class="history-card" data-run-id="${escapeHtml(h.run_id)}">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <strong class="code-text">${escapeHtml(h.run_id)}</strong>
                                    ${stBadge}
                                </div>
                                <div style="font-size: 12px; color: var(--text-secondary); display: flex; justify-content: space-between;">
                                    <span>${h.total_inputs || 0} files</span>
                                    <span>${formatDuration(h.wall_time_ns)}</span>
                                </div>
                            </div>
                        `;
                    })
                    .join("");
            } else {
                elements.historyListContainer.innerHTML = '<div class="text-muted" style="text-align: center; padding: 20px;">No previous terminal runs found.</div>';
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

    // ==========================================
    // Initialization & Event Binding
    // ==========================================
    function init() {
        setupKeyboardShortcuts();

        // Nav tabs
        elements.navTabs.forEach((tab) => {
            tab.addEventListener("click", () => switchScreen(tab.dataset.screen));
        });

        // Header Actions
        if (elements.btnOpenHistory) {
            elements.btnOpenHistory.addEventListener("click", () => toggleHistoryDrawer());
        }
        if (elements.btnCloseHistory) {
            elements.btnCloseHistory.addEventListener("click", () => toggleHistoryDrawer(false));
        }

        // File Selection Buttons
        elements.btnBrowseFiles.addEventListener("click", handleBrowseFiles);
        elements.btnBrowseFolder.addEventListener("click", handleBrowseFolder);
        if (elements.btnClearSelected) {
            elements.btnClearSelected.addEventListener("click", handleClearSelected);
        }
        elements.btnClearInputs.addEventListener("click", handleClearInputs);
        if (elements.chkSelectAllInputs) {
            elements.chkSelectAllInputs.addEventListener("change", (e) => {
                const checked = e.target.checked;
                (state.intakeItems || []).forEach((item) => {
                    const p = item.source_path || item.display_name;
                    if (checked) state.checkedInputPaths.add(p);
                    else state.checkedInputPaths.delete(p);
                });
                elements.selectedInputsTbody.querySelectorAll(".input-row-chk").forEach((cb) => {
                    cb.checked = checked;
                });
                updateClearSelectedButton();
            });
        }
        elements.selectedInputsTbody.addEventListener("change", (e) => {
            if (e.target.classList.contains("input-row-chk")) {
                const p = e.target.dataset.path;
                if (e.target.checked) state.checkedInputPaths.add(p);
                else state.checkedInputPaths.delete(p);
                updateClearSelectedButton();
            }
        });
        elements.selectedInputsTbody.addEventListener("click", (e) => {
            const removeBtn = e.target.closest(".btn-remove-row");
            if (removeBtn && removeBtn.dataset.path) {
                removePaths([removeBtn.dataset.path]);
                return;
            }
            const prevBtn = e.target.closest(".btn-preview-file");
            if (prevBtn && prevBtn.dataset.path) {
                openDocumentPreview(prevBtn.dataset.path, prevBtn.dataset.path.split(/[\\/]/).pop());
            }
        });
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
                updateRequirementOptionsVisibility();
                if (state.selectedPaths.length > 0 && state.activeRunStatus !== "RUNNING") {
                    elements.btnStartRun.disabled = false;
                }
            });
        });

        // Profile Selector
        elements.selectProfile.addEventListener("change", (e) => {
            state.currentProfile = e.target.value;
            updateRequirementOptionsVisibility();
        });

        // Run Actions
        elements.btnStartRun.addEventListener("click", handleStartRun);
        elements.btnCancelRun.addEventListener("click", handleCancelRun);
        elements.btnOpenOutputFolder.addEventListener("click", handleOpenOutputFolder);
        elements.btnReturnHome.addEventListener("click", () => switchScreen("home"));

        // Artifact Preview click delegation in Samapti
        if (elements.artifactsGrid) {
            elements.artifactsGrid.addEventListener("click", (e) => {
                const prevBtn = e.target.closest(".btn-preview-artifact");
                if (prevBtn && prevBtn.dataset.runId && prevBtn.dataset.artId) {
                    const artUrl = `/api/runs/${encodeURIComponent(prevBtn.dataset.runId)}/artifacts/${encodeURIComponent(prevBtn.dataset.artId)}`;
                    openDocumentPreview(artUrl, prevBtn.dataset.name);
                }
            });
        }

        // Preview Modal Close
        if (elements.btnClosePreview && elements.docPreviewDialog) {
            elements.btnClosePreview.addEventListener("click", () => elements.docPreviewDialog.close());
        }

        // Pariksha Review Actions
        if (elements.btnReviewAccept) {
            elements.btnReviewAccept.addEventListener("click", () => handleReviewAction("accept"));
        }
        if (elements.btnReviewDismiss) {
            elements.btnReviewDismiss.addEventListener("click", () => handleReviewAction("dismiss"));
        }
        if (elements.btnReviewEdit) {
            elements.btnReviewEdit.addEventListener("click", () => {
                const current = elements.reviewOutputText ? elements.reviewOutputText.textContent : "";
                const val = prompt("Edit correction proposal:", current);
                if (val !== null) handleReviewAction("edit");
            });
        }

        // Inspector Sub-Tabs & Log Filtering
        if (elements.inspectorTabs) {
            elements.inspectorTabs.forEach((tab) => {
                tab.addEventListener("click", () => {
                    elements.inspectorTabs.forEach((t) => t.classList.remove("active"));
                    tab.classList.add("active");
                    const targetTab = tab.dataset.tab;
                    elements.inspectorTabContents.forEach((content) => {
                        content.classList.toggle("hidden", content.id !== `tab-inspector-${targetTab}`);
                    });
                });
            });
        }
        if (elements.logPills) {
            elements.logPills.forEach((pill) => {
                pill.addEventListener("click", () => {
                    elements.logPills.forEach((p) => p.classList.remove("active"));
                    pill.classList.add("active");
                    state.logFilterLevel = pill.dataset.level;
                    renderFilteredLogs();
                });
            });
        }
        if (elements.inputLogSearch) {
            elements.inputLogSearch.addEventListener("input", (e) => {
                state.logSearchQuery = e.target.value;
                renderFilteredLogs();
            });
        }
        if (elements.inspectorRegionFilter) {
            elements.inspectorRegionFilter.addEventListener("input", (e) => {
                state.regionSearchQuery = e.target.value;
                renderFilteredRegions();
            });
        }
        if (elements.btnCopyLogs) {
            elements.btnCopyLogs.addEventListener("click", () => {
                if (elements.inspectorLogs) {
                    navigator.clipboard.writeText(elements.inspectorLogs.innerText);
                }
            });
        }

        // Error Banner Dismiss
        if (elements.btnDismissError) {
            elements.btnDismissError.addEventListener("click", hideError);
        }

        // Cancel Run Confirmation Modal
        if (elements.btnCancelDialogConfirm) {
            elements.btnCancelDialogConfirm.addEventListener("click", () => {
                if (elements.cancelRunDialog && typeof elements.cancelRunDialog.close === "function") {
                    elements.cancelRunDialog.close();
                }
                dispatchCancelRun();
            });
        }
        if (elements.btnCancelDialogDismiss) {
            elements.btnCancelDialogDismiss.addEventListener("click", () => {
                if (elements.cancelRunDialog && typeof elements.cancelRunDialog.close === "function") {
                    elements.cancelRunDialog.close();
                }
            });
        }

        updateRequirementOptionsVisibility();

        // Connect Real-Time SSE Stream (with Polling Fallback)
        initSSE();

        // Dynamic Inspector refresh during active runs
        setInterval(() => {
            if (state.currentScreen === "inspector" && state.activeRunStatus === "RUNNING") {
                loadInspector();
            }
        }, 1500);
    }

    function updateRequirementOptionsVisibility() {
        if (elements.profileRow) {
            elements.profileRow.classList.toggle("hidden", state.currentRequirement !== "ocr");
        }
        if (elements.ocrLangRow) {
            elements.ocrLangRow.classList.toggle("hidden", state.currentRequirement !== "ocr");
        }
        if (elements.ocrCustomControls) {
            elements.ocrCustomControls.classList.toggle("hidden", !(state.currentRequirement === "ocr" && state.currentProfile === "custom"));
        }
        if (elements.fontModeRow) {
            elements.fontModeRow.classList.toggle("hidden", state.currentRequirement !== "font_conversion");
        }
    }

    // Start on DOM Ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
