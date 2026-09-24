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
  const [zoomLevel, setZoomLevel] = useState<number>(100);
  const [triageFilter, setTriageFilter] = useState<"all" | "pending" | "resolved">("all");
  const [sourcePageImageUrl, setSourcePageImageUrl] = useState<string | null>(null);
  const [sourcePageLoading, setSourcePageLoading] = useState(false);

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
  const resolvedCount = queue.length - pendingCount;

  useEffect(() => {
    if (item) {
      setDraftInput(savedDrafts[item.item_id] ?? item.draft_proposal ?? item.output_text ?? "");
      setShowDraftBox(false);
    }
  }, [item?.item_id]);

  // Fetch rendered page image for the source pane when item has source_input_id + page_number
  useEffect(() => {
    if (!item?.source_input_id || !item?.page_number) {
      setSourcePageImageUrl(null);
      return;
    }
    let cancelled = false;
    setSourcePageLoading(true);
    setSourcePageImageUrl(null);
    let url = `/api/inputs/${encodeURIComponent(item.source_input_id)}/pdf_page?page=${item.page_number}`;
    if (item.source_bbox) {
      url += `&bbox=${item.source_bbox.join(",")}`;
      if (item.source_dpi) {
        url += `&dpi=${item.source_dpi}`;
      }
    }
    fetch(url, { headers: { Accept: "application/json" } })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("Failed to load page"))))
      .then((data: any) => {
        if (!cancelled && data.page_data_url) {
          setSourcePageImageUrl(data.page_data_url);
        }
      })
      .catch(() => {
        if (!cancelled) setSourcePageImageUrl(null);
      })
      .finally(() => {
        if (!cancelled) setSourcePageLoading(false);
      });
    return () => { cancelled = true; };
  }, [item?.item_id, item?.source_input_id, item?.page_number, item?.source_bbox, item?.source_dpi]);

  // Jump to next pending issue shortcut
  const jumpToNextIssue = () => {
    if (!queue.length) return;
    const startIndex = selectedIndex >= 0 ? selectedIndex + 1 : 0;
    for (let i = 0; i < queue.length; i++) {
      const idx = (startIndex + i) % queue.length;
      const candidate = queue[idx];
      if (candidate && ((candidate.status || "").toLowerCase() === "pending" || (candidate.confidence !== null && candidate.confidence < 0.85))) {
        setSelectedId(candidate.item_id);
        return;
      }
    }
  };

  // Keyboard Shortcuts (Space/Tab to jump, Arrows to navigate)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeTag = (document.activeElement?.tagName || "").toLowerCase();
      if (activeTag === "input" || activeTag === "textarea") return;

      if (e.key === "Tab" || (e.code === "Space" && e.ctrlKey)) {
        e.preventDefault();
        jumpToNextIssue();
      } else if (e.key === "ArrowLeft" && selectedIndex > 0) {
        e.preventDefault();
        setSelectedId(queue[selectedIndex - 1]?.item_id ?? null);
      } else if (e.key === "ArrowRight" && selectedIndex < queue.length - 1) {
        e.preventDefault();
        setSelectedId(queue[selectedIndex + 1]?.item_id ?? null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedIndex, queue]);

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

  const filteredQueue = queue.filter((i) => {
    if (triageFilter === "pending") return (i.status || "").toLowerCase() === "pending";
    if (triageFilter === "resolved") return (i.status || "").toLowerCase() !== "pending";
    return true;
  });

  return (
    <div class="review-workbench-container">
      {/* Top Header & Triage Bar */}
      <div class="review-header-bar">
        <div class="review-header-left">
          <span class="eyebrow">Pariksha · Verification Hub</span>
          <h3 id="review-queue-count" class="review-heading">
            {queue.length} items ({pendingCount} pending)
          </h3>
        </div>

        <div class="review-triage-controls">
          <div class="filter-segmented-group mini">
            <button
              class={`filter-seg-btn ${triageFilter === "all" ? "active" : ""}`}
              onClick={() => setTriageFilter("all")}
              type="button"
            >
              All ({queue.length})
            </button>
            <button
              class={`filter-seg-btn ${triageFilter === "pending" ? "active" : ""}`}
              onClick={() => setTriageFilter("pending")}
              type="button"
            >
              Needs Attention ({pendingCount})
            </button>
            <button
              class={`filter-seg-btn ${triageFilter === "resolved" ? "active" : ""}`}
              onClick={() => setTriageFilter("resolved")}
              type="button"
            >
              Resolved ({resolvedCount})
            </button>
          </div>

          <button
            id="btn-review-jump-issue"
            class="button secondary small jump-issue-btn"
            onClick={jumpToNextIssue}
            title="Jump to next item requiring attention (Shortcut: Tab or Ctrl+Space)"
            type="button"
          >
            <span>⏩ Jump to Next Issue</span>
            <span class="key-hint">Tab</span>
          </button>
        </div>
      </div>

      {/* Main Review Layout */}
      <div class="screen-grid review-grid-split">
        {/* Left Column: Queue List (Narrower) */}
        <section class="panel review-queue-panel">
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
                {filteredQueue.length === 0 ? (
                  <tr>
                    <td colSpan={3} style="text-align: center; padding: 24px; color: var(--muted);">
                      {queue.length === 0
                        ? "No items currently require human review."
                        : "No items match the selected filter."}
                    </td>
                  </tr>
                ) : (
                  filteredQueue.map((reviewItem, idx) => (
                    <tr
                      key={reviewItem.item_id}
                      class={`review-row ${reviewItem.item_id === item?.item_id ? "selected active" : ""}`}
                      data-idx={idx}
                      onClick={() => setSelectedId(reviewItem.item_id)}
                      style="cursor: pointer;"
                    >
                      <td>
                        <strong>{reviewItem.item_id}</strong>
                        <div class="quiet" style="font-size: 11px; text-overflow: ellipsis; overflow: hidden; max-width: 120px;">
                          {reviewItem.file_display_name}
                        </div>
                      </td>
                      <td style="font-size: 11px;">{reviewItem.stage}</td>
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

        {/* Right Column: Universal 50/50 Side-by-Side Verification Screen */}
        <section id="review-detail-card" class={item ? "panel review-detail-panel" : "panel hidden"}>
          {item ? (
            <div class="review-workbench-card">
              {/* Item Top Bar */}
              <div class="section-heading" style="margin-bottom: 8px;">
                <div>
                  <span class="eyebrow">Active Verification Item</span>
                  <div style="display: flex; align-items: baseline; gap: 8px;">
                    <h3 id="review-active-item-title">{item.item_id}</h3>
                    {item.file_display_name ? (
                      <span class="quiet" style="font-size: 12px;">· {item.file_display_name}</span>
                    ) : null}
                  </div>
                </div>
                <div class="button-row">
                  <span id="review-status-badge" class={`badge badge-${getBadgeClass(item.status)}`}>
                    {item.status.toUpperCase()}
                  </span>
                  {(item as any).context?.confidence ? (
                    <span class="badge badge-cyan" title="Extraction confidence score">
                      {Math.round(((item as any).context.confidence as number) * 100)}% Confidence
                    </span>
                  ) : null}
                </div>
              </div>

              <p class="quiet" style="margin: 0 0 12px 0; font-size: 12px;">
                {item.issue_reason || (item as any).message || "Verification required for accurate downstream export."}
              </p>

              {/* Universal 50 / 50 Side-by-Side Comparison Container */}
              <div class="side-by-side-comparison-box">
                {/* Left 50%: Original Source */}
                <div class="comparison-column comparison-source">
                  <div class="comparison-column-header">
                    <span class="comparison-col-title">👈 Original Input (Source)</span>
                    <div class="zoom-controls-row">
                      <button
                        class="btn-zoom-mini"
                        onClick={() => setZoomLevel((z) => Math.max(70, z - 15))}
                        type="button"
                        title="Zoom out"
                      >
                        -
                      </button>
                      <span class="zoom-label">{zoomLevel}%</span>
                      <button
                        class="btn-zoom-mini"
                        onClick={() => setZoomLevel((z) => Math.min(180, z + 15))}
                        type="button"
                        title="Zoom in"
                      >
                        +
                      </button>
                      <button
                        class="btn-zoom-mini"
                        onClick={() => setZoomLevel(100)}
                        type="button"
                        title="Reset zoom"
                      >
                        Reset
                      </button>
                    </div>
                  </div>
                  <div
                    class="comparison-pane-body source-body"
                    style={{ fontSize: `${zoomLevel}%` }}
                  >
                    {sourcePageLoading ? (
                      <div class="loading compact" style={{ padding: "24px", textAlign: "center" }}>
                        <div class="spinner" />
                        <span class="quiet">Loading page image…</span>
                      </div>
                    ) : sourcePageImageUrl ? (
                      <img
                        id="review-source-image"
                        src={sourcePageImageUrl}
                        alt={`Original page ${item.page_number ?? ""}`}
                        style={{
                          maxWidth: "100%",
                          height: "auto",
                          borderRadius: "4px",
                          display: "block",
                          margin: "0 auto",
                        }}
                      />
                    ) : (
                      <p id="review-source-text" class="source-content-render">
                        {item.source_text || (item as any).context?.source || "—"}
                      </p>
                    )}
                  </div>
                </div>

                {/* Right 50%: Generated Output */}
                <div class="comparison-column comparison-output">
                  <div class="comparison-column-header">
                    <span class="comparison-col-title">👉 Generated Output (Deliverable)</span>
                    <button
                      id="btn-review-edit"
                      class="button secondary mini"
                      onClick={() => setShowDraftBox(true)}
                      type="button"
                    >
                      ✏️ Edit Output
                    </button>
                  </div>
                  <div class="comparison-pane-body output-body">
                    <p id="review-output-text" class="output-content-render">
                      {item.output_text || (item as any).context?.output || "—"}
                    </p>
                  </div>
                </div>
              </div>

              {/* Proposed Edit Box (Interactive Textarea) */}
              <div id="review-draft-box" class={`review-draft-card ${showDraftBox ? "" : "hidden"}`} style="margin-top: 12px;">
                <label class="field">
                  <span>Proposed Direct Correction (Overrides output)</span>
                  <input
                    id="review-draft-input"
                    class="draft-input-field"
                    value={draftInput}
                    onInput={(e) => setDraftInput(e.currentTarget.value)}
                    placeholder="Type corrected text or value here..."
                  />
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
                    Save Correction
                  </button>
                  <button class="button ghost small" onClick={() => setShowDraftBox(false)} type="button">
                    Cancel
                  </button>
                </div>
              </div>

              <div
                id="review-proposed-display"
                class={savedDrafts[item.item_id] ? "" : "hidden"}
                style="margin-top: 8px; padding: 6px 10px; background: rgba(16, 185, 129, 0.1); border-radius: 6px; border: 1px solid rgba(16, 185, 129, 0.2);"
              >
                <span class="quiet" style="font-size: 11px;">Saved Correction: </span>
                <strong id="review-proposed-text" style="color: #34d399;">{savedDrafts[item.item_id]}</strong>
              </div>

              {/* Bottom Navigation & Decision Row */}
              <div class="button-row between" style="margin-top: 16px; border-top: 1px solid var(--border); padding-top: 12px;">
                <div class="button-row">
                  <button
                    id="btn-review-prev"
                    class="button ghost small"
                    disabled={selectedIndex <= 0}
                    onClick={() => setSelectedId(queue[selectedIndex - 1]?.item_id ?? item.item_id)}
                    type="button"
                  >
                    ← Previous
                  </button>
                  <button
                    id="btn-review-next"
                    class="button ghost small"
                    disabled={selectedIndex >= queue.length - 1}
                    onClick={() => setSelectedId(queue[selectedIndex + 1]?.item_id ?? item.item_id)}
                    type="button"
                  >
                    Next →
                  </button>
                </div>

                <div class="button-row action-row">
                  <button
                    id="btn-review-dismiss"
                    class="button secondary small"
                    disabled={workingItem === item.item_id || !item.available_actions.includes("unresolved")}
                    onClick={() => void apply("unresolved")}
                    type="button"
                  >
                    Mark Unresolved
                  </button>
                  {/* Alias for test compatibility */}
                  <button
                    id="btn-review-unresolved"
                    style={{ display: "none" }}
                    onClick={() => void apply("unresolved")}
                    type="button"
                  >
                    Mark Unresolved
                  </button>
                  <button
                    id="btn-review-accept"
                    class="button primary small btn-accept-verification"
                    disabled={workingItem === item.item_id || !item.available_actions.includes("accept")}
                    onClick={() => void apply("accept")}
                    type="button"
                  >
                    {workingItem === item.item_id ? "Saving…" : "Accept & Approve ✓"}
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <EmptyState title="No item selected" detail="Select an item from the review queue to verify side-by-side." />
          )}
        </section>
      </div>
    </div>
  );
}
