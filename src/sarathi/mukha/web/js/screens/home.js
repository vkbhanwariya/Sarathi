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

export function renderAvailableActions(actions) {
    if (!elements.requirementGrid || !actions || actions.length === 0) return;
    state.availableActions = actions;

    const cardsHtml = actions
        .map((act) => {
            const isActive = act.action_id === state.currentRequirement;
            const isDisabled = !act.is_enabled;
            const statusBadge = act.is_enabled
                ? '<span class="req-status badge badge-emerald">Ready</span>'
                : `<span class="req-status badge badge-amber" title="${escapeHtml(act.disabled_reason || "Unavailable")}">Unavailable</span>`;
            return `
                <button type="button" class="req-card ${isActive ? "selected active" : ""} ${isDisabled ? "disabled" : ""}" data-req="${escapeHtml(act.action_id)}" ${isDisabled ? "disabled" : ""}>
                    <div class="req-title">${escapeHtml(act.label)}</div>
                    <div class="req-desc">${escapeHtml(act.description || "")}</div>
                    ${statusBadge}
                </button>
            `;
        })
        .join("");

    elements.requirementGrid.innerHTML = cardsHtml;

    const activeAction = actions.find((a) => a.action_id === state.currentRequirement) || actions[0];
    if (activeAction) {
        renderActionParameters(activeAction);
    }
}

export function renderActionParameters(action) {
    if (!elements.actionParamsContainer) return;
    if (!action || !action.parameters || action.parameters.length === 0) {
        elements.actionParamsContainer.classList.add("hidden");
        elements.actionParamsContainer.innerHTML = "";
        return;
    }

    elements.actionParamsContainer.classList.remove("hidden");

    const selects = action.parameters.filter((p) => p.kind === "select");
    const toggles = action.parameters.filter((p) => p.kind === "toggle");

    let html = "";
    if (selects.length > 0) {
        html += selects
            .map((p) => {
                const optsHtml = (p.options || [])
                    .map(([val, text]) => `<option value="${escapeHtml(val)}" ${val === p.default_value ? "selected" : ""}>${escapeHtml(text)}</option>`)
                    .join("");
                return `
                    <div class="form-row" style="margin-bottom: 8px;">
                        <label class="form-label" style="font-weight: 600; font-size: 0.85rem;">${escapeHtml(p.display_name)}</label>
                        <select class="form-select action-param-select" data-param="${escapeHtml(p.parameter_id)}" id="param-${escapeHtml(p.parameter_id)}">
                            ${optsHtml}
                        </select>
                    </div>
                `;
            })
            .join("");
    }

    if (toggles.length > 0) {
        const isProfileCustom = !selects.some((p) => p.parameter_id === "profile") || (document.getElementById("param-profile") && document.getElementById("param-profile").value === "custom");
        const togglesHtml = toggles
            .map((t) => `
                <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                    <input type="checkbox" class="action-param-toggle" data-param="${escapeHtml(t.parameter_id)}" id="param-${escapeHtml(t.parameter_id)}" ${t.default_value ? "checked" : ""}>
                    <span>${escapeHtml(t.display_name)}</span>
                </label>
            `)
            .join("");

        html += `
            <div id="dynamic-toggles-group" class="form-row ${isProfileCustom ? "" : "hidden"}" style="border: 1px solid var(--border-color); padding: 12px; border-radius: var(--radius-sm); margin-top: 8px; background: rgba(8, 12, 20, 0.5);">
                <label class="form-label" style="font-weight: 600; margin-bottom: 8px;">Advanced Engine Settings</label>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 0.85rem;">
                    ${togglesHtml}
                </div>
            </div>
        `;
    }

    elements.actionParamsContainer.innerHTML = html;

    const profileSelect = document.getElementById("param-profile");
    const togglesGroup = document.getElementById("dynamic-toggles-group");
    if (profileSelect && togglesGroup) {
        profileSelect.addEventListener("change", (e) => {
            state.currentProfile = e.target.value;
            togglesGroup.classList.toggle("hidden", e.target.value !== "custom");
        });
    }
}

export async function handleStartRun() {
    if (state.selectedPaths.length === 0 || !elements.btnStartRun) return;

    elements.btnStartRun.disabled = true;
    hideError();

    const customOpts = {};
    let profile = "instant";

    if (elements.actionParamsContainer) {
        const selects = elements.actionParamsContainer.querySelectorAll(".action-param-select");
        selects.forEach((s) => {
            const p = s.dataset.param;
            if (p === "profile") {
                profile = s.value;
            } else {
                customOpts[p] = s.value;
            }
        });

        const toggles = elements.actionParamsContainer.querySelectorAll(".action-param-toggle");
        toggles.forEach((t) => {
            customOpts[t.dataset.param] = t.checked;
        });
    }

    if (state.currentRequirement === "ocr" && profile === "custom") {
        customOpts.engine = "rapidocr";
    }

    const payload = {
        paths: state.selectedPaths,
        requirement: state.currentRequirement,
        profile: profile,
        recursive: state.isRecursive,
        custom_options: customOpts,
    };

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

    if (elements.requirementGrid) {
        elements.requirementGrid.addEventListener("click", (e) => {
            const card = e.target.closest(".req-card");
            if (card && card.dataset.req && !card.classList.contains("disabled")) {
                const cards = elements.requirementGrid.querySelectorAll(".req-card");
                cards.forEach((c) => c.classList.remove("selected", "active"));
                card.classList.add("selected", "active");
                state.currentRequirement = card.dataset.req;

                const act = (state.availableActions || []).find((a) => a.action_id === state.currentRequirement);
                if (act) {
                    renderActionParameters(act);
                }
            }
        });
    }
}
