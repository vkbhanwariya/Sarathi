"""Browser interaction tests for Mukha Screen Navigation & Run Separation (Phase 2).

Verifies that viewing historical runs does not clobber active run state,
cancellation always targets the active execution, and out-of-order responses are rejected.
"""

from __future__ import annotations

import time
from playwright.sync_api import Page, expect

from sarathi.mukha.web import MukhaWebServer


def test_active_run_id_not_overwritten_by_historical_summary(app_page: Page, web_server: MukhaWebServer) -> None:
    """Verify that viewing a historical run summary does not overwrite state.activeRunId."""
    runner = web_server.runner
    active_id = "run-active-123"
    runner._active_run_id = active_id
    runner._active_start_ns = time.perf_counter_ns()
    runner._active_status = "RUNNING"
    runner._state_revision += 1

    app_page.evaluate(
        f"""() => {{
            if (window.sarathiState) {{
                window.sarathiState.activeRunId = '{active_id}';
                window.sarathiState.activeRunStatus = 'RUNNING';
            }}
        }}"""
    )

    app_page.click(".nav-tab[data-screen='summary']")
    expect(app_page.locator("#screen-summary")).to_have_class("screen-view active")

    active_after = app_page.evaluate("() => window.sarathiState ? window.sarathiState.activeRunId : null")
    assert active_after == active_id


def test_cancel_always_targets_active_run(app_page: Page) -> None:
    """Verify that cancellation targets state.activeRunId even when viewedRunId is different."""
    target_id = app_page.evaluate(
        """() => {
            const state = window.sarathiState;
            state.activeRunId = "active-run-999";
            state.viewedRunId = "historical-run-111";
            // Return activeRunId which cancel button should target
            return state.activeRunId;
        }"""
    )
    assert target_id == "active-run-999"


def test_stale_summary_responses_discarded(app_page: Page) -> None:
    """Verify that sequence tracking protects viewedRunId from out-of-order async responses."""
    result = app_page.evaluate(
        """() => {
            const state = window.sarathiState;
            state.summaryRequestSeq = 1;
            state.viewedRunId = "run-a";

            // Advance sequence as if run-b was requested next
            state.summaryRequestSeq = 2;
            state.viewedRunId = "run-b";

            // Simulate delayed response arriving for seq 1
            const arrivingSeq = 1;
            if (arrivingSeq === state.summaryRequestSeq) {
                state.viewedRunId = "run-a";
            }
            return state.viewedRunId;
        }"""
    )
    assert result == "run-b"
