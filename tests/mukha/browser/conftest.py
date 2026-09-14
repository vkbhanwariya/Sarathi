"""Pytest fixtures for Mukha browser interaction tests using Playwright.

Reuses the canonical Agni and MukhaWebServer fixtures from tests/mukha/conftest.py.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from sarathi.mukha.web import MukhaWebServer


@pytest.fixture
def app_url(web_server: MukhaWebServer) -> str:
    """Return the root URL of the running MukhaWebServer."""
    return web_server.local_url


@pytest.fixture
def app_page(page: Page, app_url: str, request: pytest.FixtureRequest) -> Page:
    """Navigate to Mukha after both initial state hydration paths have converged.

    Mukha hydrates concurrently through ``/api/state`` and an EventSource that
    emits a canonical ``state`` snapshot. Browser tests install synthetic state
    through ``window.__sarathi_*`` hooks; if either initial hydration finishes
    afterward, it can overwrite that synthetic state. Observe completion of the
    initial HTTP state fetch and receipt of the first streamed state event before
    allowing a test to take control.

    The batch-selection module deliberately drives local UI state through those
    synthetic hooks. Its tests do not exercise live server reconciliation, so the
    captured EventSource is closed after initial hydration for that module only.
    This prevents later server snapshots from racing with and overwriting the
    synthetic intake while leaving EventSource behavior intact for all other
    browser tests.
    """
    page.add_init_script(
        """
        (() => {
          window.__sarathi_initial_state_fetch_seen = false;
          window.__sarathi_initial_state_event_seen = false;
          window.__sarathi_test_event_source = null;

          const originalFetch = window.fetch.bind(window);
          window.fetch = async (...args) => {
            const response = await originalFetch(...args);
            const request = args[0];
            const url = typeof request === "string" ? request : request?.url;
            if (url && new URL(url, window.location.href).pathname === "/api/state") {
              window.__sarathi_initial_state_fetch_seen = true;
            }
            return response;
          };

          const NativeEventSource = window.EventSource;
          const originalAddEventListener = NativeEventSource.prototype.addEventListener;
          NativeEventSource.prototype.addEventListener = function(type, listener, options) {
            if (type !== "state" || typeof listener !== "function") {
              return originalAddEventListener.call(this, type, listener, options);
            }
            const wrapped = function(event) {
              window.__sarathi_initial_state_event_seen = true;
              return listener.call(this, event);
            };
            return originalAddEventListener.call(this, type, wrapped, options);
          };

          window.EventSource = class SarathiTestEventSource extends NativeEventSource {
            constructor(...args) {
              super(...args);
              window.__sarathi_test_event_source = this;
            }
          };
        })();
        """
    )
    page.goto(app_url)
    page.wait_for_selector("#screen-home", state="attached")
    page.wait_for_function("() => window.__sarathi_initial_state_fetch_seen === true")
    page.wait_for_function("() => window.__sarathi_initial_state_event_seen === true")
    page.wait_for_function("() => typeof window.__sarathi_set_intake === 'function'")

    if request.node.path.name == "test_batch_selection.py":
        page.evaluate("() => window.__sarathi_test_event_source?.close()")

    return page
