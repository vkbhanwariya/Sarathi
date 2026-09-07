/**
 * Screen 3: Pariksha (Review & Exceptions Workbench) Controller for Mukha.
 */

import { apiGet, apiPost } from "../api.js";
import { elements, showError } from "../dom.js";
import { escapeHtml } from "../formatters.js";
import { state } from "../state.js";

let currentItems = [];

export async function loadReviewQueue() {
    const res = await apiGet("/api/review");
    if (!res.ok) return;

    const items = res.items || [];
    currentItems = items;
    if (elements.reviewQueueCount) {
        elements.reviewQueueCount.textContent = `${items.length} items`;
    }
    if (elements.reviewBadge) {
        elements.reviewBadge.textContent = items.length;
        elements.reviewBadge.classList.toggle("hidden", items.length === 0);
    }

    if (!elements.reviewQueueTbody) return;

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

export function selectReviewItem(item) {
    if (!item || !elements.reviewDetailCard) return;
    state.selectedReviewItem = item;
    elements.reviewDetailCard.classList.remove("hidden");
    if (elements.reviewActiveItemTitle) {
        elements.reviewActiveItemTitle.textContent = item.item_id || "Review Item";
    }

    if (elements.reviewSourceText) {
        elements.reviewSourceText.textContent = item.context && item.context.source ? item.context.source : "(Source snippet unavailable)";
    }
    if (elements.reviewOutputText) {
        elements.reviewOutputText.textContent = item.context && item.context.output ? item.context.output : (item.message || "—");
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
    const attemptId = state.selectedReviewItem.attempt_id || "att-1";
    const payload = {
        item_id: itemId,
        attempt_id: attemptId,
        action_id: action,
        action: action,
    };
    if (proposedValue !== null && proposedValue !== undefined) {
        payload.proposed_value = proposedValue;
    }
    const res = await apiPost("/api/review", payload);
    if (res.ok) {
        loadReviewQueue();
    } else {
        showError(res.error || `Failed to apply review action ${action}`);
    }
}

export function initReviewScreen() {
    if (elements.btnReviewAccept) {
        elements.btnReviewAccept.addEventListener("click", () => handleReviewAction("accept"));
    }
    if (elements.btnReviewEdit) {
        elements.btnReviewEdit.addEventListener("click", () => {
            if (!state.selectedReviewItem) return;
            const currentVal = state.selectedReviewItem.context && state.selectedReviewItem.context.output
                ? state.selectedReviewItem.context.output
                : "";
            const val = prompt("Edit output value:", currentVal);
            if (val !== null) {
                handleReviewAction("validate_edit", val);
            }
        });
    }
    if (elements.btnReviewDismiss) {
        elements.btnReviewDismiss.addEventListener("click", () => handleReviewAction("unresolved"));
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
