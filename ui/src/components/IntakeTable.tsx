import { RefObject } from "preact";
import { formatBytes } from "../formatters";
import type { InputFilter, InputItemView } from "../types";

export interface IntakeTableProps {
  visibleItems: InputItemView[];
  filteredItems: InputItemView[];
  pagedItems: InputItemView[];
  checkedPaths: Set<string>;
  totalSize: number;
  eligibleCount: number;
  issueCount: number;
  query: string;
  filter: InputFilter;
  page: number;
  pageCount: number;
  showAllInputsTable: boolean;
  showGroupedSummary: boolean;
  selectAllRef: RefObject<HTMLInputElement>;
  isAllPagedChecked: boolean;
  onQueryChange: (query: string) => void;
  onFilterChange: (filter: InputFilter) => void;
  onSetShowAll: (show: boolean) => void;
  onSetPage: (page: number) => void;
  onToggleSelectAllPaged: (checked: boolean) => void;
  onToggleItemChecked: (itemKey: string, checked: boolean) => void;
  onSelectAllMatching: () => void;
  onClearChecked: () => void;
  onPreview: (pathOrUrl: string, displayName: string) => void;
  onRemoveItem: (item: InputItemView) => void;
}

export function IntakeTable({
  visibleItems,
  filteredItems,
  pagedItems,
  checkedPaths,
  totalSize,
  eligibleCount,
  issueCount,
  query,
  filter,
  page,
  pageCount,
  showAllInputsTable,
  showGroupedSummary,
  selectAllRef,
  isAllPagedChecked,
  onQueryChange,
  onFilterChange,
  onSetShowAll,
  onSetPage,
  onToggleSelectAllPaged,
  onToggleItemChecked,
  onSelectAllMatching,
  onClearChecked,
  onPreview,
  onRemoveItem,
}: IntakeTableProps) {
  const pageSize = 10;
  const currentPage = Math.min(page, pageCount);

  return (
    <div class="intake-table-section">
      {/* Search & Filter Badges */}
      <div class="intake-search-filter-row">
        <div class="search-input-wrap">
          <svg class="search-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            id="input-files-filter"
            class="filter-search-input"
            placeholder="Search selected documents..."
            value={query}
            onInput={(event) => onQueryChange(event.currentTarget.value)}
          />
        </div>
        <div class="filter-segmented-group">
          <button
            id="btn-filter-all"
            class={filter === "all" ? "filter-seg-btn active" : "filter-seg-btn"}
            onClick={() => onFilterChange("all")}
            type="button"
          >
            All <span id="filter-all-count">{visibleItems.length}</span>
          </button>
          <button
            id="btn-filter-eligible"
            class={filter === "eligible" ? "filter-seg-btn active" : "filter-seg-btn"}
            onClick={() => onFilterChange("eligible")}
            type="button"
          >
            Eligible <span id="filter-eligible-count">{eligibleCount}</span>
          </button>
          <button
            id="btn-filter-issues"
            class={filter === "issues" ? "filter-seg-btn active" : "filter-seg-btn"}
            onClick={() => onFilterChange("issues")}
            type="button"
          >
            Issues <span id="filter-issues-count">{issueCount}</span>
          </button>
        </div>
      </div>

      {/* Intake Queue Summary */}
      <div id="input-grouped-summary" class={`grouped-summary-card ${showGroupedSummary ? "" : "hidden"}`}>
        <span class="grouped-summary-text">
          <strong>{visibleItems.length} documents selected</strong>
          <span class="quiet"> · {formatBytes(totalSize)}</span>
        </span>
        <button id="btn-view-all-inputs" class="btn-view-all" onClick={() => onSetShowAll(true)} type="button">
          View All ({visibleItems.length} files)
        </button>
      </div>

      {/* Intake Table */}
      <div class={`table-container input-table-container ${showGroupedSummary ? "hidden" : ""}`}>
        {visibleItems.length > 10 && showAllInputsTable ? (
          <div class="collapse-summary-wrap">
            <button id="btn-collapse-inputs" class="btn-collapse-summary" onClick={() => onSetShowAll(false)} type="button">
              Collapse to summary
            </button>
          </div>
        ) : null}

        {checkedPaths.size > 0 ? (
          <div id="selection-scope-banner" class="selection-scope-banner">
            <span id="selection-scope-text">
              {checkedPaths.size === filteredItems.length && filteredItems.length > pagedItems.length
                ? `All ${filteredItems.length} matching documents selected`
                : `All ${pagedItems.filter((i) => checkedPaths.has(i.source_path || i.display_name)).length} documents on this page selected`}
            </span>
            <div class="button-row">
              {checkedPaths.size < filteredItems.length ? (
                <button id="btn-select-all-matching" class="button ghost small" onClick={onSelectAllMatching} type="button">
                  Select all {filteredItems.length} matching
                </button>
              ) : null}
              <button id="btn-clear-selection-scope" class="button ghost small" onClick={onClearChecked} type="button">
                Clear
              </button>
            </div>
          </div>
        ) : null}

        <table class="data-table compact-table">
          <thead>
            <tr>
              <th style="width: 36px; text-align: center;">
                <input
                  id="chk-select-all-inputs"
                  ref={selectAllRef}
                  type="checkbox"
                  checked={isAllPagedChecked}
                  onChange={(e) => onToggleSelectAllPaged(e.currentTarget.checked)}
                />
              </th>
              <th>Document</th>
              <th>Status</th>
              <th style="text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody id="selected-inputs-tbody">
            {visibleItems.length === 0 ? (
              <tr class="empty-row"><td colSpan={4} class="empty-cell">No documents selected. Click Add files or paste a path above.</td></tr>
            ) : filteredItems.length === 0 ? (
              <tr class="empty-row"><td colSpan={4} class="empty-cell">No documents match the filter query</td></tr>
            ) : (
              pagedItems.map((item) => {
                const itemKey = item.source_path || item.display_name;
                const isChecked = checkedPaths.has(itemKey);
                return (
                  <tr key={item.input_id} data-path={itemKey}>
                    <td style="text-align: center;">
                      <input
                        type="checkbox"
                        class="input-row-chk"
                        checked={isChecked}
                        onChange={(e) => onToggleItemChecked(itemKey, e.currentTarget.checked)}
                      />
                    </td>
                    <td>
                      <div class="doc-item-cell">
                        <strong class="doc-name">{item.display_name}</strong>
                        <span class="doc-size">{item.source_path ? `${item.source_path} · ` : ""}{formatBytes(item.size_bytes)}</span>
                      </div>
                    </td>
                    <td>
                      {item.is_eligible ? (
                        <span class="badge badge-emerald">Eligible</span>
                      ) : (
                        <button
                          class="btn-issue-info badge badge-crimson"
                          tabIndex={0}
                          aria-label={`Issue: ${item.issue_reason || "Ineligible document"}`}
                          type="button"
                        >
                          {item.issue_reason || "Issue"}
                        </button>
                      )}
                    </td>
                    <td style="text-align: right;">
                      <div class="button-row compact" style="justify-content: flex-end;">
                        <button class="button ghost mini" onClick={() => onPreview(`/api/inputs/${encodeURIComponent(item.input_id)}/preview`, item.display_name)} type="button">Preview</button>
                        <a class="button ghost mini" href={`/api/inputs/${encodeURIComponent(item.input_id)}/raw`} target="_blank">Open</a>
                        <button class="button ghost mini text-danger" onClick={() => void onRemoveItem(item)} type="button">Remove</button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>

        {filteredItems.length > pageSize ? (
          <div class="pagination" style="margin-top: 10px; display: flex; align-items: center; justify-content: space-between; padding: 4px 8px;">
            <button id="btn-input-prev" class="button ghost small" disabled={currentPage <= 1} onClick={() => onSetPage(Math.max(1, currentPage - 1))} type="button">Previous</button>
            <span id="input-page-indicator" style="font-size: 11px;">Page {currentPage} of {pageCount} ({filteredItems.length} total)</span>
            <button id="btn-input-next" class="button ghost small" disabled={currentPage >= pageCount} onClick={() => onSetPage(Math.min(pageCount, currentPage + 1))} type="button">Next</button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
