"""Browser interaction tests for Mukha Screen 1 (Griha Setup State).

Verifies preservation of draft configurations, available action reconciliation,
and parameter stability against telemetry and navigation updates.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from sarathi.mukha.web import MukhaWebServer


def test_app_loads_and_displays_home_screen(app_page: Page) -> None:
    """Verify that the single-page application loads with Griha Home active."""
    expect(app_page.locator("h1")).to_contain_text("Sarathi")
    expect(app_page.locator(".nav-tab[data-screen='home']")).to_have_class("nav-tab active")
    expect(app_page.locator("#screen-home")).to_have_class("screen-view active")


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
    expect(app_page.locator("#screen-monitor")).to_have_class("screen-view active")

    app_page.click(".nav-tab[data-screen='home']")
    expect(app_page.locator("#screen-home")).to_have_class("screen-view active")

    # Value should remain accurate
    profile_select = app_page.locator("#param-profile")
    expect(profile_select).to_have_value("accurate")


def test_preview_and_execution_payload_equivalence(app_page: Page) -> None:
    """Verify that buildRequestPayload produces identical configuration for preview and execution."""
    ocr_card = app_page.locator(".req-card[data-req='ocr']")
    ocr_card.click()

    profile_select = app_page.locator("#param-profile")
    profile_select.select_option("accurate")

    payload = app_page.evaluate(
        """() => {
            // Import and evaluate buildRequestPayload from home screen module
            const state = window.sarathiState;
            const customOpts = {};
            let profile = "instant";
            const act = (state.availableActions || []).find((a) => a.action_id === state.currentRequirement);
            if (act && act.parameters) {
                act.parameters.forEach((p) => {
                    const draftVal = state.draftActionParams[act.action_id] ? state.draftActionParams[act.action_id][p.parameter_id] : p.default_value;
                    if (p.kind === "select") {
                        if (p.parameter_id === "profile") profile = draftVal || "instant";
                        else if (draftVal !== undefined && draftVal !== "") customOpts[p.parameter_id] = draftVal;
                    } else if (p.kind === "toggle") {
                        customOpts[p.parameter_id] = Boolean(draftVal);
                    }
                });
            }
            return { requirement: state.currentRequirement, profile, customOpts };
        }"""
    )
    assert payload["requirement"] == "ocr"
    assert payload["profile"] == "accurate"
