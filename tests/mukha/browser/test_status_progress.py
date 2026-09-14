"""Browser interaction tests for Mukha Status & Progress Fidelity (Phase 3).

Verifies truthful status badges, indeterminate vs known progress rendering,
ARIA progress attributes, and accurate cancellation messages.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.browser]


def test_top_progress_role_and_aria_attributes(app_page: Page) -> None:
    """Verify that role='progressbar' has proper aria attributes."""
    container = app_page.locator("#top-progress-container")
    expect(container).to_have_attribute("role", "progressbar")
    expect(container).to_have_attribute("aria-valuemin", "0")
    expect(container).to_have_attribute("aria-valuemax", "100")


def test_cancel_dialog_copy_truthfulness(app_page: Page) -> None:
    """Verify that cancellation dialog does not claim immediate stoppage."""
    dialog = app_page.locator("#cancel-run-dialog")
    expect(dialog).not_to_contain_text("stopped immediately")
    expect(dialog).to_contain_text("cooperatively")


def test_indeterminate_progress_rendering(app_page: Page) -> None:
    """Verify indeterminate progress has indeterminate class and no invented percentage in Preact DOM."""
    container = app_page.locator("#top-progress-container")
    expect(container).to_have_attribute("aria-busy", "true")
    assert "indeterminate" in (container.get_attribute("class") or "")
    assert container.get_attribute("aria-valuenow") is None


def test_measured_zero_vs_missing_formatting(app_page: Page) -> None:
    """Verify that measured 0 values are preserved while missing values display as —."""
    res = app_page.evaluate(
        """async () => {
            const mod = window.__formatters;
            return {
                zeroDuration: mod.formatDuration(0),
                missingDuration: mod.formatDuration(null),
                zeroConfidence: mod.formatConfidence(0),
                missingConfidence: mod.formatConfidence(null),
                zeroBytes: mod.formatBytes(0),
                missingBytes: mod.formatBytes(null),
                unknownStatus: mod.formatStatus("SOME_FUTURE_STATE").label,
                cancelledStatus: mod.formatStatus("CANCELLED").label,
                warningStatus: mod.formatStatus("WARNING").label,
            };
        }"""
    )
    assert res["zeroDuration"] == "0.0 s"
    assert res["missingDuration"] == "—"
    assert res["zeroConfidence"] == "0.0%"
    assert res["missingConfidence"] == "—"
    assert res["zeroBytes"] == "0 B"
    assert res["missingBytes"] == "—"
    assert "SOME_FUTURE_STATE" in res["unknownStatus"]
    assert res["cancelledStatus"] == "Run Cancelled"
    assert res["warningStatus"] == "Completed with Warnings"


def test_summary_terminal_outcome_titles(app_page: Page) -> None:
    """Verify factual summary titles for each outcome."""
    titles = app_page.evaluate(
        """async () => {
            const results = {};
            for (const st of ["SUCCESS", "WARNING", "PARTIAL", "CANCELLED", "QUARANTINED", "FAILED"]) {
                results[st] = window.__formatSummaryTitle(st);
            }
            return results;
        }"""
    )
    assert titles["SUCCESS"] == "Run Completed Successfully"
    assert titles["WARNING"] == "Run Completed with Warnings"
    assert titles["PARTIAL"] == "Run Completed with Warnings"
    assert titles["CANCELLED"] == "Run Cancelled"
    assert titles["QUARANTINED"] == "Run Quarantined"
    assert titles["FAILED"] == "Run Failed (FAILED)"
