"""Browser interaction tests for Mukha Phase 5 (Review and Correction Workbench).

Verifies truthful review queue rendering, pending count, Previous/Next navigation,
fail-closed actions based on available_actions, truthful status badges (ACCEPTED, UNRESOLVED, PENDING),
inline draft proposal handling without browser prompt(), and selection preservation across updates.
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.browser]


def _make_review_items() -> list[dict]:
    """Helper to generate synthetic review items matching state_builder.py output."""
    return [
        {
            "item_id": "rev_001",
            "attempt_id": "span_001",
            "artifact_id": "art_101",
            "stage": "ocr_extraction",
            "severity": "WARNING",
            "code": "WARNING",
            "message": "Low confidence OCR token detected",
            "status": "pending",
            "available_actions": ["accept", "unresolved"],
            "draft_proposal": None,
            "context": {
                "file": "doc_01.pdf",
                "span_id": "span_001",
                "source": "1O0.50",
                "output": "100.50",
                "confidence": 0.65,
            },
        },
        {
            "item_id": "rev_002",
            "attempt_id": "span_002",
            "artifact_id": "art_102",
            "stage": "translation",
            "severity": "WARNING",
            "code": "WARNING",
            "message": "Ambiguous terminology match",
            "status": "pending",
            "available_actions": ["accept", "unresolved"],
            "draft_proposal": None,
            "context": {
                "file": "doc_02.docx",
                "span_id": "span_002",
                "source": "bank statement credit",
                "output": "kredyt wyciag",
                "confidence": 0.55,
            },
        },
        {
            "item_id": "rev_003",
            "attempt_id": "span_003",
            "artifact_id": "art_103",
            "stage": "native_extraction",
            "severity": "WARNING",
            "code": "WARNING",
            "message": "Potential formatting discrepancy",
            "status": "unresolved",
            "available_actions": ["accept", "unresolved"],
            "draft_proposal": None,
            "context": {
                "file": "doc_03.pdf",
                "span_id": "span_003",
                "source": "N/A",
                "output": "0.00",
                "confidence": 0.50,
            },
        },
    ]


def test_review_empty_queue_state(app_page: Page) -> None:
    """Empty review queue renders empty state message and hides inspector card."""
    app_page.route(
        "**/api/review*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "items": []}),
        ),
    )

    app_page.click(".nav-tab[data-screen='review']")
    expect(app_page.locator("#screen-review")).to_have_class("screen-view active")

    app_page.evaluate(
        """async () => {
            const mod = await import("/js/screens/review.js");
            await mod.loadReviewQueue();
        }"""
    )

    tbody = app_page.locator("#review-queue-tbody")
    expect(tbody).to_contain_text("No items currently require human review.")
    expect(app_page.locator("#review-queue-count")).to_contain_text("0 items (0 pending)")
    expect(app_page.locator("#review-detail-card")).to_have_class("panel hidden")


def test_review_queue_rendering_and_pending_count(app_page: Page) -> None:
    """Review queue lists items and displays truthful pending vs total count."""
    items = _make_review_items()
    app_page.route(
        "**/api/review*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "items": items}),
        ),
    )

    app_page.click(".nav-tab[data-screen='review']")
    app_page.evaluate(
        """async () => {
            const mod = await import("/js/screens/review.js");
            await mod.loadReviewQueue();
        }"""
    )

    # 3 review rows rendered
    rows = app_page.locator("#review-queue-tbody tr.review-row")
    expect(rows).to_have_count(3)

    # Header count: 3 items (2 pending)
    expect(app_page.locator("#review-queue-count")).to_have_text("3 items (2 pending)")

    # First item is auto-selected and inspector is visible
    expect(app_page.locator("#review-detail-card")).not_to_have_class("panel hidden")
    expect(app_page.locator("#review-active-item-title")).to_have_text("rev_001")
    expect(app_page.locator("#review-status-badge")).to_have_text("PENDING")
    expect(app_page.locator("#review-source-text")).to_have_text("1O0.50")
    expect(app_page.locator("#review-output-text")).to_have_text("100.50")


def test_previous_next_navigation_and_bounds(app_page: Page) -> None:
    """Previous and Next buttons navigate between items and respect list bounds."""
    items = _make_review_items()
    app_page.route(
        "**/api/review*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "items": items}),
        ),
    )

    app_page.click(".nav-tab[data-screen='review']")
    app_page.evaluate(
        """async () => {
            const mod = await import("/js/screens/review.js");
            await mod.loadReviewQueue();
        }"""
    )

    prev_btn = app_page.locator("#btn-review-prev")
    next_btn = app_page.locator("#btn-review-next")

    # Item 0 (rev_001): prev is disabled, next is enabled
    expect(app_page.locator("#review-active-item-title")).to_have_text("rev_001")
    expect(prev_btn).to_be_disabled()
    expect(next_btn).to_be_enabled()

    # Click Next -> moves to item 1 (rev_002)
    next_btn.click()
    expect(app_page.locator("#review-active-item-title")).to_have_text("rev_002")
    expect(prev_btn).to_be_enabled()
    expect(next_btn).to_be_enabled()

    # Click Next -> moves to item 2 (rev_003)
    next_btn.click()
    expect(app_page.locator("#review-active-item-title")).to_have_text("rev_003")
    expect(prev_btn).to_be_enabled()
    expect(next_btn).to_be_disabled()

    # Click Prev -> returns to item 1 (rev_002)
    prev_btn.click()
    expect(app_page.locator("#review-active-item-title")).to_have_text("rev_002")


def test_action_enablement_and_unsupported_actions(app_page: Page) -> None:
    """Action buttons enable based on available_actions; validate_edit and retry do not exist."""
    items = _make_review_items()
    app_page.route(
        "**/api/review*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "items": items}),
        ),
    )

    app_page.click(".nav-tab[data-screen='review']")
    app_page.evaluate(
        """async () => {
            const mod = await import("/js/screens/review.js");
            await mod.loadReviewQueue();
        }"""
    )

    accept_btn = app_page.locator("#btn-review-accept")
    unresolved_btn = app_page.locator("#btn-review-dismiss")

    # Item 1 is pending -> accept & unresolved enabled
    expect(accept_btn).to_be_enabled()
    expect(unresolved_btn).to_be_enabled()

    # Verify that unsupported actions do not exist in the DOM
    expect(app_page.locator("#btn-review-validate")).to_have_count(0)
    expect(app_page.locator("#btn-review-retry")).to_have_count(0)


def test_status_badge_truthfulness(app_page: Page) -> None:
    """Status badge strictly displays truthful states: PENDING, ACCEPTED, UNRESOLVED."""
    items = _make_review_items()
    items[0]["status"] = "accepted"
    items[1]["status"] = "unresolved"
    items[2]["status"] = "pending"

    app_page.route(
        "**/api/review*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "items": items}),
        ),
    )

    app_page.click(".nav-tab[data-screen='review']")
    app_page.evaluate(
        """async () => {
            const mod = await import("/js/screens/review.js");
            await mod.loadReviewQueue();
        }"""
    )

    badge = app_page.locator("#review-status-badge")

    # Item 0: ACCEPTED
    expect(badge).to_have_text("ACCEPTED")
    expect(badge).to_have_class("badge badge-emerald")

    # Move to Item 1: UNRESOLVED
    app_page.click("#btn-review-next")
    expect(badge).to_have_text("UNRESOLVED")
    expect(badge).to_have_class("badge badge-crimson")

    # Move to Item 2: PENDING
    app_page.click("#btn-review-next")
    expect(badge).to_have_text("PENDING")
    expect(badge).to_have_class("badge badge-amber")


def test_inline_draft_box_handling(app_page: Page) -> None:
    """Inline draft proposal input saves draft locally without prompt() and preserves output text."""
    items = _make_review_items()
    app_page.route(
        "**/api/review*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "items": items}),
        ),
    )

    app_page.click(".nav-tab[data-screen='review']")
    app_page.evaluate(
        """async () => {
            const mod = await import("/js/screens/review.js");
            await mod.loadReviewQueue();
        }"""
    )

    draft_box = app_page.locator("#review-draft-box")
    expect(draft_box).to_have_class("review-draft-card hidden")

    # Click Propose Edit -> draft box becomes visible
    app_page.click("#btn-review-edit")
    expect(draft_box).not_to_have_class("hidden")

    # Type draft proposal and click Save Draft
    draft_input = app_page.locator("#review-draft-input")
    draft_input.fill("100.50 (verified)")
    app_page.click("#btn-review-save-draft")

    # Draft box is now hidden again
    expect(draft_box).to_have_class("review-draft-card hidden")

    # Proposed display is visible with draft value
    proposed_display = app_page.locator("#review-proposed-display")
    expect(proposed_display).not_to_have_class("hidden")
    expect(app_page.locator("#review-proposed-text")).to_have_text("100.50 (verified)")

    # Committed output text is NOT altered
    expect(app_page.locator("#review-output-text")).to_have_text("100.50")


def test_selection_preservation_across_queue_reload(app_page: Page) -> None:
    """Selected review item is preserved across re-renders when the item remains in the queue."""
    items = _make_review_items()
    current_items_holder = [items]

    def handle_review(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "items": current_items_holder[0]}),
        )

    app_page.route("**/api/review*", handle_review)

    app_page.click(".nav-tab[data-screen='review']")
    app_page.evaluate(
        """async () => {
            const mod = await import("/js/screens/review.js");
            await mod.loadReviewQueue();
        }"""
    )
    expect(app_page.locator("#review-active-item-title")).to_have_text("rev_001")

    # Click row 1 (rev_002)
    app_page.click("#review-queue-tbody tr.review-row[data-idx='1']")
    expect(app_page.locator("#review-active-item-title")).to_have_text("rev_002")

    # Update backend items (item 1 status changed to accepted)
    updated_items = _make_review_items()
    updated_items[1]["status"] = "accepted"
    current_items_holder[0] = updated_items

    # Reload queue
    app_page.evaluate(
        """async () => {
            const mod = await import("/js/screens/review.js");
            await mod.loadReviewQueue();
        }"""
    )

    # rev_002 should still be selected, and its badge updated to ACCEPTED
    expect(app_page.locator("#review-active-item-title")).to_have_text("rev_002")
    expect(app_page.locator("#review-status-badge")).to_have_text("ACCEPTED")
