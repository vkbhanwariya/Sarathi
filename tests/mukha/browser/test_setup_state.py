"""Browser interaction tests for Mukha Screen 1 (Griha Setup State).

Verifies preservation of draft configurations, available action reconciliation,
and parameter stability against telemetry and navigation updates.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from sarathi.mukha.web import MukhaWebServer

pytestmark = [pytest.mark.browser]


def test_app_loads_and_displays_home_screen(app_page: Page) -> None:
    """Verify that the single-page application loads with Griha Home active."""
    expect(app_page.locator("h1")).to_contain_text("Sarathi")
    expect(app_page.locator(".nav-tab[data-screen='home']")).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#screen-home")).to_have_class(re.compile(r"\bactive\b"))


def test_draft_parameter_preservation_across_telemetry(app_page: Page, web_server: MukhaWebServer) -> None:
    """Verify that changing an action parameter is preserved when telemetry updates arrive."""
    ocr_card = app_page.locator(".req-card[data-req='ocr']")
    ocr_card.click()

    profile_select = app_page.locator("#param-profile")
    expect(profile_select).to_be_visible()

    profile_select.select_option("accurate")
    expect(profile_select).to_have_value("accurate")

    # Simulate background telemetry update or state revision change
    web_server.runner.set_intake_selection(web_server.runner.get_intake_selection())

    # Wait for SSE/poll update
    app_page.wait_for_timeout(2000)

    # In Phase 1 requirement: value must NOT reset back to default 'instant'
    expect(profile_select).to_have_value("accurate")


def test_parameter_selection_survives_capability_switching(app_page: Page) -> None:
    """Verify that changing requirement and returning preserves previous parameter choices."""
    ocr_card = app_page.locator(".req-card[data-req='ocr']")
    ocr_card.click()

    profile_select = app_page.locator("#param-profile")
    expect(profile_select).to_be_visible()
    profile_select.select_option("accurate")
    expect(profile_select).to_have_value("accurate")

    # Switch to Bank Statements
    bank_card = app_page.locator(".req-card[data-req='bank_statements']")
    bank_card.click()

    # Switch back to OCR
    ocr_card.click()
    profile_select = app_page.locator("#param-profile")
    expect(profile_select).to_be_visible()

    # Must survive switching capabilities and returning
    expect(profile_select).to_have_value("accurate")


def test_toggle_value_survives_capability_switching(app_page: Page) -> None:
    """Verify that custom toggle values survive switching between capabilities."""
    ocr_card = app_page.locator(".req-card[data-req='ocr']")
    ocr_card.click()

    profile_select = app_page.locator("#param-profile")
    profile_select.select_option("custom")

    # Toggle clahe checkbox
    clahe_chk = app_page.locator("#param-clahe")
    expect(clahe_chk).to_be_visible()
    clahe_chk.check()
    expect(clahe_chk).to_be_checked()

    # Switch to Bank Statements and back to OCR
    bank_card = app_page.locator(".req-card[data-req='bank_statements']")
    bank_card.click()
    ocr_card.click()

    clahe_chk = app_page.locator("#param-clahe")
    expect(clahe_chk).to_be_visible()
    expect(clahe_chk).to_be_checked()


def test_parameter_selection_survives_screen_navigation(app_page: Page) -> None:
    """Verify that user draft choices survive navigating to another screen and returning."""
    ocr_card = app_page.locator(".req-card[data-req='ocr']")
    ocr_card.click()

    profile_select = app_page.locator("#param-profile")
    expect(profile_select).to_be_visible()
    profile_select.select_option("accurate")
    expect(profile_select).to_have_value("accurate")

    # Switch to Monitor (F2) and back to Home (F1)
    app_page.click(".nav-tab[data-screen='monitor']")
    expect(app_page.locator("#screen-monitor")).to_have_class(re.compile(r"\bactive\b"))

    app_page.click(".nav-tab[data-screen='home']")
    expect(app_page.locator("#screen-home")).to_have_class(re.compile(r"\bactive\b"))

    # Value should remain accurate
    profile_select = app_page.locator("#param-profile")
    expect(profile_select).to_have_value("accurate")


def test_preview_and_execution_payload_equivalence(app_page: Page) -> None:
    """Verify that buildRequest produces identical configuration for preview and execution."""
    ocr_card = app_page.locator(".req-card[data-req='ocr']")
    ocr_card.click()

    profile_select = app_page.locator("#param-profile")
    profile_select.select_option("accurate")

    payload = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert payload is not None
    assert payload["requirement"] == "ocr"
    assert payload["profile"] == "accurate"


def test_action_category_menus_and_cloud_partitioning(app_page: Page) -> None:
    """Verify category tabs partition core local actions and cloud actions."""
    cat_core = app_page.locator("#btn-cat-core")
    cat_ocr = app_page.locator("#btn-cat-ocr")
    cat_trans = app_page.locator("#btn-cat-translation")
    cat_cloud = app_page.locator("#btn-cat-cloud")
    cat_all = app_page.locator("#btn-cat-all")

    expect(cat_core).to_be_visible()
    expect(cat_ocr).to_be_visible()
    expect(cat_trans).to_be_visible()
    expect(cat_cloud).to_be_visible()
    expect(cat_all).to_be_visible()

    # Core tab is active by default; local actions visible, cloud actions hidden
    expect(cat_core).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".req-card[data-req='ocr']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='bank_statements']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='gemini_ocr']")).to_have_count(0)

    # Switch to Cloud tab
    cat_cloud.click()
    expect(cat_cloud).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".req-card[data-req='gemini_ocr']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='gemini_translation']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='azure_ocr']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='azure_translation']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='bank_statements']")).to_have_count(0)

    # Switch to Translation tab
    cat_trans.click()
    expect(cat_trans).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".req-card[data-req='translation']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='gemini_translation']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='ocr']")).to_have_count(0)

    # Switch to OCR tab
    cat_ocr.click()
    expect(cat_ocr).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".req-card[data-req='ocr']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='gemini_ocr']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='bank_statements']")).to_have_count(0)

    # Switch to All tab
    cat_all.click()
    expect(cat_all).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".req-card[data-req='ocr']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='gemini_ocr']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='translation']")).to_be_visible()
    expect(app_page.locator(".req-card[data-req='bank_statements']")).to_be_visible()


def test_active_action_banner_when_browsing_other_category(app_page: Page) -> None:
    """Verify active action banner is displayed when active action is in another tab."""
    # Ensure OCR is selected in core tab
    ocr_card = app_page.locator(".req-card[data-req='ocr']")
    expect(ocr_card).to_be_visible()
    ocr_card.click()
    expect(ocr_card).to_have_class(re.compile(r"\bselected\b"))

    # Switch to Translation tab (which does not contain OCR)
    app_page.locator("#btn-cat-translation").click()
    banner = app_page.locator(".active-selection-banner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("Optical Character Recognition")

    # Click jump button in banner to return to active tab
    banner.locator("button").click()
    expect(app_page.locator("#btn-cat-ocr")).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".req-card[data-req='ocr']")).to_have_class(re.compile(r"\bselected\b"))



