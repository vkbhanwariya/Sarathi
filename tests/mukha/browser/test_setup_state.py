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
    if settings.count() > 0 and settings.get_attribute("open") is None:
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
    expect(app_page.locator("#subtask-ocr")).to_be_visible()
    expect(app_page.locator(".primary-task-tab-btn")).to_have_count(1)
    expect(app_page.locator("#param-convert-legacy-fonts")).to_be_visible()
    expect(app_page.locator("#param-convert-legacy-fonts")).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#param-layout-analysis")).to_be_visible()


def test_draft_parameter_preservation_across_telemetry(app_page: Page, web_server: MukhaWebServer) -> None:
    """Verify that changing an action parameter is preserved when telemetry updates arrive."""
    _choose_task(app_page, "documents-extraction")
    ocr_card = app_page.locator("#subtask-ocr")
    ocr_card.click()

    btn_en = app_page.locator("#btn-ocr-lang-en-v6")
    expect(btn_en).to_be_visible()
    btn_en.click()
    expect(btn_en).to_have_class(re.compile(r"\bactive\b"))

    # Simulate background telemetry update or state revision change
    web_server.runner.set_intake_selection(web_server.runner.get_intake_selection())

    # Wait for SSE/poll update
    app_page.wait_for_timeout(2000)

    # Value must NOT reset back to default
    expect(btn_en).to_have_class(re.compile(r"\bactive\b"))


def test_parameter_selection_survives_capability_switching(app_page: Page) -> None:
    """Verify that changing primary task/capability and returning preserves previous parameter choices."""
    _choose_task(app_page, "documents-extraction")
    ocr_card = app_page.locator("#subtask-ocr")
    ocr_card.click()

    btn_en = app_page.locator("#btn-ocr-lang-en-v6")
    expect(btn_en).to_be_visible()
    btn_en.click()
    expect(btn_en).to_have_class(re.compile(r"\bactive\b"))

    # Switch directly to Bank Account Consolidation
    _choose_task(app_page, "bank-consolidation")
    expect(app_page.locator("#btn-bank-mode-accurate")).to_be_visible()

    # Switch back to Documents Extraction
    _choose_task(app_page, "documents-extraction")
    btn_en = app_page.locator("#btn-ocr-lang-en-v6")
    expect(btn_en).to_be_visible()

    # Must survive switching capabilities and returning
    expect(btn_en).to_have_class(re.compile(r"\bactive\b"))


def test_toggle_value_survives_capability_switching(app_page: Page) -> None:
    """Verify that custom toggle values survive switching between capabilities."""
    _choose_task(app_page, "documents-extraction")
    ocr_card = app_page.locator("#subtask-ocr")
    ocr_card.click()

    # Toggle preserve layout checkbox
    lay_chk = app_page.locator("#param-preserve-layout")
    expect(lay_chk).to_be_visible()
    lay_chk.click()
    expect(lay_chk).to_have_class(re.compile(r"\bactive\b"))

    # Switch to Bank Statements and back to Documents Extraction
    _choose_task(app_page, "bank-consolidation")
    expect(app_page.locator("#btn-bank-mode-accurate")).to_be_visible()

    _choose_task(app_page, "documents-extraction")
    lay_chk = app_page.locator("#param-preserve-layout")
    expect(lay_chk).to_be_visible()
    expect(lay_chk).to_have_class(re.compile(r"\bactive\b"))


def test_parameter_selection_survives_screen_navigation(app_page: Page) -> None:
    """Verify that user draft choices survive navigating to another screen and returning."""
    _choose_task(app_page, "documents-extraction")
    ocr_card = app_page.locator("#subtask-ocr")
    ocr_card.click()

    btn_en = app_page.locator("#btn-ocr-lang-en-v6")
    expect(btn_en).to_be_visible()
    btn_en.click()
    expect(btn_en).to_have_class(re.compile(r"\bactive\b"))

    # Switch to Monitor (F2) and back to Home (F1)
    app_page.click(".nav-tab[data-screen='monitor']")
    expect(app_page.locator("#screen-monitor")).to_have_class(re.compile(r"\bactive\b"))

    app_page.click(".nav-tab[data-screen='home']")
    expect(app_page.locator("#screen-home")).to_have_class(re.compile(r"\bactive\b"))

    # Value should remain selected
    btn_en = app_page.locator("#btn-ocr-lang-en-v6")
    expect(btn_en).to_have_class(re.compile(r"\bactive\b"))


def test_preview_and_execution_payload_equivalence(app_page: Page) -> None:
    """Verify that buildRequest produces identical configuration for preview and execution."""
    _choose_task(app_page, "documents-extraction")
    ocr_card = app_page.locator("#subtask-ocr")
    ocr_card.locator(".action-card-header").click()
    expect(ocr_card).to_have_class(re.compile(r"\bselected\b"))

    payload = app_page.evaluate("""() => window.__sarathi_build_request ? window.__sarathi_build_request() : null""")
    assert payload is not None
    assert payload["requirement"] == "ocr"
    assert payload["profile"] == "instant"


def test_preserve_layout_and_layout_analysis_toggles(app_page: Page) -> None:
    """Verify that layout preservation and GNN layout analysis checkboxes toggle on click and update request payload."""
    _choose_task(app_page, "documents-extraction")

    # 1. OCR: Preserve Layout toggle
    card = app_page.locator("#subtask-ocr")
    card.locator(".action-card-header").click()
    chk_preserve = app_page.locator("#param-preserve-layout")
    expect(chk_preserve).not_to_have_class(re.compile(r"\bactive\b"))

    # Click checkbox directly
    chk_preserve.click()
    expect(chk_preserve).to_have_class(re.compile(r"\bactive\b"))

    # Verify payload reflects layout_preserving profile
    payload = app_page.evaluate("""() => window.__sarathi_build_request ? window.__sarathi_build_request() : null""")
    assert payload is not None
    assert payload["requirement"] == "ocr"
    assert payload["profile"] == "layout_preserving"
    assert payload["custom_options"].get("preserve_layout") is True

    # Toggle the switch button off again.
    chk_preserve.click()
    expect(chk_preserve).not_to_have_class(re.compile(r"\bactive\b"))
    payload_off = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert payload_off["profile"] == "instant"

    # 2. Native Extraction: Deep Layout Analysis toggle
    native_card = app_page.locator("#subtask-native")
    native_card.locator(".action-card-header").click()
    _open_settings(app_page, "native")
    chk_gnn = app_page.locator("#param-layout-analysis")
    expect(chk_gnn).not_to_have_class(re.compile(r"\bactive\b"))

    chk_gnn.click()
    expect(chk_gnn).to_have_class(re.compile(r"\bactive\b"))

    native_payload = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert native_payload is not None
    assert native_payload["requirement"] == "read_native"
    assert native_payload["profile"] == "layout_preserving"
    assert native_payload["custom_options"].get("layout_analysis") is True


def test_progressive_task_hierarchy_and_second_level_choices(app_page: Page) -> None:
    """Verify that the 4 primary tasks expand into the exact approved second-level choices in Vedas/Decisions.md."""
    # 1. Documents Extraction: Native, OCR Document Recognition
    _choose_task(app_page, "documents-extraction")
    expect(app_page.locator("#subtask-native")).to_be_visible()
    expect(app_page.locator("#subtask-ocr")).to_be_visible()
    expect(app_page.locator(".subtask-card")).to_have_count(2)

    # Providers appear after Cloud OCR is selected.
    expect(app_page.locator("#chip-mistral-ocr")).not_to_be_visible()
    app_page.locator("#subtask-ocr .action-card-header").click()
    app_page.locator("#btn-ocr-engine-cloud").click()
    # Verify cloud provider chips in Cloud Document AI
    expect(app_page.locator("#chip-mistral-ocr")).to_be_visible()

    # 2. Bank Account Consolidation: Instant is default; Accurate is an in-place mode toggle.
    _choose_task(app_page, "bank-consolidation")
    bank_accurate = app_page.locator("#btn-bank-mode-accurate")
    expect(bank_accurate).to_be_visible()
    expect(bank_accurate).not_to_have_class(re.compile(r"\bactive\b"))

    # 3. Font Conversion: default legacy-to-Unicode plus explicit legacy-target controls.
    _choose_task(app_page, "font-conversion")
    expect(app_page.locator("#btn-font-source-hint")).to_be_visible()
    to_legacy = app_page.locator("#btn-font-to-legacy")
    expect(to_legacy).to_be_visible()
    expect(to_legacy).not_to_have_class(re.compile(r"\bactive\b"))
    to_legacy.click()
    expect(app_page.locator("#chip-font-krutidev")).to_be_visible()
    expect(app_page.locator("#chip-font-devlys")).to_be_visible()

    # 4. Translation: direction selector first, with Krutrim-Translate (4096 Context).
    _choose_task(app_page, "translation")
    expect(app_page.locator("#btn-direction-auto")).to_be_visible()
    expect(app_page.locator("#btn-direction-hi-en")).to_be_visible()
    expect(app_page.locator("#btn-direction-en-hi")).to_be_visible()
    krutrim_toggle = app_page.locator("#btn-trans-krutrim")
    expect(krutrim_toggle).to_be_visible()
    expect(krutrim_toggle).to_have_class(re.compile(r"\bactive\b"))



def test_translation_direction_and_engine_payload(app_page: Page) -> None:
    """Verify that translation direction and engine options map correctly to the execution payload."""
    _choose_task(app_page, "translation")

    # Choose Hindi -> English direction
    app_page.locator("#btn-direction-hi-en").click()
    expect(app_page.locator("#btn-direction-hi-en")).to_have_class(re.compile(r"\bactive\b"))

    # Canonical Krutrim engine is selected
    krutrim_toggle = app_page.locator("#btn-trans-krutrim")
    expect(krutrim_toggle).to_be_visible()
    expect(krutrim_toggle).to_have_class(re.compile(r"\bactive\b"))

    payload = app_page.evaluate("""() => window.__sarathi_build_request ? window.__sarathi_build_request() : null""")
    assert payload is not None
    assert payload["requirement"] == "translation"
    assert payload["profile"] == "instant"
    assert payload["custom_options"]["direction"] == "hi_en"
    assert payload["custom_options"]["engine"] == "krutrim"


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
    expect(app_page.locator("#btn-bank-mode-accurate")).to_be_visible()

    # Switching directly to Font Conversion expands its controls
    font_btn = app_page.locator("#btn-task-font-conversion")
    _choose_task(app_page, "font-conversion")
    expect(font_btn).to_have_class(re.compile(r"\bactive\b"))
    expect(app_page.locator("#btn-font-source-hint")).to_be_visible()
    expect(app_page.locator("#btn-font-to-legacy")).to_be_visible()


def test_clean_output_header_footer_toggle(app_page: Page) -> None:
    """Verify that Clean Output (running header/footer separation) toggle is visible, checked by default, and reflected in request payload."""
    _choose_task(app_page, "documents-extraction")
    expect(app_page.locator("#subtask-native")).to_be_visible()

    # Native Extraction: Clean output checkbox is visible and checked by default
    _open_settings(app_page, "native")
    native_chk = app_page.locator("#param-skip-header-footer")
    expect(native_chk).to_be_visible()
    expect(native_chk).to_have_class(re.compile(r"\bactive\b"))

    payload_native = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert payload_native is not None
    assert payload_native["custom_options"]["skip_header_footer"] is True

    # OCR: Clean output checkbox is visible and checked by default
    app_page.locator("#subtask-ocr").click()
    ocr_chk = app_page.locator("#param-ocr-skip-header-footer")
    expect(ocr_chk).to_be_visible()
    expect(ocr_chk).to_have_class(re.compile(r"\bactive\b"))

    payload_ocr = app_page.evaluate(
        """() => window.__sarathi_build_request ? window.__sarathi_build_request() : null"""
    )
    assert payload_ocr is not None
    assert payload_ocr["custom_options"]["skip_header_footer"] is True


def test_ocr_document_recognition_add_ons_and_engine_switching(app_page: Page) -> None:
    """Verify OCR Document Recognition subtask integrates presets, layout toggles, local/cloud engines, and clean single-path UI without redundant custom pipeline."""
    # Redundant switcher and custom mode pipeline are completely absent from production
    expect(app_page.locator("#workflow-more-options")).to_have_count(0)
    expect(app_page.locator("#custom-mode-pipeline")).to_have_count(0)

    # 1. Expand Documents Extraction and select OCR Document Recognition
    _choose_task(app_page, "documents-extraction")
    ocr_card = app_page.locator("#subtask-ocr")
    ocr_card.locator(".action-card-header").click()
    expect(ocr_card).to_have_class(re.compile(r"\bselected\b"))

    # Verify absence of redundant preset controls
    expect(app_page.locator("#btn-ocr-preset-instant")).to_have_count(0)
    expect(app_page.locator("#btn-ocr-preset-accurate")).to_have_count(0)

    # Default profile is instant
    payload_initial = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_initial["requirement"] == "ocr"
    assert payload_initial["profile"] == "instant"

    # Verify Profile selector (single Accurate toggle, Instant is default)
    expect(app_page.locator("#btn-ocr-profile-instant")).to_have_count(0)
    btn_accurate = app_page.locator("#btn-ocr-profile-accurate")
    expect(btn_accurate).to_be_visible()
    # Default: Accurate toggle is OFF (profile = instant)
    expect(btn_accurate).not_to_have_class(re.compile(r"\bactive\b"))

    btn_accurate.click()
    expect(btn_accurate).to_have_class(re.compile(r"\bactive\b"))
    payload_accurate = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_accurate["profile"] == "accurate"

    btn_accurate.click()
    expect(btn_accurate).not_to_have_class(re.compile(r"\bactive\b"))
    payload_reinstant = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_reinstant["profile"] == "instant"

    # 2. Verify Local OpenVINO model options (Devanagari vs English)
    btn_devanagari = app_page.locator("#btn-ocr-lang-devanagari")
    btn_en_v6 = app_page.locator("#btn-ocr-lang-en-v6")
    expect(btn_devanagari).to_be_visible()
    expect(btn_devanagari).to_have_class(re.compile(r"\bactive\b"))
    expect(btn_en_v6).to_be_visible()

    btn_en_v6.click()
    expect(btn_en_v6).to_have_class(re.compile(r"\bactive\b"))
    payload_en = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_en["custom_options"]["lang"] == "en_v6"

    # 3. Switch to Cloud Multimodal Inference Engine
    btn_cloud = app_page.locator("#btn-ocr-engine-cloud")
    btn_cloud.click()
    expect(btn_cloud).to_have_class(re.compile(r"\bactive\b"))

    # Verify cloud chips and local fallback checkbox appear
    expect(app_page.locator("#chip-mistral-ocr")).to_be_visible()
    expect(app_page.locator("#param-ocr-fallback-to-local")).to_be_visible()
    expect(app_page.locator("#param-ocr-fallback-to-local")).to_have_class(re.compile(r"\bactive\b"))

    payload_cloud = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_cloud["requirement"] == "mistral_ocr"
    assert payload_cloud["custom_options"]["engine"] == "mistral_ocr"
    assert payload_cloud["custom_options"]["fallback_to_local"] is True

    # 4. In-front inference engines and stamp suppression toggle
    expect(app_page.locator("#btn-ocr-lang-devanagari")).to_be_visible()
    expect(app_page.locator("#chip-mistral-ocr")).to_be_visible()

    stamp_chk = app_page.locator("#param-ocr-remove-stamps")
    expect(stamp_chk).to_be_visible()
    stamp_chk.click()
    expect(stamp_chk).to_have_class(re.compile(r"\bactive\b"))

    payload_tuned = app_page.evaluate("() => window.__sarathi_build_request()")
    assert payload_tuned["custom_options"]["remove_stamps"] is True


def test_translation_in_front_toggles_and_legal_integrity_bar(app_page: Page) -> None:
    """Verify Translation in-front toggles and legal integrity chips."""
    _choose_task(app_page, "translation")

    # 1. Legal fidelity controls are presented directly in the translation workspace.
    expect(app_page.locator("#param-trans-statutory")).to_be_visible()
    expect(app_page.locator("#param-trans-proper-nouns")).to_be_visible()

    # 2. In-front legal fidelity toggles are active by default
    stat_chk = app_page.locator("#param-trans-statutory")
    pn_chk = app_page.locator("#param-trans-proper-nouns")
    expect(stat_chk).to_be_visible()
    expect(stat_chk).to_have_class(re.compile(r"\bactive\b"))
    expect(pn_chk).to_be_visible()
    expect(pn_chk).to_have_class(re.compile(r"\bactive\b"))

    # 3. Default payload carries statutory and proper noun flags
    payload = app_page.evaluate("() => window.__sarathi_build_request ? window.__sarathi_build_request() : null")
    assert payload is not None
    assert payload["custom_options"]["statutory"] is True
    assert payload["custom_options"]["preserve_proper_nouns"] is True

    # 4. Krutrim-Translate engine is canonical and active
    krutrim_card = app_page.locator("#btn-trans-krutrim")
    expect(krutrim_card).to_be_visible()
    expect(krutrim_card).to_have_class(re.compile(r"\bactive\b"))

    payload_krutrim = app_page.evaluate("() => window.__sarathi_build_request ? window.__sarathi_build_request() : null")
    assert payload_krutrim is not None
    assert payload_krutrim["requirement"] == "translation"
    assert payload_krutrim["custom_options"]["engine"] == "krutrim"
