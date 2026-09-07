/**
 * Reactive application state store and screen routing coordinator for Mukha.
 */

import { elements } from "./dom.js";

export const state = {
    currentScreen: "home",
    selectedRoots: [],
    selectedPaths: [],
    excludedPaths: new Set(),
    currentRequirement: "read_native",
    currentProfile: "instant",
    isRecursive: true,
    activeRunId: null,
    activeRunStatus: "idle",
    viewedRunId: null,
    followLive: true,
    lastAutoNavigatedRunId: null,
    lastState: null,
    lastRevision: 0,
    pollIntervalMs: 500,
    pollTimer: null,
    checkedInputPaths: new Set(),
    intakeItems: [],
    inputSearchQuery: "",
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
    screenChangeCallbacks: {},
    draftActionParams: {},
    requestSeq: 0,
    summaryRequestSeq: 0,
    inspectorRequestSeq: 0,
    inputFilterMode: "all",
    inputPagination: { page: 1, pageSize: 10 },
    inputSelectionScope: "page",
    showAllInputsTable: false,
};

if (typeof window !== "undefined") {
    window.sarathiState = state;
}

export function getDraftParam(actionId, paramId, defaultValue) {
    if (state.draftActionParams[actionId] && state.draftActionParams[actionId][paramId] !== undefined) {
        return state.draftActionParams[actionId][paramId];
    }
    return defaultValue;
}

export function setDraftParam(actionId, paramId, value) {
    if (!state.draftActionParams[actionId]) {
        state.draftActionParams[actionId] = {};
    }
    state.draftActionParams[actionId][paramId] = value;
}

export function registerScreenCallback(screenId, callback) {
    state.screenChangeCallbacks[screenId] = callback;
}

export function switchScreen(screenId) {
    state.currentScreen = screenId;
    if (elements.navTabs) {
        elements.navTabs.forEach((tab) => {
            tab.classList.toggle("active", tab.dataset.screen === screenId);
        });
    }
    if (elements.screens) {
        elements.screens.forEach((view) => {
            view.classList.toggle("active", view.id === `screen-${screenId}`);
        });
    }

    const cb = state.screenChangeCallbacks[screenId];
    if (typeof cb === "function") {
        cb();
    }
}
