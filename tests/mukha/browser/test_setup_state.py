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
    """Verify that the single-page application loads with Griha Home active and displays only Level 1 selection initially."""
    expect(app_page.locator("h1")).to_contain_text("Sarathi")
    expect(app_page.locator(".nav-tab[data-screen='home']")).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#screen-home")).to_have_class(re.compile(r"\bactive\b"))

    # Verify exactly 4 primary tasks are displayed in exact approved order
    task_tabs = app_page.locator(".primary-task-tab-btn")
    expect(task_tabs).to_have_count(4)
    expect(app_page.locator("#btn-task-documents-extraction")).to_be_visible()
    expect(app_page.locator("#btn-task-bank-consolidation")).to_be_visible()
    expect(app_page.locator("#btn-task-font-conversion")).to_be_visible()
    expect(app_page.locator("#btn-task-translation")).to_be_visible()

    # On home screen, only level 1 selection is shown initially (no level 2 subtask cards visible)
    expect(app_page.locator(".subtask-card")).to_have_count(0)
    expect(app_page.locator("#level1-empty-prompt")).to_be_visible()

    # On selecting the respective level 1 task, the specific level 2 options are displayed
    app_page.locator("#btn-task-documents-extraction").click()
    expect(app_page.locator("#btn-task-documents-extraction")).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#subtask-native")).to_be_visible()
    expect(app_page.locator("#subtask-instant-ocr")).to_be_visible()
    expect(app_page.locator("#param-convert-legacy-fonts")).to_be_visible()
    expect(app_page.locator("#param-convert-legacy-fonts")).to_be_checked()
    expect(app_page.locator("#param-layout-analysis")).to_be_visible()


def test_draft_parameter_preservation_across_telemetry(app_page: Page, web_server: MukhaWebServer) -> None:
    """Verify that changing an action parameter is preserved when telemetry updates arrive."""
    app_page.locator("#btn-task-documents-extraction").click()
    custom_ocr_card = app_page.locator("#subtask-custom-ocr")
    custom_ocr_card.click()

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
    """Verify that changing primary task/capability and returning preserves previous parameter choices."""
    app_page.locator("#btn-task-documents-extraction").click()
    custom_ocr_card = app_page.locator("#subtask-custom-ocr")
    custom_ocr_card.click()

    profile_select = app_page.locator("#param-profile")
    expect(profile_select).to_be_visible()
    profile_select.select_option("accurate")
    expect(profile_select).to_have_value("accurate")

    # Switch to Bank Account Consolidation
    bank_tab = app_page.locator("#btn-task-bank-consolidation")
    bank_tab.click()
    expect(app_page.locator("#subtask-instant-consolidation")).to_be_visible()

    # Switch back to Documents Extraction
    app_page.locator("#btn-task-documents-extraction").click()
    profile_select = app_page.locator("#param-profile")
    expect(profile_select).to_be_visible()

    # Must survive switching capabilities and returning
    expect(profile_select).to_have_value("accurate")


def test_toggle_value_survives_capability_switching(app_page: Page) -> None:
    """Verify that custom toggle values survive switching between capabilities."""
    app_page.locator("#btn-task-documents-extraction").click()
    custom_ocr_card = app_page.locator("#subtask-custom-ocr")
    custom_ocr_card.click()

    # Toggle clahe checkbox
    clahe_chk = app_page.locator("#param-clahe")
    expect(clahe_chk).to_be_visible()
    clahe_chk.check()
    expect(clahe_chk).to_be_checked()

    # Switch to Bank Statements and back to Documents Extraction
    app_page.locator("#btn-task-bank-consolidation").click()
    expect(app_page.locator("#subtask-instant-consolidation")).to_be_visible()

    app_page.locator("#btn-task-documents-extraction").click()
    clahe_chk = app_page.locator("#param-clahe")
    expect(clahe_chk).to_be_visible()
    expect(clahe_chk).to_be_checked()


def test_parameter_selection_survives_screen_navigation(app_page: Page) -> None:
    """Verify that user draft choices survive navigating to another screen and returning."""
    app_page.locator("#btn-task-documents-extraction").click()
    custom_ocr_card = app_page.locator("#subtask-custom-ocr")
    custom_ocr_card.click()

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
    app_page.locator("#btn-task-documents-extraction").click()
    accurate_ocr_card = app_page.locator("#subtask-accurate-ocr")
    accurate_ocr_card.locator(".action-card-header").click()
    expect(accurate_ocr_card).to_have_class(re.compile(r"\bselected\b"))

    payload = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert payload is not None
    assert payload["requirement"] == "ocr"
    assert payload["profile"] == "accurate"


def test_preserve_layout_and_layout_analysis_toggles(app_page: Page) -> None:
    """Verify that layout preservation and GNN layout analysis checkboxes toggle on click and update request payload."""
    app_page.locator("#btn-task-documents-extraction").click()

    # 1. Accurate OCR: Preserve Layout toggle
    card = app_page.locator("#subtask-accurate-ocr")
    card.locator(".action-card-header").click()
    chk_preserve = app_page.locator("#param-preserve-layout")
    expect(chk_preserve).not_to_be_checked()

    # Click checkbox directly
    chk_preserve.click()
    expect(chk_preserve).to_be_checked()

    # Verify payload reflects layout_preserving profile
    payload = app_page.evaluate("""() => window.__sarathi_build_request ? window.__sarathi_build_request() : null""")
    assert payload is not None
    assert payload["requirement"] == "ocr"
    assert payload["profile"] == "layout_preserving"
    assert payload["custom_options"].get("preserve_layout") is True

    # Click label to toggle off
    label_preserve = app_page.locator("label:has(#param-preserve-layout)")
    label_preserve.click()
    expect(chk_preserve).not_to_be_checked()
    payload_off = app_page.evaluate("""() => window.__sarathi_build_request ? window.__sarathi_build_request() : null""")
    assert payload_off["profile"] == "accurate"

    # 2. Native Extraction: Deep Layout Analysis toggle
    native_card = app_page.locator("#subtask-native")
    native_card.locator(".action-card-header").click()
    chk_gnn = app_page.locator("#param-layout-analysis")
    expect(chk_gnn).not_to_be_checked()

    chk_gnn.click()
    expect(chk_gnn).to_be_checked()

    native_payload = app_page.evaluate("""() => window.__sarathi_build_request ? window.__sarathi_build_request() : null""")
    assert native_payload is not None
    assert native_payload["requirement"] == "read_native"
    assert native_payload["profile"] == "layout_preserving"
    assert native_payload["custom_options"].get("layout_analysis") is True







def test_progressive_task_hierarchy_and_second_level_choices(app_page: Page) -> None:
    """Verify that the 4 primary tasks expand into the exact approved second-level choices in Vedas/Decisions.md."""
    # 1. Documents Extraction: Native, Instant OCR, Accurate OCR, Cloud Document AI, Custom OCR
    doc_tab = app_page.locator("#btn-task-documents-extraction")
    doc_tab.click()
    expect(app_page.locator("#subtask-native")).to_be_visible()
    expect(app_page.locator("#subtask-instant-ocr")).to_be_visible()
    expect(app_page.locator("#subtask-accurate-ocr")).to_be_visible()
    expect(app_page.locator("#subtask-cloud-ocr")).to_be_visible()
    expect(app_page.locator("#subtask-custom-ocr")).to_be_visible()

    # Verify cloud provider chips in Cloud Document AI
    expect(app_page.locator("#chip-gemini-ocr")).to_be_visible()
    expect(app_page.locator("#chip-mistral-ocr")).to_be_visible()
    expect(app_page.locator("#chip-azure-ocr")).to_be_visible()
    expect(app_page.locator("#chip-bhashini-ocr")).to_be_visible()

    # 2. Bank Account Consolidation: Instant Consolidation, Accurate Consolidation
    bank_tab = app_page.locator("#btn-task-bank-consolidation")
    bank_tab.click()
    expect(app_page.locator("#subtask-instant-consolidation")).to_be_visible()
    expect(app_page.locator("#subtask-accurate-consolidation")).to_be_visible()

    # 3. Font Conversion: Legacy to Unicode, Unicode to KrutiDev, Unicode to DevLys
    font_tab = app_page.locator("#btn-task-font-conversion")
    font_tab.click()
    expect(app_page.locator("#subtask-legacy-to-unicode")).to_be_visible()
    expect(app_page.locator("#subtask-unicode-to-krutidev")).to_be_visible()
    expect(app_page.locator("#subtask-unicode-to-devlys")).to_be_visible()
    expect(app_page.locator("#param-source-font")).to_be_visible()

    # 4. Translation: Direction selector first, then 6 engines in exact order
    trans_tab = app_page.locator("#btn-task-translation")
    trans_tab.click()
    expect(app_page.locator("#btn-direction-auto")).to_be_visible()
    expect(app_page.locator("#btn-direction-hi-en")).to_be_visible()
    expect(app_page.locator("#btn-direction-en-hi")).to_be_visible()

    expect(app_page.locator("#subtask-engine-indictrans2")).to_be_visible()
    expect(app_page.locator("#subtask-engine-opus-mt")).to_be_visible()
    expect(app_page.locator("#subtask-engine-bhashini")).to_be_visible()
    expect(app_page.locator("#subtask-engine-gemini")).to_be_visible()
    expect(app_page.locator("#subtask-engine-mistral")).to_be_visible()
    expect(app_page.locator("#subtask-engine-azure")).to_be_visible()


def test_translation_direction_and_engine_payload(app_page: Page) -> None:
    """Verify that translation direction and engine options map correctly to the execution payload."""
    app_page.locator("#btn-task-translation").click()

    # Choose Hindi -> English direction
    app_page.locator("#btn-direction-hi-en").click()
    expect(app_page.locator("#btn-direction-hi-en")).to_have_class(re.compile(r"\bactive\b"))

    # Choose OPUS-MT engine
    app_page.locator("#subtask-engine-opus-mt").click()
    expect(app_page.locator("#subtask-engine-opus-mt")).to_have_class(re.compile(r"\bselected\b"))

    payload = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert payload is not None
    assert payload["requirement"] == "translation"
    assert payload["profile"] == "instant"
    assert payload["custom_options"]["direction"] == "hi_en"
    assert payload["custom_options"]["engine"] == "opus_mt"


def test_task_collapsible_accordion_toggling(app_page: Page) -> None:
    """Verify that Level 1 tasks act as a collapsible accordion: expanding Level 2 on click and collapsing back when clicked again."""
    doc_btn = app_page.locator("#btn-task-documents-extraction")
    bank_btn = app_page.locator("#btn-task-bank-consolidation")

    # Initially collapsed
    expect(app_page.locator(".subtask-card")).to_have_count(0)
    expect(app_page.locator("#level1-empty-prompt")).to_be_visible()

    # Click Documents Extraction to expand
    doc_btn.click()
    expect(doc_btn).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".accordion-item[data-task='documents_extraction']")).to_have_class(re.compile(r"\bexpanded\b"))
    expect(app_page.locator("#subtask-native")).to_be_visible()

    # Click Documents Extraction again to collapse
    doc_btn.click()
    expect(doc_btn).not_to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".accordion-item[data-task='documents_extraction']")).to_have_class(re.compile(r"\bcollapsed\b"))
    expect(app_page.locator(".subtask-card")).to_have_count(0)
    expect(app_page.locator("#level1-empty-prompt")).to_be_visible()

    # Click Bank Account Consolidation to expand
    bank_btn.click()
    expect(bank_btn).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".accordion-item[data-task='bank_consolidation']")).to_have_class(re.compile(r"\bexpanded\b"))
    expect(app_page.locator("#subtask-instant-consolidation")).to_be_visible()

    # Switching to Font Conversion collapses Bank Consolidation and expands Font Conversion
    font_btn = app_page.locator("#btn-task-font-conversion")
    font_btn.click()
    expect(bank_btn).not_to_have_class(re.compile(r"\bactive\b"))
    expect(font_btn).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#subtask-instant-consolidation")).to_have_count(0)
    expect(app_page.locator("#subtask-legacy-to-unicode")).to_be_visible()

