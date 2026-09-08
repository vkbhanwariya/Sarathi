"""Browser tests for Mukha Visual Tokens & Responsive Density (Phase 6).

Verifies modern Slate design tokens, 48px header density, table padding <= 10px,
panel scroll isolation, responsive breakpoint at 768px, and touch target sizing.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect


def test_header_height_and_tokens(app_page: Page) -> None:
    """Verify that the header computes to 48px and root tokens are applied."""
    header = app_page.locator(".app-header")
    expect(header).to_be_visible()

    height_px = app_page.evaluate(
        """() => {
            const el = document.querySelector('.app-header');
            return window.getComputedStyle(el).height;
        }"""
    )
    assert height_px == "48px"

    tokens = app_page.evaluate(
        """() => {
            const root = document.documentElement;
            const style = window.getComputedStyle(root);
            return {
                bgMain: style.getPropertyValue('--bg-main').trim(),
                bgPanel: style.getPropertyValue('--bg-panel').trim(),
                textPrimary: style.getPropertyValue('--text-primary').trim(),
            };
        }"""
    )
    assert tokens["bgMain"].lower() == "#0b0f19"
    assert tokens["bgPanel"].lower() == "#1e293b"
    assert tokens["textPrimary"].lower() == "#f1f5f9"


def test_table_density_and_padding(app_page: Page) -> None:
    """Verify that data-table headers and cells use compact padding (<= 10px)."""
    th_padding = app_page.evaluate(
        """() => {
            const th = document.querySelector('.data-table th');
            if (!th) return null;
            const style = window.getComputedStyle(th);
            return {
                top: parseFloat(style.paddingTop),
                bottom: parseFloat(style.paddingBottom),
            };
        }"""
    )
    assert th_padding is not None
    assert th_padding["top"] <= 10.0
    assert th_padding["bottom"] <= 10.0


def test_panel_scroll_isolation(app_page: Page) -> None:
    """Verify that screen views isolate scrolling to panels rather than whole page."""
    isolation = app_page.evaluate(
        """() => {
            const bodyStyle = window.getComputedStyle(document.body);
            const mainStyle = window.getComputedStyle(document.querySelector('.app-main'));
            const panelBody = document.querySelector('.panel-body');
            const panelStyle = panelBody ? window.getComputedStyle(panelBody) : null;
            return {
                bodyOverflow: bodyStyle.overflow,
                mainOverflow: mainStyle.overflow,
                panelOverflowY: panelStyle ? panelStyle.overflowY : null,
            };
        }"""
    )
    assert isolation["bodyOverflow"] == "hidden"
    assert "hidden" in isolation["mainOverflow"]
    assert isolation["panelOverflowY"] == "auto"


def test_responsive_layout_and_touch_targets(app_page: Page) -> None:
    """Verify responsive stacking at 768px viewport width and touch target sizing."""
    app_page.set_viewport_size({"width": 768, "height": 800})
    app_page.wait_for_timeout(200)

    grid_cols = app_page.evaluate(
        """() => {
            const grid = document.querySelector('.screen-grid');
            if (!grid) return null;
            return window.getComputedStyle(grid).gridTemplateColumns;
        }"""
    )
    assert grid_cols is not None
    # In a single column grid, there is only one column width value (not two space-separated values)
    cols = grid_cols.strip().split()
    assert len(cols) == 1

    # Check touch target heights on mobile viewport
    button_heights = app_page.evaluate(
        """() => {
            const btn = document.querySelector('.btn-primary');
            const navTab = document.querySelector('.nav-tab');
            return {
                btnHeight: btn ? btn.getBoundingClientRect().height : 0,
                navTabHeight: navTab ? navTab.getBoundingClientRect().height : 0,
            };
        }"""
    )
    assert button_heights["btnHeight"] >= 36.0
    assert button_heights["navTabHeight"] >= 36.0
