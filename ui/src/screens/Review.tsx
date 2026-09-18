import { useEffect, useState } from "preact/hooks";
import { submitReview } from "../api";
import { EmptyState } from "../components/Common";
import type { ApplicationViewState, ReviewItemView } from "../types";

export function Review({
  state,
  onRefresh,
  onError,
}: {
  state: ApplicationViewState;
  onRefresh: () => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const [itemsOverride, setItemsOverride] = useState<ReviewItemView[] | null>(null);
  const queue = itemsOverride ?? state.review_queue;
  const [selectedId, setSelectedId] = useState<string | null>(queue[0]?.item_id ?? null);
  const [workingItem, setWorkingItem] = useState<string | null>(null);
  const [showDraftBox, setShowDraftBox] = useState(false);
  const [draftInput, setDraftInput] = useState("");
  const [savedDrafts, setSavedDrafts] = useState<Record<string, string>>({});

  const loadReviewQueue = async () => {
    try {
      const res = await fetch("/api/review");
      if (res.ok) {
        const payload = await res.json();
        if (Array.isArray(payload.items)) {
          setItemsOverride(payload.items);
          return;
        }
      }
    } catch {
      // fallback
    }
    await onRefresh();
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      (window as any).__sarathi_load_review = loadReviewQueue;
      (window as any).loadReviewQueue = loadReviewQueue;
    }
  });

  useEffect(() => {
    if (queue.length && (!selectedId || !queue.some((i) => i.item_id === selectedId))) {
      setSelectedId(queue[0]?.item_id ?? null);
    }
  }, [queue, selectedId]);

  const selectedIndex = Math.max(0, queue.findIndex((item) => item.item_id === selectedId));
  const item = queue.length ? queue[selectedIndex] ?? null : null;
  const runId = state.active_run?.run_id ?? state.terminal_summary?.run_id ?? "";
  const pendingCount = queue.filter((i) => (i.status || "").toLowerCase() === "pending").length;

  useEffect(() => {
    if (item) {
      setDraftInput(savedDrafts[item.item_id] ?? item.draft_proposal ?? item.output_text ?? "");
      setShowDraftBox(false);
    }
  }, [item?.item_id]);

  const apply = async (action: "accept" | "unresolved") => {
    if (!item) return;
    setWorkingItem(item.item_id);
    onError(null);
    try {
      await submitReview(runId, item.item_id, item.attempt_id, action);
      await onRefresh();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Unable to submit review action.");
    } finally {
      setWorkingItem(null);
    }
  };

  const getBadgeClass = (status: string) => {
    const s = (status || "").toLowerCase();
    if (s === "accepted") return "emerald";
    if (s === "unresolved") return "crimson";
    return "amber";
  };

  return (
    <div class="screen-grid">
      <section class="panel">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Human review</span>
            <h3 id="review-queue-count">
              {queue.length} items ({pendingCount} pending)
            </h3>
          </div>
        </div>
        <div class="table-container">
          <table class="data-table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Stage</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody id="review-queue-tbody">
              {queue.length === 0 ? (
                <tr>
                  <td colSpan={3} style="text-align: center; padding: 24px; color: var(--muted);">
                    No items currently require human review.
                  </td>
                </tr>
              ) : (
                queue.map((reviewItem, idx) => (
                  <tr
                    key={reviewItem.item_id}
                    class={`review-row ${reviewItem.item_id === item?.item_id ? "selected active" : ""}`}
                    data-idx={idx}
                    onClick={() => setSelectedId(reviewItem.item_id)}
                    style="cursor: pointer;"
                  >
                    <td>
                      <strong>{reviewItem.item_id}</strong>
                      <div class="quiet">{reviewItem.file_display_name}</div>
                    </td>
                    <td>{reviewItem.stage}</td>
                    <td>
                      <span class={`badge badge-${getBadgeClass(reviewItem.status)}`}>
                        {reviewItem.status.toUpperCase()}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section id="review-detail-card" class={`panel ${item ? "" : "hidden"}`}>
        {item ? (
          <>
            <div class="section-heading">
              <div>
                <span class="eyebrow">Review item</span>
                <h3 id="review-active-item-title">{item.item_id}</h3>
              </div>
              <span id="review-status-badge" class={`badge badge-${getBadgeClass(item.status)}`}>
                {item.status.toUpperCase()}
              </span>
            </div>
            <p class="quiet">{item.issue_reason || (item as any).message || "Review required."}</p>
            <div class="review-text">
              <div>
                <span>Source</span>
                <p id="review-source-text">{item.source_text || (item as any).context?.source || "—"}</p>
              </div>
              <div>
                <span>Output</span>
                <p id="review-output-text">{item.output_text || (item as any).context?.output || "—"}</p>
              </div>
            </div>

            <div style="margin-top: 12px;">
              <button
                id="btn-review-edit"
                class="button secondary small"
                onClick={() => setShowDraftBox(true)}
                type="button"
              >
                Propose Edit
              </button>
            </div>

            <div id="review-draft-box" class={`review-draft-card ${showDraftBox ? "" : "hidden"}`}>
              <label class="field">
                <span>Proposed correction</span>
                <input id="review-draft-input" value={draftInput} onInput={(e) => setDraftInput(e.currentTarget.value)} />
              </label>
              <div class="button-row">
                <button
                  id="btn-review-save-draft"
                  class="button secondary small"
                  onClick={() => {
                    setSavedDrafts((prev) => ({ ...prev, [item.item_id]: draftInput }));
                    setShowDraftBox(false);
                  }}
                  type="button"
                >
                  Save Draft
                </button>
                <button class="button ghost small" onClick={() => setShowDraftBox(false)} type="button">
                  Cancel
                </button>
              </div>
            </div>

            <div
              id="review-proposed-display"
              class={savedDrafts[item.item_id] ? "" : "hidden"}
              style="margin-top: 10px;"
            >
              <span class="quiet">Proposed: </span>
              <strong id="review-proposed-text">{savedDrafts[item.item_id]}</strong>
            </div>

            <div class="button-row between" style="margin-top: 18px;">
              <div class="button-row">
                <button
                  id="btn-review-prev"
                  class="button ghost"
                  disabled={selectedIndex <= 0}
                  onClick={() => setSelectedId(queue[selectedIndex - 1]?.item_id ?? item.item_id)}
                  type="button"
                >
                  Previous
                </button>
                <button
                  id="btn-review-next"
                  class="button ghost"
                  disabled={selectedIndex >= queue.length - 1}
                  onClick={() => setSelectedId(queue[selectedIndex + 1]?.item_id ?? item.item_id)}
                  type="button"
                >
                  Next
                </button>
              </div>
            </div>

            <div class="button-row action-row" style="margin-top: 16px;">
              <button
                id="btn-review-accept"
                class="button primary"
                disabled={workingItem === item.item_id || !item.available_actions.includes("accept")}
                onClick={() => void apply("accept")}
                type="button"
              >
                Accept
              </button>
              <button
                id="btn-review-dismiss"
                class="button secondary"
                disabled={workingItem === item.item_id || !item.available_actions.includes("unresolved")}
                onClick={() => void apply("unresolved")}
                type="button"
              >
                Mark Unresolved
              </button>
            </div>
          </>
        ) : (
          <EmptyState title="No item selected" detail="Select an item from the review queue." />
        )}
      </section>
    </div>
  );
}
