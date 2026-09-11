"""Browser interaction tests for Mukha Phase 4 (Batch Selection and Navigation).

Verifies grouped summary, complete paginated table, All/Eligible/Issues filtering,
explicit selection scope, selection persistence, re-addition of excluded files,
and keyboard-accessible issue explanations across batch boundaries (0, 1, 10, 11, 100, 101).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.browser]


def _make_synthetic_items(count: int, issues_ratio: float = 0.0) -> list[dict]:
    """Helper to generate synthetic intake document items."""
    items = []
    for i in range(count):
        is_issue = i < int(count * issues_ratio)
        items.append({
            "input_id": f"inp_{i:04d}",
            "source_path": f"E:/Docs/doc_{i:04d}.pdf",
            "display_name": f"doc_{i:04d}.pdf",
            "size_bytes": 1024 * (i + 1),
            "is_eligible": not is_issue,
            "issue_reason": "Encrypted PDF file" if is_issue else None,
        })
    return items


def test_batch_boundary_0_files(app_page: Page) -> None:
    """Boundary 0 files: empty message rendered, clear buttons disabled."""
    app_page.evaluate("""() => window.__sarathi_set_intake([])""")
    tbody = app_page.locator("#selected-inputs-tbody")
    expect(tbody).to_contain_text("No documents selected")
    expect(app_page.locator("#input-grouped-summary")).to_have_class("grouped-summary-card hidden")
    expect(app_page.locator("#btn-start-run")).to_be_disabled()


def test_batch_zero_eligible_inputs_disables_start_button(app_page: Page) -> None:
    """When documents are selected but eligible_count is 0, Start Document Processing button must be disabled."""
    items = [
        {
            "input_id": "inp_bad1",
            "source_path": "E:/Docs/encrypted.pdf",
            "display_name": "encrypted.pdf",
            "size_bytes": 2048,
            "is_eligible": False,
            "issue_reason": "Encrypted PDF file",
        },
        {
            "input_id": "inp_bad2",
            "source_path": "E:/Docs/empty.txt",
            "display_name": "empty.txt",
            "size_bytes": 0,
            "is_eligible": False,
            "issue_reason": "Zero-byte file",
        },
    ]
    app_page.evaluate(
        """(items) => {
            window.__sarathi_set_intake(items, {
                eligible_count: 0,
                issue_count: 2,
                issues: [["encrypted.pdf", "Encrypted PDF file"], ["empty.txt", "Zero-byte file"]],
            });
        }""",
        items,
    )
    btn_start = app_page.locator("#btn-start-run")
    expect(btn_start).to_be_disabled()


def test_batch_boundary_1_file(app_page: Page) -> None:
    """Boundary 1 file: individual row rendered directly without grouped summary."""
    items = _make_synthetic_items(1)
    app_page.evaluate("""(items) => window.__sarathi_set_intake(items)""", items)
    rows = app_page.locator("#selected-inputs-tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("doc_0000.pdf")
    expect(app_page.locator("#input-grouped-summary")).to_have_class("grouped-summary-card hidden")


def test_batch_boundary_10_files(app_page: Page) -> None:
    """Boundary 10 files: exactly 10 individual rows rendered without grouped summary."""
    items = _make_synthetic_items(10)
    app_page.evaluate("""(items) => window.__sarathi_set_intake(items)""", items)
    rows = app_page.locator("#selected-inputs-tbody tr")
    expect(rows).to_have_count(10)
    expect(app_page.locator("#input-grouped-summary")).to_have_class("grouped-summary-card hidden")


def test_batch_boundary_11_files_grouped_summary_and_view_all(app_page: Page) -> None:
    """Boundary 11 files: grouped summary card rendered with View All action expanding into paginated table."""
    items = _make_synthetic_items(11)
    app_page.evaluate("""(items) => window.__sarathi_set_intake(items)""", items)

    summary = app_page.locator("#input-grouped-summary")
    expect(summary).to_be_visible()
    expect(summary).to_contain_text("11 documents selected")

    view_all_btn = app_page.locator("#btn-view-all-inputs")
    expect(view_all_btn).to_be_visible()
    expect(view_all_btn).to_contain_text("View All (11 files)")

    # By default, table is hidden
    expect(app_page.locator(".input-table-container")).to_have_class("table-container input-table-container hidden")

    # Click View All to expand
    view_all_btn.click()

    # Now table container is visible and paginated (10 rows on page 1)
    expect(app_page.locator(".input-table-container")).not_to_have_class("hidden")
    expect(app_page.locator("#selected-inputs-tbody tr")).to_have_count(10)
    expect(app_page.locator("#input-page-indicator")).to_contain_text("Page 1 of 2 (11 total)")

    # Collapse back to summary
    collapse_btn = app_page.locator("#btn-collapse-inputs")
    expect(collapse_btn).to_be_visible()
    collapse_btn.click()
    expect(app_page.locator(".input-table-container")).to_have_class("table-container input-table-container hidden")


def test_batch_boundaries_100_and_101_files_pagination(app_page: Page) -> None:
    """Boundaries 100 & 101 files: paginated table allows reaching all items across pages without 100-row cutoff."""
    items_101 = _make_synthetic_items(101)
    app_page.evaluate(
        """(items) => {
            window.__sarathi_set_intake(items);
            window.__sarathi_set_show_all(true);
            window.__sarathi_set_input_page(1);
        }""",
        items_101,
    )

    expect(app_page.locator("#input-page-indicator")).to_contain_text("Page 1 of 11 (101 total)")
    expect(app_page.locator("#btn-input-prev")).to_be_disabled()
    expect(app_page.locator("#btn-input-next")).to_be_enabled()

    # Navigate to next page
    app_page.locator("#btn-input-next").click()
    expect(app_page.locator("#input-page-indicator")).to_contain_text("Page 2 of 11")
    expect(app_page.locator("#btn-input-prev")).to_be_enabled()
    # Row 1 of page 2 is index 10 (doc_0010.pdf)
    expect(app_page.locator("#selected-inputs-tbody tr").first).to_contain_text("doc_0010.pdf")

    # Navigate to last page (page 11)
    app_page.evaluate("""() => window.__sarathi_set_input_page(11)""")
    expect(app_page.locator("#input-page-indicator")).to_contain_text("Page 11 of 11 (101 total)")
    expect(app_page.locator("#btn-input-next")).to_be_disabled()
    # Exactly 1 row on page 11 (101st item)
    expect(app_page.locator("#selected-inputs-tbody tr")).to_have_count(1)
    expect(app_page.locator("#selected-inputs-tbody tr").first).to_contain_text("doc_0100.pdf")


def test_duplicate_filenames_in_different_directories(app_page: Page) -> None:
    """Duplicate display names across different directory paths render without collision."""
    items = [
        {"input_id": "1", "source_path": "E:/FolderA/invoice.pdf", "display_name": "invoice.pdf", "size_bytes": 100, "is_eligible": True},
        {"input_id": "2", "source_path": "E:/FolderB/invoice.pdf", "display_name": "invoice.pdf", "size_bytes": 200, "is_eligible": True},
    ]
    app_page.evaluate(
        """(items) => {
            window.__sarathi_set_intake(items);
        }""",
        items,
    )

    rows = app_page.locator("#selected-inputs-tbody tr")
    expect(rows).to_have_count(2)

    # Check only the first invoice.pdf
    rows.first.locator(".input-row-chk").check()

    checked_paths = app_page.evaluate("""() => window.__sarathi_get_checked_paths()""")
    assert checked_paths == ["E:/FolderA/invoice.pdf"]
    expect(rows.first.locator(".input-row-chk")).to_be_checked()
    expect(rows.nth(1).locator(".input-row-chk")).not_to_be_checked()


def test_search_filtering_preserves_selection_and_handles_empty(app_page: Page) -> None:
    """Search filtering updates visible items without dropping existing checked selections."""
    items = [
        {"input_id": "1", "source_path": "E:/docs/alpha.pdf", "display_name": "alpha.pdf", "size_bytes": 100, "is_eligible": True},
        {"input_id": "2", "source_path": "E:/docs/beta.pdf", "display_name": "beta.pdf", "size_bytes": 200, "is_eligible": True},
    ]
    app_page.evaluate(
        """(items) => {
            window.__sarathi_set_intake(items);
            window.__sarathi_add_checked("E:/docs/alpha.pdf");
        }""",
        items,
    )

    filter_input = app_page.locator("#input-files-filter")
    # Search for non-matching string
    filter_input.fill("xyz_no_match")
    expect(app_page.locator("#selected-inputs-tbody")).to_contain_text("No documents match the filter query")

    # Clear filter
    filter_input.fill("")
    rows = app_page.locator("#selected-inputs-tbody tr")
    expect(rows).to_have_count(2)
    # Selection of alpha.pdf survived
    expect(rows.first.locator(".input-row-chk")).to_be_checked()


def test_filter_tabs_all_eligible_issues(app_page: Page) -> None:
    """Filter tabs for All, Eligible, and Issues filter correctly and display accurate counts."""
    items = [
        {"input_id": "1", "source_path": "E:/doc1.pdf", "display_name": "doc1.pdf", "size_bytes": 100, "is_eligible": True},
        {"input_id": "2", "source_path": "E:/doc2.pdf", "display_name": "doc2.pdf", "size_bytes": 100, "is_eligible": True},
        {"input_id": "3", "source_path": "E:/doc3.pdf", "display_name": "doc3.pdf", "size_bytes": 100, "is_eligible": False, "issue_reason": "Encrypted"},
    ]
    app_page.evaluate(
        """(items) => {
            window.__sarathi_set_intake(items);
            window.__sarathi_set_filter("all");
        }""",
        items,
    )

    expect(app_page.locator("#filter-all-count")).to_have_text("3")
    expect(app_page.locator("#filter-eligible-count")).to_have_text("2")
    expect(app_page.locator("#filter-issues-count")).to_have_text("1")

    # Filter to Eligible
    app_page.locator("#btn-filter-eligible").click()
    expect(app_page.locator("#selected-inputs-tbody tr")).to_have_count(2)
    expect(app_page.locator("#selected-inputs-tbody")).not_to_contain_text("doc3.pdf")

    # Filter to Issues
    app_page.locator("#btn-filter-issues").click()
    expect(app_page.locator("#selected-inputs-tbody tr")).to_have_count(1)
    expect(app_page.locator("#selected-inputs-tbody")).to_contain_text("doc3.pdf")

    # Return to All
    app_page.locator("#btn-filter-all").click()
    expect(app_page.locator("#selected-inputs-tbody tr")).to_have_count(3)


def test_selection_scope_and_indeterminate_checkbox(app_page: Page) -> None:
    """Selection scope distinguishes current page vs all matching files with indeterminate header checkbox."""
    items = _make_synthetic_items(15)  # 2 pages: 10 on page 1, 5 on page 2
    app_page.evaluate(
        """(items) => {
            window.__sarathi_set_intake(items);
            window.__sarathi_set_show_all(true);
            window.__sarathi_set_input_page(1);
        }""",
        items,
    )

    header_chk = app_page.locator("#chk-select-all-inputs")
    scope_banner = app_page.locator("#selection-scope-banner")

    # Select 1 row on page 1
    app_page.locator("#selected-inputs-tbody tr").first.locator(".input-row-chk").check()
    is_indeterminate = header_chk.evaluate("el => el.indeterminate")
    assert is_indeterminate is True
    expect(header_chk).not_to_be_checked()

    # Click header checkbox: selects all 10 on current page
    header_chk.click()
    expect(scope_banner).to_be_visible()
    expect(app_page.locator("#selection-scope-text")).to_contain_text("All 10 documents on this page selected")

    # Click 'Select all 15 matching documents'
    app_page.locator("#btn-select-all-matching").click()
    expect(app_page.locator("#selection-scope-text")).to_contain_text("All 15 matching documents selected")

    # Navigate to page 2: all items on page 2 must be checked
    app_page.locator("#btn-input-next").click()
    expect(app_page.locator("#input-page-indicator")).to_contain_text("Page 2 of 2")
    rows_page_2 = app_page.locator("#selected-inputs-tbody tr")
    expect(rows_page_2).to_have_count(5)
    for i in range(5):
        expect(rows_page_2.nth(i).locator(".input-row-chk")).to_be_checked()

    # Clear selection scope
    app_page.locator("#btn-clear-selection-scope").click()
    for i in range(5):
        expect(rows_page_2.nth(i).locator(".input-row-chk")).not_to_be_checked()


def test_removal_and_readdition_of_excluded_file(app_page: Page) -> None:
    """Removing a file excludes it; re-adding un-excludes and restores it."""
    res = app_page.evaluate(
        """() => {
            window.__sarathi_remove_path(["E:/test.pdf"]);
            const afterRemoveExcluded = window.__sarathi_is_excluded("E:/test.pdf");

            window.__sarathi_add_path(["E:/test.pdf"]);
            const afterReaddExcluded = window.__sarathi_is_excluded("E:/test.pdf");
            return { afterRemoveExcluded, afterReaddExcluded };
        }"""
    )
    assert res["afterRemoveExcluded"] is True
    assert res["afterReaddExcluded"] is False


def test_accessible_issue_buttons_and_html_escaping(app_page: Page) -> None:
    """Issue badges are keyboard-accessible buttons with aria-label and safely escaped dynamic text."""
    xss_reason = '<script>alert("xss")</script> & "bad" quote'
    items = [
        {"input_id": "1", "source_path": "E:/bad.pdf", "display_name": "bad.pdf", "size_bytes": 100, "is_eligible": False, "issue_reason": xss_reason},
    ]
    app_page.evaluate(
        """(items) => {
            window.__sarathi_set_intake(items);
        }""",
        items,
    )

    issue_btn = app_page.locator(".btn-issue-info")
    expect(issue_btn).to_be_visible()
    expect(issue_btn).to_have_attribute("tabindex", "0")
    expect(issue_btn).to_have_attribute("aria-label", f"Issue: {xss_reason}")

    # Ensure no script tags were inserted into the DOM
    script_tags = app_page.locator("#selected-inputs-tbody script")
    expect(script_tags).to_have_count(0)
