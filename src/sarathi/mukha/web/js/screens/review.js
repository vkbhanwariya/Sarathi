/**
 * Screen 3: Pariksha (Review & Exceptions Workbench) Controller for Mukha.
 */

import { apiGet, apiPost } from "../api.js";
import { elements, showError } from "../dom.js";
import { escapeHtml, formatStatus } from "../formatters.js";
import { state } from "../state.js";

let currentItems = [];

export async function loadReviewQueue() {
    const runId = state.viewedRunId || state.activeRunId;
    const url = runId ? `/api/runs/${encodeURIComponent(runId)}/review` : "/api/review";
    const res = await apiGet(url);
    if (!res.ok) return;

    const items = res.items || [];
    currentItems = items;

    const pendingCount = items.filter((i) => (i.status || "pending") === "pending").length;

    if (elements.reviewQueueCount) {
        elements.reviewQueueCount.textContent = `${items.length} items (${pendingCount} pending)`;
    }
    if (elements.reviewBadge) {
        elements.reviewBadge.textContent = pendingCount;
        elements.reviewBadge.classList.toggle("hidden", pendingCount === 0);
    }

    if (!elements.reviewQueueTbody) return;

    if (items.length === 0) {
        elements.reviewQueueTbody.innerHTML = '<tr class="empty-row"><td colspan="6">No items currently require human review.</td></tr>';
        if (elements.reviewDetailCard) elements.reviewDetailCard.classList.add("hidden");
        state.selectedReviewItem = null;
        return;
    }

    elements.reviewQueueTbody.innerHTML = items
        .map((it, idx) => {
            const st = (it.status || "pending").toLowerCase();
            const badgeClass = st === "accepted" ? "badge-emerald" : (st === "unresolved" ? "badge-crimson" : "badge-amber");
            const badgeText = st.toUpperCase();
            return `
                <tr class="review-row" data-idx="${idx}" style="cursor: pointer;">
                    <td><strong class="code-text">${escapeHtml(it.item_id || `rev-${idx + 1}`)}</strong></td>
                    <td>${escapeHtml(it.context && it.context.file ? it.context.file : "—")}</td>
                    <td><span class="badge badge-indigo">${escapeHtml(it.stage || "—")}</span></td>
                    <td>${it.context && it.context.confidence ? `${(it.context.confidence * 100).toFixed(1)}%` : "—"}</td>
                    <td><span class="badge ${badgeClass}">${badgeText}</span> — ${escapeHtml(it.message || it.code || "Review needed")}</td>
                    <td style="text-align: center;">
                        <button class="btn btn-primary btn-sm btn-inspect-review" data-idx="${idx}">Inspect</button>
                    </td>
                </tr>
            `;
        })
        .join("");

    // Preserve selection across queue updates
    let selected = null;
    if (state.selectedReviewItem) {
        selected = items.find((i) => i.item_id === state.selectedReviewItem.item_id);
    }
    if (!selected && items.length > 0) {
        selected = items[0];
    }
    selectReviewItem(selected);
}

export function selectReviewItem(item) {
    if (!item || !elements.reviewDetailCard) return;
    state.selectedReviewItem = item;
    elements.reviewDetailCard.classList.remove("hidden");

    if (elements.reviewActiveItemTitle) {
        elements.reviewActiveItemTitle.textContent = item.item_id || "Review Item";
    }

    const st = (item.status || "pending").toLowerCase();
    if (elements.reviewStatusBadge) {
        elements.reviewStatusBadge.textContent = st.toUpperCase();
        elements.reviewStatusBadge.className = st === "accepted" ? "badge badge-emerald" : (st === "unresolved" ? "badge badge-crimson" : "badge badge-amber");
    }

    if (elements.reviewSourceText) {
        elements.reviewSourceText.textContent = item.context && item.context.source ? item.context.source : "(Source snippet unavailable)";
    }
    if (elements.reviewOutputText) {
        elements.reviewOutputText.textContent = item.context && item.context.output ? item.context.output : (item.message || "—");
    }

    // Display draft proposal if present without altering committed output
    if (elements.reviewProposedDisplay && elements.reviewProposedText) {
        if (item.draft_proposal) {
            elements.reviewProposedDisplay.classList.remove("hidden");
            elements.reviewProposedText.textContent = item.draft_proposal;
        } else {
            elements.reviewProposedDisplay.classList.add("hidden");
            elements.reviewProposedText.textContent = "—";
        }
    }

    // Hide inline draft editing box when switching items
    if (elements.reviewDraftBox) {
        elements.reviewDraftBox.classList.add("hidden");
    }

    // Enable/disable supported action buttons based on available_actions
    const actions = item.available_actions || ["accept", "unresolved"];
    if (elements.btnReviewAccept) {
        elements.btnReviewAccept.disabled = !actions.includes("accept") || item.status === "accepted";
    }
    if (elements.btnReviewDismiss) {
        elements.btnReviewDismiss.disabled = !actions.includes("unresolved") || item.status === "unresolved";
    }

    // Previous / Next button state
    const currentIndex = currentItems.findIndex((i) => i.item_id === item.item_id);
    if (elements.btnReviewPrev) {
        elements.btnReviewPrev.disabled = currentIndex <= 0;
    }
    if (elements.btnReviewNext) {
        elements.btnReviewNext.disabled = currentIndex < 0 || currentIndex >= currentItems.length - 1;
    }

    const conf = item.context && item.context.confidence !== undefined ? item.context.confidence : null;
    if (elements.reviewConfidenceText && elements.reviewConfidenceFill) {
        if (conf !== null && conf !== undefined) {
            const pct = Math.round(conf * 100);
            elements.reviewConfidenceText.textContent = `${pct}%`;
            elements.reviewConfidenceFill.style.width = `${pct}%`;
            elements.reviewConfidenceFill.style.background = pct >= 90 ? "var(--accent-emerald)" : (pct >= 75 ? "var(--accent-amber)" : "var(--accent-crimson)");
        } else {
            elements.reviewConfidenceText.textContent = "—";
            elements.reviewConfidenceFill.style.width = "0%";
        }
    }
}

export async function handleReviewAction(action, proposedValue = null) {
    if (!state.selectedReviewItem) return;
    const itemId = state.selectedReviewItem.item_id;
    const attemptId = state.selectedReviewItem.attempt_id;

    if (!attemptId) {
        showError("Cannot submit review intent: missing attempt identity.");
        return;
    }

    const payload = {
        item_id: itemId,
        attempt_id: attemptId,
        action_id: action,
        action: action,
        run_id: state.viewedRunId || state.activeRunId || null,
    };
    if (proposedValue !== null && proposedValue !== undefined) {
        payload.proposed_value = proposedValue;
    }

    const res = await apiPost("/api/review", payload);
    if (res.ok) {
        await loadReviewQueue();
    } else {
        showError(res.error || `Failed to apply review action ${action}`);
    }
}

export function initReviewScreen() {
    if (elements.btnReviewAccept) {
        elements.btnReviewAccept.addEventListener("click", () => handleReviewAction("accept"));
    }
    if (elements.btnReviewDismiss) {
        elements.btnReviewDismiss.addEventListener("click", () => handleReviewAction("unresolved"));
    }

    if (elements.btnReviewPrev) {
        elements.btnReviewPrev.addEventListener("click", () => {
            if (!state.selectedReviewItem) return;
            const idx = currentItems.findIndex((i) => i.item_id === state.selectedReviewItem.item_id);
            if (idx > 0) {
                selectReviewItem(currentItems[idx - 1]);
            }
        });
    }

    if (elements.btnReviewNext) {
        elements.btnReviewNext.addEventListener("click", () => {
            if (!state.selectedReviewItem) return;
            const idx = currentItems.findIndex((i) => i.item_id === state.selectedReviewItem.item_id);
            if (idx >= 0 && idx < currentItems.length - 1) {
                selectReviewItem(currentItems[idx + 1]);
            }
        });
    }

    if (elements.btnReviewEdit) {
        elements.btnReviewEdit.addEventListener("click", () => {
            if (!state.selectedReviewItem || !elements.reviewDraftBox) return;
            elements.reviewDraftBox.classList.remove("hidden");
            if (elements.reviewDraftInput) {
                elements.reviewDraftInput.value = state.selectedReviewItem.draft_proposal || (state.selectedReviewItem.context && state.selectedReviewItem.context.output) || "";
                elements.reviewDraftInput.focus();
            }
        });
    }

    if (elements.btnReviewCancelDraft) {
        elements.btnReviewCancelDraft.addEventListener("click", () => {
            if (elements.reviewDraftBox) {
                elements.reviewDraftBox.classList.add("hidden");
            }
        });
    }

    if (elements.btnReviewSaveDraft) {
        elements.btnReviewSaveDraft.addEventListener("click", () => {
            if (!state.selectedReviewItem) return;
            const val = elements.reviewDraftInput ? elements.reviewDraftInput.value.trim() : "";
            state.selectedReviewItem.draft_proposal = val || null;
            if (elements.reviewProposedDisplay && elements.reviewProposedText) {
                if (val) {
                    elements.reviewProposedDisplay.classList.remove("hidden");
                    elements.reviewProposedText.textContent = val;
                } else {
                    elements.reviewProposedDisplay.classList.add("hidden");
                    elements.reviewProposedText.textContent = "—";
                }
            }
            if (elements.reviewDraftBox) {
                elements.reviewDraftBox.classList.add("hidden");
            }
        });
    }

    if (elements.reviewQueueTbody) {
        elements.reviewQueueTbody.addEventListener("click", (e) => {
            const row = e.target.closest(".review-row");
            if (row && row.dataset.idx !== undefined) {
                const idx = parseInt(row.dataset.idx, 10);
                if (currentItems[idx]) {
                    selectReviewItem(currentItems[idx]);
                }
            }
        });
    }
}
