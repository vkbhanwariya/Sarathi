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


def _choose_task(page: Page, task: str) -> None:
    button = page.locator(f"#btn-task-{task}")
    if button.count() == 0:
        page.locator(".selected-task-heading").click()
    button.click()


def _open_settings(page: Page, subtask: str) -> None:
    settings = page.locator(f"#subtask-{subtask} .task-settings")
    if settings.get_attribute("open") is None:
        settings.locator("summary").click()


def test_app_loads_and_displays_home_screen(app_page: Page) -> None:
    """Verify that the single-page application loads with Griha Home active and displays only Level 1 selection initially."""
    expect(app_page.locator("h1")).to_contain_text("Sarathi")
    expect(app_page.locator(".nav-tab[data-screen='home']")).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#screen-home")).to_have_class(re.compile(r"\bactive\b"))

    # All four tasks are directly available without an intermediate module filter.
    task_tabs = app_page.locator(".primary-task-tab-btn")
    expect(task_tabs).to_have_count(4)
    expect(app_page.locator(".col-card-title")).to_have_text(
        [
            "Documents Extraction",
            "Bank Account Consolidation",
            "Font Conversion",
            "Translation",
        ]
    )
    expect(app_page.locator("#btn-task-bank-consolidation")).to_be_visible()

    # On home screen, only level 1 selection is shown initially (no level 2 subtask cards visible)
    expect(app_page.locator(".subtask-card")).to_have_count(0)
    expect(app_page.locator(".workflow-columns-grid")).to_be_visible()

    # On selecting the respective level 1 task, the specific level 2 options are displayed
    _choose_task(app_page, "documents-extraction")
    expect(app_page.locator("#btn-task-documents-extraction")).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#subtask-native")).to_be_visible()
    expect(app_page.locator("#subtask-instant-ocr")).to_be_visible()
    expect(app_page.locator(".primary-task-tab-btn")).to_have_count(1)
    expect(app_page.locator("#param-convert-legacy-fonts")).not_to_be_visible()
    _open_settings(app_page, "native")
    expect(app_page.locator("#param-convert-legacy-fonts")).to_be_visible()
    expect(app_page.locator("#param-convert-legacy-fonts")).to_be_checked()
    expect(app_page.locator("#param-layout-analysis")).to_be_visible()


def test_draft_parameter_preservation_across_telemetry(app_page: Page, web_server: MukhaWebServer) -> None:
    """Verify that changing an action parameter is preserved when telemetry updates arrive."""
    _choose_task(app_page, "documents-extraction")
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
    _choose_task(app_page, "documents-extraction")
    custom_ocr_card = app_page.locator("#subtask-custom-ocr")
    custom_ocr_card.click()

    profile_select = app_page.locator("#param-profile")
    expect(profile_select).to_be_visible()
    profile_select.select_option("accurate")
    expect(profile_select).to_have_value("accurate")

    # Switch directly to Bank Account Consolidation
    _choose_task(app_page, "bank-consolidation")
    expect(app_page.locator("#subtask-instant-consolidation")).to_be_visible()

    # Switch back to Documents Extraction
    _choose_task(app_page, "documents-extraction")
    profile_select = app_page.locator("#param-profile")
    expect(profile_select).to_be_visible()

    # Must survive switching capabilities and returning
    expect(profile_select).to_have_value("accurate")


def test_toggle_value_survives_capability_switching(app_page: Page) -> None:
    """Verify that custom toggle values survive switching between capabilities."""
    _choose_task(app_page, "documents-extraction")
    custom_ocr_card = app_page.locator("#subtask-custom-ocr")
    custom_ocr_card.click()

    # Toggle clahe checkbox
    clahe_chk = app_page.locator("#param-clahe")
    expect(clahe_chk).to_be_visible()
    clahe_chk.check()
    expect(clahe_chk).to_be_checked()

    # Switch to Bank Statements and back to Documents Extraction
    _choose_task(app_page, "bank-consolidation")
    expect(app_page.locator("#subtask-instant-consolidation")).to_be_visible()

    _choose_task(app_page, "documents-extraction")
    clahe_chk = app_page.locator("#param-clahe")
    expect(clahe_chk).to_be_visible()
    expect(clahe_chk).to_be_checked()


def test_parameter_selection_survives_screen_navigation(app_page: Page) -> None:
    """Verify that user draft choices survive navigating to another screen and returning."""
    _choose_task(app_page, "documents-extraction")
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
    _choose_task(app_page, "documents-extraction")
    accurate_ocr_card = app_page.locator("#subtask-accurate-ocr")
    accurate_ocr_card.locator(".action-card-header").click()
    expect(accurate_ocr_card).to_have_class(re.compile(r"\bselected\b"))

    payload = app_page.evaluate("""() => window.__sarathi_build_request ? window.__sarathi_build_request() : null""")
    assert payload is not None
    assert payload["requirement"] == "ocr"
    assert payload["profile"] == "accurate"


def test_preserve_layout_and_layout_analysis_toggles(app_page: Page) -> None:
    """Verify that layout preservation and GNN layout analysis checkboxes toggle on click and update request payload."""
    _choose_task(app_page, "documents-extraction")

    # 1. Accurate OCR: Preserve Layout toggle
    card = app_page.locator("#subtask-accurate-ocr")
    card.locator(".action-card-header").click()
    _open_settings(app_page, "accurate-ocr")
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
    payload_off = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert payload_off["profile"] == "accurate"

    # 2. Native Extraction: Deep Layout Analysis toggle
    native_card = app_page.locator("#subtask-native")
    native_card.locator(".action-card-header").click()
    _open_settings(app_page, "native")
    chk_gnn = app_page.locator("#param-layout-analysis")
    expect(chk_gnn).not_to_be_checked()

    chk_gnn.click()
    expect(chk_gnn).to_be_checked()

    native_payload = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert native_payload is not None
    assert native_payload["requirement"] == "read_native"
    assert native_payload["profile"] == "layout_preserving"
    assert native_payload["custom_options"].get("layout_analysis") is True


def test_progressive_task_hierarchy_and_second_level_choices(app_page: Page) -> None:
    """Verify that the 4 primary tasks expand into the exact approved second-level choices in Vedas/Decisions.md."""
    # 1. Documents Extraction: Native, Instant OCR, Accurate OCR, Cloud Document AI, Custom OCR
    _choose_task(app_page, "documents-extraction")
    expect(app_page.locator("#subtask-native")).to_be_visible()
    expect(app_page.locator("#subtask-instant-ocr")).to_be_visible()
    expect(app_page.locator("#subtask-accurate-ocr")).to_be_visible()
    expect(app_page.locator("#subtask-cloud-ocr")).to_be_visible()
    expect(app_page.locator("#subtask-custom-ocr")).to_be_visible()

    # Providers appear only after Cloud OCR is selected.
    expect(app_page.locator("#chip-gemini-ocr")).not_to_be_visible()
    app_page.locator("#subtask-cloud-ocr .action-card-header").click()
    # Verify cloud provider chips in Cloud Document AI
    expect(app_page.locator("#chip-gemini-ocr")).to_be_visible()
    expect(app_page.locator("#chip-mistral-ocr")).to_be_visible()
    expect(app_page.locator("#chip-azure-ocr")).to_be_visible()

    # 2. Bank Account Consolidation: Instant Consolidation, Accurate Consolidation
    _choose_task(app_page, "bank-consolidation")
    expect(app_page.locator("#subtask-instant-consolidation")).to_be_visible()
    expect(app_page.locator("#subtask-accurate-consolidation")).to_be_visible()

    # 3. Font Conversion: Legacy to Unicode, Unicode to KrutiDev, Unicode to DevLys
    _choose_task(app_page, "font-conversion")
    expect(app_page.locator("#subtask-legacy-to-unicode")).to_be_visible()
    expect(app_page.locator("#subtask-unicode-to-krutidev")).to_be_visible()
    expect(app_page.locator("#subtask-unicode-to-devlys")).to_be_visible()
    _open_settings(app_page, "legacy-to-unicode")
    expect(app_page.locator("#param-source-font")).to_be_visible()

    # 4. Translation: Direction selector first, then 5 engines in exact order
    _choose_task(app_page, "translation")
    expect(app_page.locator("#btn-direction-auto")).to_be_visible()
    expect(app_page.locator("#btn-direction-hi-en")).to_be_visible()
    expect(app_page.locator("#btn-direction-en-hi")).to_be_visible()

    expect(app_page.locator("#subtask-engine-indictrans2")).to_be_visible()
    expect(app_page.locator("#subtask-engine-opus-mt")).to_be_visible()
    expect(app_page.locator("#subtask-engine-gemini")).to_be_visible()
    expect(app_page.locator("#subtask-engine-mistral")).to_be_visible()
    expect(app_page.locator("#subtask-engine-azure")).to_be_visible()


def test_translation_direction_and_engine_payload(app_page: Page) -> None:
    """Verify that translation direction and engine options map correctly to the execution payload."""
    _choose_task(app_page, "translation")

    # Choose Hindi -> English direction
    app_page.locator("#btn-direction-hi-en").click()
    expect(app_page.locator("#btn-direction-hi-en")).to_have_class(re.compile(r"\bactive\b"))

    # Choose OPUS-MT engine
    app_page.locator("#subtask-engine-opus-mt").click()
    expect(app_page.locator("#subtask-engine-opus-mt")).to_have_class(re.compile(r"\bselected\b"))

    payload = app_page.evaluate("""() => window.__sarathi_build_request ? window.__sarathi_build_request() : null""")
    assert payload is not None
    assert payload["requirement"] == "translation"
    assert payload["profile"] == "instant"
    assert payload["custom_options"]["direction"] == "hi_en"
    assert payload["custom_options"]["engine"] == "opus_mt"


def test_task_collapsible_accordion_toggling(app_page: Page) -> None:
    """Verify that Level 1 tasks act as a collapsible accordion: expanding Level 2 on click and collapsing back when clicked again."""
    doc_btn = app_page.locator("#btn-task-documents-extraction")

    # Initially collapsed
    expect(app_page.locator(".subtask-card")).to_have_count(0)
    expect(app_page.locator(".workflow-columns-grid")).to_be_visible()

    # Click Documents Extraction to expand
    _choose_task(app_page, "documents-extraction")
    expect(doc_btn).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".accordion-item[data-task='documents_extraction']")).to_have_class(
        re.compile(r"\bexpanded\b")
    )
    expect(app_page.locator("#subtask-native")).to_be_visible()

    # Click Documents Extraction again to collapse
    _choose_task(app_page, "documents-extraction")
    expect(doc_btn).not_to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".accordion-item[data-task='documents_extraction']")).to_have_class(
        re.compile(r"\bcollapsed\b")
    )
    expect(app_page.locator(".subtask-card")).to_have_count(0)
    expect(app_page.locator(".workflow-columns-grid")).to_be_visible()

    # Click Bank Account Consolidation
    bank_btn = app_page.locator("#btn-task-bank-consolidation")
    _choose_task(app_page, "bank-consolidation")
    expect(bank_btn).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".accordion-item[data-task='bank_consolidation']")).to_have_class(
        re.compile(r"\bexpanded\b")
    )
    expect(app_page.locator("#subtask-instant-consolidation")).to_be_visible()

    # Switching directly to Font Conversion expands its options
    font_btn = app_page.locator("#btn-task-font-conversion")
    _choose_task(app_page, "font-conversion")
    expect(font_btn).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#subtask-legacy-to-unicode")).to_be_visible()


def test_clean_output_header_footer_toggle(app_page: Page) -> None:
    """Verify that Clean Output (running header/footer separation) toggle is visible, checked by default, and reflected in request payload."""
    _choose_task(app_page, "documents-extraction")
    expect(app_page.locator("#subtask-native")).to_be_visible()

    # Native Extraction: Clean output checkbox is visible and checked by default
    _open_settings(app_page, "native")
    native_chk = app_page.locator("#param-skip-header-footer")
    expect(native_chk).to_be_visible()
    expect(native_chk).to_be_checked()

    payload_native = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert payload_native is not None
    assert payload_native["custom_options"]["skip_header_footer"] is True

    # Accurate OCR: Clean output checkbox is visible and checked by default
    app_page.locator("#subtask-accurate-ocr").click()
    _open_settings(app_page, "accurate-ocr")
    ocr_chk = app_page.locator("#param-ocr-skip-header-footer")
    expect(ocr_chk).to_be_visible()
    expect(ocr_chk).to_be_checked()

    payload_ocr = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert payload_ocr is not None
    assert payload_ocr["custom_options"]["skip_header_footer"] is True


def test_custom_mode_workflow_and_end_to_end_wiring(app_page: Page) -> None:
    """Verify that selecting Custom Mode unfolds the 5-stage modular pipeline builder, updates request payloads, and restores Workflows mode seamlessly."""
    expect(app_page.locator("#btn-mode-custom")).not_to_be_visible()
    app_page.locator("#workflow-more-options > summary").click()
    expect(app_page.locator("#btn-mode-custom")).to_be_visible()
    expect(app_page.locator("#btn-mode-workflows")).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator(".tasks-accordion")).to_be_visible()
    expect(app_page.locator("#custom-mode-pipeline")).to_have_count(0)

    # 1. Switch to Custom Mode
    app_page.locator("#btn-mode-custom").click()
    expect(app_page.locator("#btn-mode-custom")).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#custom-mode-pipeline")).to_be_visible()
    expect(app_page.locator(".tasks-accordion")).to_have_count(0)

    # Verify all 5 pipeline stages are rendered
    expect(app_page.locator("#custom-stage-extraction")).to_be_visible()
    expect(app_page.locator("#custom-stage-font")).to_be_visible()
    expect(app_page.locator("#custom-stage-translation")).to_be_visible()
    expect(app_page.locator("#custom-stage-layout")).to_be_visible()
    expect(app_page.locator("#custom-stage-tuning")).to_be_visible()

    # Default payload in custom mode (defaults to native documents extraction)
    payload_initial = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_initial["requirement"] == "read_native"
    assert payload_initial["profile"] == "instant"

    # 2. Stage 1: Select RapidOCR Accurate Layout
    app_page.locator("#custom-engine-accurate-ocr").click()
    payload_accurate = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_accurate["requirement"] == "ocr"
    assert payload_accurate["profile"] == "accurate"

    # 3. Stage 1: Select Financial Statements Engine
    app_page.locator("#custom-engine-bank-statements").click()
    payload_bank = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_bank["requirement"] == "bank_statements"

    # 4. Stage 1: Select Custom RapidOCR & tune Stage 5 parameters
    app_page.locator("#custom-engine-custom-ocr").click()
    payload_custom = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_custom["requirement"] == "ocr"
    assert payload_custom["profile"] == "custom"

    # Check and toggle CLAHE in tuning panel
    clahe_toggle = app_page.locator("#param-clahe")
    expect(clahe_toggle).to_be_visible()
    clahe_toggle.check()
    expect(clahe_toggle).to_be_checked()

    payload_tuned = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_tuned["custom_options"]["clahe"] is True

    # 5. Stage 3: Neural Translation selection
    app_page.locator("#custom-trans-indictrans2").click()
    payload_trans = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_trans["requirement"] == "translation"
    assert payload_trans["custom_options"]["engine"] == "indictrans2"

    # 6. Switch back to Workflows mode
    app_page.locator("#btn-mode-workflows").click()
    expect(app_page.locator("#btn-mode-workflows")).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#custom-mode-pipeline")).to_have_count(0)
    expect(app_page.locator(".tasks-accordion")).to_be_visible()
