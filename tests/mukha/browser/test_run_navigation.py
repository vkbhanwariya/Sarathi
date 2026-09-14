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
    active_id = "run-active-123"

    app_page.evaluate(
        f"""() => {{
            if (window.__sarathi_set_active_run) {{
                window.__sarathi_set_active_run({{
                    run_id: '{active_id}',
                    status: 'RUNNING',
                    elapsed_ns: 1000000
                }});
            }}
        }}"""
    )

    app_page.click(".nav-tab[data-screen='summary']")
    expect(app_page.locator("#screen-summary")).to_have_class("screen-view active")

    app_page.click(".nav-tab[data-screen='monitor']")
    expect(app_page.locator("#screen-monitor")).to_have_class("screen-view active")
    expect(app_page.locator("#monitor-run-id")).to_have_text(active_id)


def test_cancel_always_targets_active_run(app_page: Page) -> None:
    """Verify that clicking Cancel sends a POST request targeting active run, not historical summary."""
    intercepted_requests: list[str] = []

    def handle_route(route: any) -> None:
        intercepted_requests.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body='{"ok": true}')

    app_page.route("**/api/runs/**/cancel", handle_route)

    # Set active run to run-active-999 via production hook
    app_page.evaluate(
        """() => {
            if (window.__sarathi_set_active_run) {
                window.__sarathi_set_active_run({
                    run_id: "run-active-999",
                    status: "RUNNING",
                    elapsed_ns: 1000000
                });
            }
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
            window.loadRunSummary("run-a");
            window.loadRunSummary("run-b");
        }"""
    )

    app_page.wait_for_timeout(600)

    # The active viewed summary must remain run-b, not clobbered by delayed run-a
    expect(app_page.locator("#summary-run-id")).to_have_text("run-b")
    assert app_page.locator("#screen-summary").get_attribute("data-run-id") == "run-b"
