/**
 * Centralized DOM element cache and UI feedback helpers for Mukha.
 */

export const elements = {
    navTabs: null,
    screens: null,
    systemStatusDot: null,
    systemStatusText: null,
    sseStatusBadge: null,
    sseStatusLabel: null,
    btnOpenHistory: null,
    btnCommandPalette: null,

    // Home Elements
    btnBrowseFiles: null,
    btnBrowseFolder: null,
    btnClearSelected: null,
    btnClearInputs: null,
    inputManualPath: null,
    btnAddManualPath: null,
    chkRecursive: null,
    chkSelectAllInputs: null,
    selectedInputsTbody: null,
    inputGroupsContainer: null,
    inputCountsBadge: null,
    inputFilesFilter: null,
    requirementGrid: null,
    actionParamsContainer: null,
    preflightSummary: null,
    preflightIssues: null,
    preflightPlanPreview: null,
    btnStartRun: null,

    // Monitor Elements
    monitorRunId: null,
    monitorStatusBadge: null,
    monitorElapsedTime: null,
    monitorProgressBar: null,
    btnCancelRun: null,
    longRunningAlert: null,
    longRunningDesc: null,
    focusStageName: null,
    focusFileName: null,
    focusDeviceType: null,
    focusDuration: null,
    deviceThroughputTbody: null,
    activeWorkersCount: null,
    activeWorkersTbody: null,
    pipelineCounts: null,
    filePipelineTbody: null,

    // Review Elements
    reviewBadge: null,
    reviewQueueCount: null,
    reviewQueueTbody: null,
    reviewDetailCard: null,
    reviewActiveItemTitle: null,
    reviewSourceText: null,
    reviewOutputText: null,
    reviewConfidenceFill: null,
    reviewConfidenceText: null,
    btnReviewAccept: null,
    btnReviewEdit: null,
    btnReviewDismiss: null,

    // Summary Elements
    summaryHero: null,
    summaryStatusBadge: null,
    summaryTitle: null,
    summaryRunMeta: null,
    summaryFailureReason: null,
    btnOpenOutputFolder: null,
    btnReturnHome: null,
    statTotalFiles: null,
    statSuccessFiles: null,
    statWarningFiles: null,
    statFailedFiles: null,
    statConfidence: null,
    artifactsGrid: null,
    summaryDeviceTbody: null,
    summaryStagesTbody: null,

    // Inspector Elements
    inspectorTabs: null,
    inspectorTabContents: null,
    inputLogSearch: null,
    logPills: null,
    btnCopyLogs: null,
    inspectorLogs: null,
    inspectorDeviceTbody: null,
    inspectorStagesTbody: null,
    inspectorWorkerTbody: null,
    inspectorPageConfTbody: null,
    inspectorRegionConfTbody: null,
    inspectorRegionFilter: null,
    statConfHigh: null,
    statConfMid: null,
    statConfLow: null,
    statConfCrit: null,
    systemFactsTbody: null,

    // Document Preview Dialog
    docPreviewDialog: null,
    previewModalTitle: null,
    previewModalContent: null,
    btnClosePreview: null,

    // History Drawer
    historyDrawer: null,
    historyListContainer: null,
    btnCloseHistory: null,

    // Overlay
    aarambhaOverlay: null,
    aarambhaStage: null,

    // Alert Banner & Dialog Elements
    errorBanner: null,
    errorBannerText: null,
    btnDismissError: null,
    cancelRunDialog: null,
    btnCancelDialogConfirm: null,
    btnCancelDialogDismiss: null,
};

export function initDom() {
    elements.navTabs = document.querySelectorAll(".nav-tab");
    elements.screens = document.querySelectorAll(".screen-view");
    elements.systemStatusDot = document.getElementById("system-status-dot");
    elements.systemStatusText = document.getElementById("system-status-text");
    elements.sseStatusBadge = document.getElementById("sse-status-badge");
    elements.sseStatusLabel = document.getElementById("sse-status-label");
    elements.btnOpenHistory = document.getElementById("btn-open-history");
    elements.btnCommandPalette = document.getElementById("btn-command-palette");

    // Home
    elements.btnBrowseFiles = document.getElementById("btn-browse-files");
    elements.btnBrowseFolder = document.getElementById("btn-browse-folder");
    elements.btnClearSelected = document.getElementById("btn-clear-selected");
    elements.btnClearInputs = document.getElementById("btn-clear-inputs");
    elements.inputManualPath = document.getElementById("input-manual-path");
    elements.btnAddManualPath = document.getElementById("btn-add-manual-path");
    elements.chkRecursive = document.getElementById("chk-recursive");
    elements.chkSelectAllInputs = document.getElementById("chk-select-all-inputs");
    elements.selectedInputsTbody = document.getElementById("selected-inputs-tbody");
    elements.inputGroupsContainer = document.getElementById("input-groups-container");
    elements.inputCountsBadge = document.getElementById("input-counts-badge");
    elements.inputFilesFilter = document.getElementById("input-files-filter");
    elements.requirementGrid = document.getElementById("requirement-grid");
    elements.actionParamsContainer = document.getElementById("action-parameters-container");
    elements.preflightSummary = document.getElementById("preflight-summary");
    elements.preflightIssues = document.getElementById("preflight-issues");
    elements.preflightPlanPreview = document.getElementById("preflight-plan-preview");
    elements.btnStartRun = document.getElementById("btn-start-run");

    // Monitor
    elements.monitorRunId = document.getElementById("monitor-run-id");
    elements.monitorStatusBadge = document.getElementById("monitor-status-badge");
    elements.monitorElapsedTime = document.getElementById("monitor-elapsed-time");
    elements.monitorProgressBar = document.getElementById("monitor-progress-bar");
    elements.btnCancelRun = document.getElementById("btn-cancel-run");
    elements.longRunningAlert = document.getElementById("long-running-alert");
    elements.longRunningDesc = document.getElementById("long-running-desc");
    elements.focusStageName = document.getElementById("focus-stage-name");
    elements.focusFileName = document.getElementById("focus-file-name");
    elements.focusDeviceType = document.getElementById("focus-device-type");
    elements.focusDuration = document.getElementById("focus-duration");
    elements.deviceThroughputTbody = document.getElementById("device-throughput-tbody");
    elements.activeWorkersCount = document.getElementById("active-workers-count");
    elements.activeWorkersTbody = document.getElementById("active-workers-tbody");
    elements.pipelineCounts = document.getElementById("pipeline-counts");
    elements.filePipelineTbody = document.getElementById("file-pipeline-tbody");

    // Review
    elements.reviewBadge = document.getElementById("review-badge");
    elements.reviewQueueCount = document.getElementById("review-queue-count");
    elements.reviewQueueTbody = document.getElementById("review-queue-tbody");
    elements.reviewDetailCard = document.getElementById("review-detail-card");
    elements.reviewActiveItemTitle = document.getElementById("review-active-item-title");
    elements.reviewSourceText = document.getElementById("review-source-text");
    elements.reviewOutputText = document.getElementById("review-output-text");
    elements.reviewConfidenceFill = document.getElementById("review-confidence-fill");
    elements.reviewConfidenceText = document.getElementById("review-confidence-text");
    elements.btnReviewAccept = document.getElementById("btn-review-accept");
    elements.btnReviewEdit = document.getElementById("btn-review-edit");
    elements.btnReviewDismiss = document.getElementById("btn-review-dismiss");

    // Summary
    elements.summaryHero = document.getElementById("summary-hero");
    elements.summaryStatusBadge = document.getElementById("summary-status-badge");
    elements.summaryTitle = document.getElementById("summary-title");
    elements.summaryRunMeta = document.getElementById("summary-run-meta");
    elements.summaryFailureReason = document.getElementById("summary-failure-reason");
    elements.btnOpenOutputFolder = document.getElementById("btn-open-output-folder");
    elements.btnReturnHome = document.getElementById("btn-return-home");
    elements.statTotalFiles = document.getElementById("stat-total-files");
    elements.statSuccessFiles = document.getElementById("stat-success-files");
    elements.statWarningFiles = document.getElementById("stat-warning-files");
    elements.statFailedFiles = document.getElementById("stat-failed-files");
    elements.statConfidence = document.getElementById("stat-confidence");
    elements.artifactsGrid = document.getElementById("artifacts-grid");
    elements.summaryDeviceTbody = document.getElementById("summary-device-tbody");
    elements.summaryStagesTbody = document.getElementById("summary-stages-tbody");

    // Inspector
    elements.inspectorTabs = document.querySelectorAll(".inspector-tab");
    elements.inspectorTabContents = document.querySelectorAll(".inspector-tab-content");
    elements.inputLogSearch = document.getElementById("input-log-search");
    elements.logPills = document.querySelectorAll(".log-pill");
    elements.btnCopyLogs = document.getElementById("btn-copy-logs");
    elements.inspectorLogs = document.getElementById("inspector-logs");
    elements.inspectorDeviceTbody = document.getElementById("inspector-device-tbody");
    elements.inspectorStagesTbody = document.getElementById("inspector-stages-tbody");
    elements.inspectorWorkerTbody = document.getElementById("inspector-worker-tbody");
    elements.inspectorPageConfTbody = document.getElementById("inspector-page-conf-tbody");
    elements.inspectorRegionConfTbody = document.getElementById("inspector-region-conf-tbody");
    elements.inspectorRegionFilter = document.getElementById("inspector-region-filter");
    elements.statConfHigh = document.getElementById("stat-conf-high");
    elements.statConfMid = document.getElementById("stat-conf-mid");
    elements.statConfLow = document.getElementById("stat-conf-low");
    elements.statConfCrit = document.getElementById("stat-conf-crit");
    elements.systemFactsTbody = document.getElementById("system-facts-tbody");

    // Preview
    elements.docPreviewDialog = document.getElementById("doc-preview-dialog");
    elements.previewModalTitle = document.getElementById("preview-modal-title");
    elements.previewModalContent = document.getElementById("preview-modal-content");
    elements.btnClosePreview = document.getElementById("btn-close-preview");

    // History
    elements.historyDrawer = document.getElementById("history-drawer");
    elements.historyListContainer = document.getElementById("history-list-container");
    elements.btnCloseHistory = document.getElementById("btn-close-history");

    // Overlay
    elements.aarambhaOverlay = document.getElementById("aarambha-overlay");
    elements.aarambhaStage = document.getElementById("aarambha-stage");

    // Banner & Dialog
    elements.errorBanner = document.getElementById("error-banner");
    elements.errorBannerText = document.getElementById("error-banner-text");
    elements.btnDismissError = document.getElementById("btn-dismiss-error");
    elements.cancelRunDialog = document.getElementById("cancel-run-dialog");
    elements.btnCancelDialogConfirm = document.getElementById("btn-cancel-dialog-confirm");
    elements.btnCancelDialogDismiss = document.getElementById("btn-cancel-dialog-dismiss");
}

export function showError(msg) {
    if (!elements.errorBanner || !elements.errorBannerText) return;
    elements.errorBannerText.textContent = msg;
    elements.errorBanner.classList.remove("hidden");
}

export function hideError() {
    if (elements.errorBanner) {
        elements.errorBanner.classList.add("hidden");
    }
}
