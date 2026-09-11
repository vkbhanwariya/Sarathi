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
def app_page(page: Page, app_url: str) -> Page:
    """Navigate to the running Mukha local web app and wait for DOM readiness."""
    page.goto(app_url)
    page.wait_for_selector("#screen-home", state="attached")
    return page
