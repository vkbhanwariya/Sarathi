/**
 * Screen 1: Griha (Home & Intake Setup) Controller for Mukha.
 */

import { apiPost, pollState } from "../api.js";
import { elements, hideError, showError } from "../dom.js";
import { escapeHtml, formatBytes } from "../formatters.js";
import { openDocumentPreview } from "../preview.js";
import { getDraftParam, setDraftParam, state, switchScreen } from "../state.js";

export function updateClearSelectedButton() {
    if (!elements.btnClearSelected) return;
    const count = state.checkedInputPaths.size;
    elements.btnClearSelected.disabled = count === 0;
    elements.btnClearSelected.textContent = count > 0 ? `Clear Selected (${count})` : "Clear Selected";
}

export async function addSelectedPaths(newPaths) {
    newPaths.forEach((p) => state.excludedPaths.delete(p));
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
    state.showAllInputsTable = false;
    state.inputPagination = { page: 1, pageSize: 10 };
    state.inputFilterMode = "all";
    state.inputSearchQuery = "";
    if (elements.inputFilesFilter) elements.inputFilesFilter.value = "";
    updateClearSelectedButton();
    if (elements.chkSelectAllInputs) {
        elements.chkSelectAllInputs.checked = false;
        elements.chkSelectAllInputs.indeterminate = false;
    }
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
        const preflightData = res.preflight || {
            eligible_count: filteredItems.filter((i) => i.is_eligible !== false).length,
            issue_count: 0,
            issues: [],
        };
        renderPreflight(preflightData);
        if (elements.btnStartRun) {
            elements.btnStartRun.disabled = filteredItems.length === 0 || preflightData.eligible_count === 0;
        }
        previewPlan();
    } else if (res.error) {
        showError(res.error);
    }
}

export function renderInputsTable(items, inputSelection) {
    if (items) state.intakeItems = items;
    if (inputSelection) state.lastInputSelection = inputSelection;
    const allItems = state.intakeItems || [];
    const totalSize = allItems.reduce((acc, it) => acc + (it.size_bytes || 0), 0);

    const selectionObj = inputSelection || state.lastInputSelection;
    if (elements.inputGroupsContainer) {
        if (selectionObj && selectionObj.groups && selectionObj.groups.length > 0) {
            elements.inputGroupsContainer.innerHTML = selectionObj.groups
                .map((g) => `<div class="badge badge-indigo" style="padding: 4px 10px;"><strong>${escapeHtml(g.format_name)}</strong>: ${g.file_count} files (${formatBytes(g.total_size_bytes)})</div>`)
                .join(" ");
        } else {
            elements.inputGroupsContainer.innerHTML = "";
        }
    }

    const isLargeBatch = allItems.length > 10;
    if (elements.inputGroupedSummary) {
        elements.inputGroupedSummary.classList.toggle("hidden", !isLargeBatch);
        if (elements.inputGroupedSummaryText) {
            elements.inputGroupedSummaryText.textContent = `${allItems.length} documents selected (${formatBytes(totalSize)})`;
        }
        if (elements.btnViewAllInputs) {
            elements.btnViewAllInputs.textContent = `👁️ View All (${allItems.length} files)`;
            elements.btnViewAllInputs.classList.toggle("hidden", state.showAllInputsTable);
        }
    }
    if (elements.btnCollapseInputs) {
        elements.btnCollapseInputs.classList.toggle("hidden", !isLargeBatch || !state.showAllInputsTable);
    }

    const showTable = !isLargeBatch || state.showAllInputsTable;
    if (elements.inputTableContainer) {
        elements.inputTableContainer.classList.toggle("hidden", !showTable);
    }
    if (elements.inputFiltersBar) {
        elements.inputFiltersBar.classList.toggle("hidden", !showTable && isLargeBatch);
    }

    // Filter counting across all items
    const eligibleCount = allItems.filter((i) => i.is_eligible).length;
    const issuesCount = allItems.filter((i) => !i.is_eligible).length;
    if (elements.filterAllCount) elements.filterAllCount.textContent = allItems.length;
    if (elements.filterEligibleCount) elements.filterEligibleCount.textContent = eligibleCount;
    if (elements.filterIssuesCount) elements.filterIssuesCount.textContent = issuesCount;

    if (elements.btnFilterAll) {
        elements.btnFilterAll.classList.toggle("active", state.inputFilterMode === "all");
        elements.btnFilterAll.setAttribute("aria-selected", state.inputFilterMode === "all");
    }
    if (elements.btnFilterEligible) {
        elements.btnFilterEligible.classList.toggle("active", state.inputFilterMode === "eligible");
        elements.btnFilterEligible.setAttribute("aria-selected", state.inputFilterMode === "eligible");
    }
    if (elements.btnFilterIssues) {
        elements.btnFilterIssues.classList.toggle("active", state.inputFilterMode === "issues");
        elements.btnFilterIssues.setAttribute("aria-selected", state.inputFilterMode === "issues");
    }

    // Search and status filtering
    const query = (state.inputSearchQuery || "").toLowerCase().trim();
    let textMatched = allItems;
    if (query) {
        textMatched = allItems.filter((i) =>
            (i.display_name || "").toLowerCase().includes(query) ||
            (i.source_path || "").toLowerCase().includes(query)
        );
    }

    let matchingItems = textMatched;
    if (state.inputFilterMode === "eligible") {
        matchingItems = textMatched.filter((i) => i.is_eligible);
    } else if (state.inputFilterMode === "issues") {
        matchingItems = textMatched.filter((i) => !i.is_eligible);
    }

    // Pagination
    const pageSize = (state.inputPagination && state.inputPagination.pageSize) || 10;
    const totalPages = Math.max(1, Math.ceil(matchingItems.length / pageSize));
    if (!state.inputPagination) state.inputPagination = { page: 1, pageSize: 10 };
    if (state.inputPagination.page > totalPages) {
        state.inputPagination.page = totalPages;
    }
    if (state.inputPagination.page < 1) {
        state.inputPagination.page = 1;
    }
    const currentPage = state.inputPagination.page;
    const startIndex = (currentPage - 1) * pageSize;
    const itemsToRender = matchingItems.slice(startIndex, startIndex + pageSize);

    if (elements.inputPageIndicator) {
        elements.inputPageIndicator.textContent = `Page ${currentPage} of ${totalPages} (${matchingItems.length} total)`;
    }
    if (elements.btnInputPrev) {
        elements.btnInputPrev.disabled = currentPage <= 1;
    }
    if (elements.btnInputNext) {
        elements.btnInputNext.disabled = currentPage >= totalPages;
    }
    if (elements.inputPaginationContainer) {
        elements.inputPaginationContainer.classList.toggle("hidden", !showTable || matchingItems.length === 0);
    }

    if (!elements.selectedInputsTbody) return;

    if (matchingItems.length === 0) {
        elements.selectedInputsTbody.innerHTML = allItems.length === 0
            ? '<tr class="empty-row"><td colspan="5">No documents selected. Click "Add Files" or "Add Folder" to begin.</td></tr>'
            : '<tr class="empty-row"><td colspan="5">No documents match the filter query.</td></tr>';
    } else {
        const rowsHtml = itemsToRender
            .map((item) => {
                const pathVal = item.source_path || item.display_name;
                const isChecked = state.checkedInputPaths.has(pathVal);
                const issueText = item.issue_reason || "Ineligible";
                const badge = item.is_eligible
                    ? '<span class="badge badge-emerald">Eligible</span>'
                    : `<button type="button" class="badge badge-amber btn-issue-info" tabindex="0" aria-label="Issue: ${escapeHtml(issueText)}" title="${escapeHtml(issueText)}">Issue</button>`;
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
        elements.selectedInputsTbody.innerHTML = rowsHtml;
    }

    // Selection scope and header checkbox state
    const totalMatchingCount = matchingItems.length;
    const checkedMatchingCount = matchingItems.filter((i) => state.checkedInputPaths.has(i.source_path || i.display_name)).length;
    const checkedCurrentPageCount = itemsToRender.filter((i) => state.checkedInputPaths.has(i.source_path || i.display_name)).length;

    if (elements.chkSelectAllInputs) {
        if (totalMatchingCount === 0) {
            elements.chkSelectAllInputs.checked = false;
            elements.chkSelectAllInputs.indeterminate = false;
        } else if (checkedMatchingCount === totalMatchingCount) {
            elements.chkSelectAllInputs.checked = true;
            elements.chkSelectAllInputs.indeterminate = false;
        } else if (checkedMatchingCount > 0) {
            elements.chkSelectAllInputs.checked = false;
            elements.chkSelectAllInputs.indeterminate = true;
        } else {
            elements.chkSelectAllInputs.checked = false;
            elements.chkSelectAllInputs.indeterminate = false;
        }
    }

    if (elements.selectionScopeBanner) {
        if (showTable && totalMatchingCount > itemsToRender.length && checkedCurrentPageCount === itemsToRender.length && itemsToRender.length > 0 && checkedMatchingCount < totalMatchingCount) {
            elements.selectionScopeBanner.classList.remove("hidden");
            if (elements.selectionScopeText) {
                elements.selectionScopeText.textContent = `All ${itemsToRender.length} documents on this page selected.`;
            }
            if (elements.btnSelectAllMatching) {
                elements.btnSelectAllMatching.textContent = `Select all ${totalMatchingCount} matching documents`;
                elements.btnSelectAllMatching.classList.remove("hidden");
            }
            if (elements.btnClearSelectionScope) {
                elements.btnClearSelectionScope.textContent = "Clear selection";
                elements.btnClearSelectionScope.classList.remove("hidden");
            }
        } else if (showTable && totalMatchingCount > itemsToRender.length && checkedMatchingCount === totalMatchingCount && totalMatchingCount > 0) {
            elements.selectionScopeBanner.classList.remove("hidden");
            if (elements.selectionScopeText) {
                elements.selectionScopeText.textContent = `All ${totalMatchingCount} matching documents selected.`;
            }
            if (elements.btnSelectAllMatching) {
                elements.btnSelectAllMatching.classList.add("hidden");
            }
            if (elements.btnClearSelectionScope) {
                elements.btnClearSelectionScope.textContent = "Clear selection";
                elements.btnClearSelectionScope.classList.remove("hidden");
            }
        } else {
            elements.selectionScopeBanner.classList.add("hidden");
        }
    }

    updateClearSelectedButton();
}

export function renderPreflight(preflight) {
    if (!elements.preflightSummary) return;
    elements.preflightSummary.textContent = `${preflight.eligible_count} eligible, ${preflight.issue_count} issues`;
    if (elements.btnStartRun && preflight.eligible_count === 0) {
        elements.btnStartRun.disabled = true;
    }
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

export function buildRequestPayload() {
    const customOpts = {};
    let profile = "instant";

    const act = (state.availableActions || []).find((a) => a.action_id === state.currentRequirement);
    if (act && act.parameters) {
        act.parameters.forEach((p) => {
            const draftVal = getDraftParam(act.action_id, p.parameter_id, p.default_value);
            if (p.kind === "select") {
                if (p.parameter_id === "profile") {
                    profile = draftVal || "instant";
                } else if (draftVal !== undefined && draftVal !== "") {
                    customOpts[p.parameter_id] = draftVal;
                }
            } else if (p.kind === "toggle") {
                customOpts[p.parameter_id] = Boolean(draftVal);
            }
        });
    }

    if (state.currentRequirement === "ocr" && profile === "custom") {
        customOpts.engine = "rapidocr";
    }

    return {
        paths: state.selectedPaths,
        requirement: state.currentRequirement,
        profile: profile,
        recursive: state.isRecursive,
        custom_options: customOpts,
    };
}

export function renderAvailableActions(actions) {
    if (!elements.requirementGrid) return;
    if (!actions || actions.length === 0) {
        state.availableActions = [];
        elements.requirementGrid.innerHTML = '<div class="text-muted" style="padding: 12px;">No processing capabilities available.</div>';
        if (elements.actionParamsContainer) {
            elements.actionParamsContainer.classList.add("hidden");
            elements.actionParamsContainer.innerHTML = "";
        }
        if (elements.btnStartRun) elements.btnStartRun.disabled = true;
        return;
    }
    state.availableActions = actions;

    // Check if the current action is still available
    let activeAction = actions.find((a) => a.action_id === state.currentRequirement);
    if (!activeAction || !activeAction.is_enabled) {
        const firstEnabled = actions.find((a) => a.is_enabled);
        if (firstEnabled) {
            state.currentRequirement = firstEnabled.action_id;
            activeAction = firstEnabled;
        }
    }

    // Check if DOM cards need full replacement or just in-place update
    const existingCards = elements.requirementGrid.querySelectorAll(".req-card");
    const existingIds = Array.from(existingCards).map((c) => c.dataset.req).join(",");
    const newIds = actions.map((a) => a.action_id).join(",");

    if (existingIds === newIds && existingCards.length > 0) {
        // In-place update to preserve elements and focus
        actions.forEach((act) => {
            const card = elements.requirementGrid.querySelector(`.req-card[data-req="${act.action_id}"]`);
            if (card) {
                const isActive = act.action_id === state.currentRequirement;
                const isDisabled = !act.is_enabled;
                card.classList.toggle("selected", isActive);
                card.classList.toggle("active", isActive);
                card.classList.toggle("disabled", isDisabled);
                card.disabled = isDisabled;
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
    } else {
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
    }

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

    const activeElId = document.activeElement ? document.activeElement.id : null;
    elements.actionParamsContainer.classList.remove("hidden");

    const selects = action.parameters.filter((p) => p.kind === "select");
    const toggles = action.parameters.filter((p) => p.kind === "toggle");

    let hasInvalidParam = false;
    let html = "";
    if (selects.length > 0) {
        html += selects
            .map((p) => {
                const draftVal = getDraftParam(action.action_id, p.parameter_id, p.default_value);
                const isOptionValid = (p.options || []).some(([val]) => val === draftVal);
                if (!isOptionValid && draftVal !== undefined && draftVal !== null) {
                    hasInvalidParam = true;
                }
                const optsHtml = (p.options || [])
                    .map(([val, text]) => `<option value="${escapeHtml(val)}" ${val === draftVal ? "selected" : ""}>${escapeHtml(text)}</option>`)
                    .join("");
                return `
                    <div class="form-row" style="margin-bottom: 8px;">
                        <label class="form-label" style="font-weight: 600; font-size: 0.85rem;">${escapeHtml(p.display_name)}</label>
                        <select class="form-select action-param-select ${!isOptionValid ? "is-invalid" : ""}" data-param="${escapeHtml(p.parameter_id)}" id="param-${escapeHtml(p.parameter_id)}">
                            ${optsHtml}
                        </select>
                        ${!isOptionValid ? `<div class="text-danger" style="font-size: 0.78rem; margin-top: 2px;">Selected option "${escapeHtml(draftVal)}" is no longer available.</div>` : ""}
                    </div>
                `;
            })
            .join("");
    }

    if (toggles.length > 0) {
        const currentProfile = getDraftParam(action.action_id, "profile", "instant");
        const isProfileCustom = !selects.some((p) => p.parameter_id === "profile") || currentProfile === "custom";
        const togglesHtml = toggles
            .map((t) => {
                const draftVal = Boolean(getDraftParam(action.action_id, t.parameter_id, t.default_value));
                return `
                    <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                        <input type="checkbox" class="action-param-toggle" data-param="${escapeHtml(t.parameter_id)}" id="param-${escapeHtml(t.parameter_id)}" ${draftVal ? "checked" : ""}>
                        <span>${escapeHtml(t.display_name)}</span>
                    </label>
                `;
            })
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

    if (activeElId) {
        const el = document.getElementById(activeElId);
        if (el) el.focus();
    }

    if (hasInvalidParam && elements.btnStartRun) {
        elements.btnStartRun.disabled = true;
    }
}

export async function previewPlan() {
    if (state.selectedPaths.length === 0 || !elements.preflightPlanPreview) return;

    const reqSeq = ++state.requestSeq;
    const payload = buildRequestPayload();

    const res = await apiPost("/api/plan/preview", payload);
    if (reqSeq !== state.requestSeq) return;

    if (res.ok && res.stages) {
        elements.preflightPlanPreview.classList.remove("hidden");
        const stagesHtml = res.stages
            .map((s) => `<span class="badge badge-indigo" style="font-size: 0.72rem; padding: 2px 6px;">${escapeHtml(s.name)}</span>`)
            .join(" ➔ ");
        const devHtml = (res.devices || [])
            .map((d) => `<span class="badge ${d.is_available ? 'badge-emerald' : 'badge-amber'}" style="font-size: 0.72rem; padding: 2px 6px;">${escapeHtml(d.device_type)}</span>`)
            .join(" ");
        elements.preflightPlanPreview.innerHTML = `
            <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.08);">
                <div style="font-size: 0.75rem; font-weight: 600; color: var(--text-muted); margin-bottom: 4px;">PLANNED PIPELINE (${res.document_count} docs)</div>
                <div style="display: flex; gap: 4px; flex-wrap: wrap; align-items: center; margin-bottom: 4px;">${stagesHtml}</div>
                ${devHtml ? `<div style="font-size: 0.75rem; color: var(--text-muted);">DEVICES: ${devHtml}</div>` : ''}
            </div>
        `;
    } else {
        elements.preflightPlanPreview.classList.add("hidden");
        elements.preflightPlanPreview.innerHTML = "";
    }
}

export async function handleStartRun() {
    if (state.selectedPaths.length === 0 || !elements.btnStartRun) return;

    elements.btnStartRun.disabled = true;
    hideError();

    const payload = buildRequestPayload();
    const res = await apiPost("/api/runs", payload);

    if (res.ok && res.run_id) {
        state.activeRunId = res.run_id;
        state.activeRunStatus = "RUNNING";
        state.viewedRunId = res.run_id;
        state.followLive = true;
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

    if (elements.actionParamsContainer) {
        elements.actionParamsContainer.addEventListener("change", (e) => {
            const select = e.target.closest(".action-param-select");
            if (select) {
                const paramId = select.dataset.param;
                setDraftParam(state.currentRequirement, paramId, select.value);
                if (paramId === "profile") {
                    state.currentProfile = select.value;
                    const togglesGroup = document.getElementById("dynamic-toggles-group");
                    if (togglesGroup) togglesGroup.classList.toggle("hidden", select.value !== "custom");
                }
                previewPlan();
                return;
            }

            const toggle = e.target.closest(".action-param-toggle");
            if (toggle) {
                const paramId = toggle.dataset.param;
                setDraftParam(state.currentRequirement, paramId, toggle.checked);
                previewPlan();
                return;
            }
        });
    }

    if (elements.btnViewAllInputs) {
        elements.btnViewAllInputs.addEventListener("click", () => {
            state.showAllInputsTable = true;
            renderInputsTable();
        });
    }

    if (elements.btnCollapseInputs) {
        elements.btnCollapseInputs.addEventListener("click", () => {
            state.showAllInputsTable = false;
            renderInputsTable();
        });
    }

    if (elements.btnFilterAll) {
        elements.btnFilterAll.addEventListener("click", () => {
            state.inputFilterMode = "all";
            state.inputPagination.page = 1;
            renderInputsTable();
        });
    }

    if (elements.btnFilterEligible) {
        elements.btnFilterEligible.addEventListener("click", () => {
            state.inputFilterMode = "eligible";
            state.inputPagination.page = 1;
            renderInputsTable();
        });
    }

    if (elements.btnFilterIssues) {
        elements.btnFilterIssues.addEventListener("click", () => {
            state.inputFilterMode = "issues";
            state.inputPagination.page = 1;
            renderInputsTable();
        });
    }

    if (elements.btnInputPrev) {
        elements.btnInputPrev.addEventListener("click", () => {
            if (state.inputPagination && state.inputPagination.page > 1) {
                state.inputPagination.page--;
                renderInputsTable();
            }
        });
    }

    if (elements.btnInputNext) {
        elements.btnInputNext.addEventListener("click", () => {
            if (!state.inputPagination) state.inputPagination = { page: 1, pageSize: 10 };
            state.inputPagination.page++;
            renderInputsTable();
        });
    }

    if (elements.btnSelectAllMatching) {
        elements.btnSelectAllMatching.addEventListener("click", () => {
            const allItems = state.intakeItems || [];
            const query = (state.inputSearchQuery || "").toLowerCase().trim();
            let matching = query
                ? allItems.filter((i) => (i.display_name || "").toLowerCase().includes(query) || (i.source_path || "").toLowerCase().includes(query))
                : allItems;
            if (state.inputFilterMode === "eligible") {
                matching = matching.filter((i) => i.is_eligible);
            } else if (state.inputFilterMode === "issues") {
                matching = matching.filter((i) => !i.is_eligible);
            }
            matching.forEach((i) => {
                const p = i.source_path || i.display_name;
                if (p) state.checkedInputPaths.add(p);
            });
            updateClearSelectedButton();
            renderInputsTable();
        });
    }

    if (elements.btnClearSelectionScope) {
        elements.btnClearSelectionScope.addEventListener("click", () => {
            const allItems = state.intakeItems || [];
            const query = (state.inputSearchQuery || "").toLowerCase().trim();
            let matching = query
                ? allItems.filter((i) => (i.display_name || "").toLowerCase().includes(query) || (i.source_path || "").toLowerCase().includes(query))
                : allItems;
            if (state.inputFilterMode === "eligible") {
                matching = matching.filter((i) => i.is_eligible);
            } else if (state.inputFilterMode === "issues") {
                matching = matching.filter((i) => !i.is_eligible);
            }
            matching.forEach((i) => {
                const p = i.source_path || i.display_name;
                if (p) state.checkedInputPaths.delete(p);
            });
            updateClearSelectedButton();
            renderInputsTable();
        });
    }

    if (elements.chkSelectAllInputs) {
        elements.chkSelectAllInputs.addEventListener("change", (e) => {
            const allItems = state.intakeItems || [];
            const query = (state.inputSearchQuery || "").toLowerCase().trim();
            let matching = query
                ? allItems.filter((i) => (i.display_name || "").toLowerCase().includes(query) || (i.source_path || "").toLowerCase().includes(query))
                : allItems;
            if (state.inputFilterMode === "eligible") {
                matching = matching.filter((i) => i.is_eligible);
            } else if (state.inputFilterMode === "issues") {
                matching = matching.filter((i) => !i.is_eligible);
            }

            const pageSize = (state.inputPagination && state.inputPagination.pageSize) || 10;
            const currentPage = (state.inputPagination && state.inputPagination.page) || 1;
            const pageItems = matching.slice((currentPage - 1) * pageSize, currentPage * pageSize);

            const isChecked = e.target.checked;
            if (isChecked) {
                pageItems.forEach((it) => {
                    const p = it.source_path || it.display_name;
                    if (p) state.checkedInputPaths.add(p);
                });
            } else {
                pageItems.forEach((it) => {
                    const p = it.source_path || it.display_name;
                    if (p) state.checkedInputPaths.delete(p);
                });
            }
            updateClearSelectedButton();
            renderInputsTable();
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
                renderInputsTable();
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
                if (target) openDocumentPreview(target, name, pathVal);
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
                previewPlan();
            }
        });
    }

    if (elements.inputFilesFilter) {
        elements.inputFilesFilter.addEventListener("input", (e) => {
            state.inputSearchQuery = e.target.value;
            if (state.inputPagination) state.inputPagination.page = 1;
            renderInputsTable();
        });
    }
}
