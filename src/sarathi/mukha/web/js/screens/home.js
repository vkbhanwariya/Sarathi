/**
 * Screen 1: Griha (Home & Intake Setup) Controller for Mukha.
 */

import { apiPost, pollState } from "../api.js";
import { elements, hideError, showError } from "../dom.js";
import { escapeHtml, formatBytes } from "../formatters.js";
import { openDocumentPreview } from "../preview.js";
import { state, switchScreen } from "../state.js";

export function updateClearSelectedButton() {
    if (!elements.btnClearSelected) return;
    const count = state.checkedInputPaths.size;
    elements.btnClearSelected.disabled = count === 0;
    elements.btnClearSelected.textContent = count > 0 ? `Clear Selected (${count})` : "Clear Selected";
}

export async function addSelectedPaths(newPaths) {
    const set = new Set([...state.selectedRoots, ...newPaths]);
    state.selectedRoots = Array.from(set);
    await refreshIntake();
}

export function removePaths(pathsToRemove) {
    const toRemoveSet = new Set(pathsToRemove);
    state.selectedRoots = state.selectedRoots.filter((p) => !toRemoveSet.has(p));
    pathsToRemove.forEach((p) => {
        state.excludedPaths.add(p);
        state.checkedInputPaths.delete(p);
    });
    updateClearSelectedButton();
    refreshIntake();
}

export async function handleBrowseFiles() {
    if (!elements.btnBrowseFiles) return;
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

export async function handleBrowseFolder() {
    if (!elements.btnBrowseFolder) return;
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

export function handleAddManualPath() {
    if (!elements.inputManualPath) return;
    const val = elements.inputManualPath.value.trim();
    if (val) {
        hideError();
        addSelectedPaths([val]);
        elements.inputManualPath.value = "";
    }
}

export async function handleClearSelected() {
    if (state.checkedInputPaths.size === 0) return;
    removePaths(Array.from(state.checkedInputPaths));
}

export async function handleClearInputs() {
    state.selectedRoots = [];
    state.selectedPaths = [];
    state.excludedPaths.clear();
    state.checkedInputPaths.clear();
    state.intakeItems = [];
    updateClearSelectedButton();
    if (elements.chkSelectAllInputs) elements.chkSelectAllInputs.checked = false;
    await refreshIntake();
}

export async function refreshIntake() {
    if (state.selectedRoots.length === 0) {
        state.selectedPaths = [];
        state.intakeItems = [];
        renderInputsTable([]);
        renderPreflight({ eligible_count: 0, issue_count: 0, issues: [] });
        if (elements.btnStartRun) elements.btnStartRun.disabled = true;
        if (elements.inputCountsBadge) elements.inputCountsBadge.textContent = "0 files";
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
        if (elements.inputCountsBadge) {
            elements.inputCountsBadge.textContent = `${filteredItems.length} files (${formatBytes(totalSize)})`;
        }
        renderPreflight(res.preflight || { eligible_count: filteredItems.length, issue_count: 0, issues: [] });
        if (elements.btnStartRun) {
            elements.btnStartRun.disabled = filteredItems.length === 0;
        }
    } else if (res.error) {
        showError(res.error);
    }
}

export function renderInputsTable(items, inputSelection) {
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

    if (!elements.selectedInputsTbody) return;

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
                    <button class="btn btn-outline btn-sm btn-preview-file" data-path="${escapeHtml(pathVal)}" data-input-id="${escapeHtml(item.input_id || '')}" data-name="${escapeHtml(item.display_name)}" title="Preview Document">👁️</button>
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

export function renderPreflight(preflight) {
    if (!elements.preflightSummary) return;
    elements.preflightSummary.textContent = `${preflight.eligible_count} eligible, ${preflight.issue_count} issues`;
    if (elements.preflightIssues) {
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
}

export async function handleStartRun() {
    if (state.selectedPaths.length === 0 || !elements.btnStartRun) return;

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

export function initHomeScreen() {
    if (elements.btnBrowseFiles) elements.btnBrowseFiles.addEventListener("click", handleBrowseFiles);
    if (elements.btnBrowseFolder) elements.btnBrowseFolder.addEventListener("click", handleBrowseFolder);
    if (elements.btnAddManualPath) elements.btnAddManualPath.addEventListener("click", handleAddManualPath);
    if (elements.inputManualPath) {
        elements.inputManualPath.addEventListener("keydown", (e) => {
            if (e.key === "Enter") handleAddManualPath();
        });
    }
    if (elements.btnClearSelected) elements.btnClearSelected.addEventListener("click", handleClearSelected);
    if (elements.btnClearInputs) elements.btnClearInputs.addEventListener("click", handleClearInputs);
    if (elements.btnStartRun) elements.btnStartRun.addEventListener("click", handleStartRun);

    if (elements.chkRecursive) {
        elements.chkRecursive.addEventListener("change", (e) => {
            state.isRecursive = e.target.checked;
            refreshIntake();
        });
    }

    if (elements.chkSelectAllInputs) {
        elements.chkSelectAllInputs.addEventListener("change", (e) => {
            const isChecked = e.target.checked;
            if (isChecked) {
                state.intakeItems.forEach((it) => {
                    const p = it.source_path || it.display_name;
                    if (p) state.checkedInputPaths.add(p);
                });
            } else {
                state.checkedInputPaths.clear();
            }
            updateClearSelectedButton();
            renderInputsTable(state.intakeItems);
        });
    }

    if (elements.selectedInputsTbody) {
        elements.selectedInputsTbody.addEventListener("change", (e) => {
            if (e.target.classList.contains("input-row-chk")) {
                const pathVal = e.target.dataset.path;
                if (e.target.checked) {
                    state.checkedInputPaths.add(pathVal);
                } else {
                    state.checkedInputPaths.delete(pathVal);
                }
                updateClearSelectedButton();
                if (elements.chkSelectAllInputs) {
                    elements.chkSelectAllInputs.checked = state.intakeItems.length > 0 && state.intakeItems.every((i) => state.checkedInputPaths.has(i.source_path || i.display_name));
                }
            }
        });

        elements.selectedInputsTbody.addEventListener("click", (e) => {
            const btnRemove = e.target.closest(".btn-remove-row");
            if (btnRemove) {
                const pathVal = btnRemove.dataset.path;
                if (pathVal) removePaths([pathVal]);
                return;
            }

            const btnPreview = e.target.closest(".btn-preview-file");
            if (btnPreview) {
                const inputId = btnPreview.dataset.inputId;
                const pathVal = btnPreview.dataset.path;
                const name = btnPreview.dataset.name;
                const target = inputId ? `/api/inputs/${encodeURIComponent(inputId)}/preview` : pathVal;
                if (target) openDocumentPreview(target, name);
            }
        });
    }

    if (elements.reqCards) {
        elements.reqCards.forEach((card) => {
            card.addEventListener("click", () => {
                elements.reqCards.forEach((c) => c.classList.remove("selected"));
                card.classList.add("selected");
                state.currentRequirement = card.dataset.req;

                if (elements.profileRow) {
                    elements.profileRow.classList.toggle("hidden", state.currentRequirement !== "ocr");
                }
                if (elements.ocrLangRow) {
                    elements.ocrLangRow.classList.toggle("hidden", state.currentRequirement !== "ocr");
                }
                if (elements.ocrCustomControls) {
                    elements.ocrCustomControls.classList.toggle(
                        "hidden",
                        !(state.currentRequirement === "ocr" && state.currentProfile === "custom")
                    );
                }
                if (elements.fontModeRow) {
                    elements.fontModeRow.classList.toggle("hidden", state.currentRequirement !== "font_conversion");
                }
            });
        });
    }

    if (elements.selectProfile) {
        elements.selectProfile.addEventListener("change", (e) => {
            state.currentProfile = e.target.value;
            if (elements.ocrCustomControls) {
                elements.ocrCustomControls.classList.toggle(
                    "hidden",
                    !(state.currentRequirement === "ocr" && state.currentProfile === "custom")
                );
            }
        });
    }
}
