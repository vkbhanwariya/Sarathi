"""Browser interaction tests for Mukha Screen Navigation & Run Separation (Phase 2).

Verifies that viewing historical runs does not clobber active run state,
cancellation always targets the active execution, and out-of-order responses are rejected.
"""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page, expect

from sarathi.mukha.web import MukhaWebServer

pytestmark = [pytest.mark.browser]


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
    """Verify that clicking Cancel sends a POST request targeting state.activeRunId, not viewedRunId."""
    intercepted_requests: list[str] = []

    def handle_route(route: any) -> None:
        intercepted_requests.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body='{"ok": true}')

    app_page.route("**/api/runs/**/cancel", handle_route)

    # Set active run to run-active-999, but view historical run-history-111
    app_page.evaluate(
        """() => {
            const state = window.sarathiState;
            state.activeRunId = "run-active-999";
            state.activeRunStatus = "RUNNING";
            state.viewedRunId = "run-history-111";

            const btn = document.getElementById("btn-cancel-run");
            if (btn) btn.disabled = false;
        }"""
    )

    # Switch to monitor screen where cancel button resides
    app_page.click(".nav-tab[data-screen='monitor']")
    expect(app_page.locator("#screen-monitor")).to_have_class("screen-view active")

    # Click cancel button
    app_page.click("#btn-cancel-run")

    # If confirmation dialog appears, confirm it
    confirm_btn = app_page.locator("#btn-cancel-dialog-confirm")
    if confirm_btn.is_visible():
        confirm_btn.click()

    app_page.wait_for_timeout(300)

    # Assert that an HTTP request was dispatched to /api/runs/run-active-999/cancel
    assert len(intercepted_requests) == 1
    assert "run-active-999/cancel" in intercepted_requests[0]
    assert "run-history-111" not in intercepted_requests[0]


def test_stale_summary_responses_discarded(app_page: Page) -> None:
    """Verify that loadRunSummary sequence tracking drops delayed out-of-order responses."""

    def handle_summary_route(route: any) -> None:
        req_url = route.request.url
        if "run-a" in req_url:
            time.sleep(0.4)
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok": true, "summary": {"run_id": "run-a", "status": "SUCCESS"}}',
            )
        else:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok": true, "summary": {"run_id": "run-b", "status": "SUCCESS"}}',
            )

    app_page.route("**/api/runs/**/summary", handle_summary_route)

    # Invoke production loadRunSummary for run-a then run-b
    app_page.evaluate(
        """async () => {
            const { loadRunSummary } = await import("/js/screens/summary.js");
            loadRunSummary("run-a");
            loadRunSummary("run-b");
        }"""
    )

    app_page.wait_for_timeout(600)

    # The active viewedRunId must remain run-b, not clobbered by delayed run-a
    viewed_id = app_page.evaluate("() => window.sarathiState ? window.sarathiState.viewedRunId : null")
    assert viewed_id == "run-b"
