"""Review intent extraction and validation for Mukha Web Server."""

from __future__ import annotations

from typing import Any

from sarathi.mukha.state import ReviewIntent


def parse_and_validate_review_intent(
    body: dict[str, Any],
) -> tuple[ReviewIntent | None, str | None, int]:
    """Parse and validate review intent from HTTP request body.

    Returns:
        (intent, error_message, http_status_code)
    """
    item_id = body.get("item_id")
    action = body.get("action_id") or body.get("action")
    attempt_id = body.get("attempt_id")
    run_id = body.get("run_id")

    if not isinstance(item_id, str) or not item_id.strip():
        return None, "item_id must be a non-empty string.", 400
    if not isinstance(action, str) or not action.strip():
        return None, "action or action_id must be a non-empty string.", 400
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        return None, "attempt_id must be a non-empty string.", 400
    if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
        return None, "run_id must be a non-empty string when provided.", 400

    act = action.strip()
    act_mapped = "validate_edit" if act == "edit" else ("unresolved" if act in ("dismiss", "unresolved") else act)
    if act_mapped not in ("accept", "validate_edit", "retry", "unresolved"):
        return None, f"Invalid review action: '{action}'.", 400

    # Fail-closed check: validate_edit and retry lack runtime capability contracts
    if act_mapped in ("validate_edit", "retry"):
        return None, f"Review action '{act_mapped}' is currently unsupported by runtime capability.", 400

    expected_rev = None
    if body.get("expected_revision") is not None:
        try:
            expected_rev = int(body["expected_revision"])
        except (ValueError, TypeError):
            return None, "expected_revision must be an integer.", 400

    intent = ReviewIntent(
        item_id=item_id.strip(),
        attempt_id=attempt_id.strip(),
        action_id=act_mapped,
        run_id=run_id.strip() if run_id else None,
        proposed_value=str(body["proposed_value"]) if body.get("proposed_value") is not None else None,
        expected_revision=expected_rev,
    )
    return intent, None, 200


def handle_review_post(handler: Any, body: dict[str, Any]) -> None:
    """Handle POST /api/review request dispatching."""
    intent, err_msg, status_code = parse_and_validate_review_intent(body)
    if err_msg is not None or intent is None:
        handler._send_json(status_code, {"ok": False, "error": err_msg or "Invalid review payload."})
        return

    applied = handler.mukha_app.apply_review_intent(intent)
    if not applied:
        handler._send_json(
            400,
            {
                "ok": False,
                "error": "Review intent rejected: foreign run, stale attempt, duplicate submission, or invalid item.",
            },
        )
        return

    handler._send_json(200, {"ok": True, "action": intent.action_id, "item_id": intent.item_id, "applied": True})
