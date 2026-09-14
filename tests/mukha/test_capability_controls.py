"""Tests for Mukha capability-driven dynamic parameter controls."""

from __future__ import annotations

from unittest.mock import MagicMock

from sarathi.mukha.state import ActionParameterView
from sarathi.mukha.web.security import _serialize_dataclass
from sarathi.mukha.web.state_builder import _build_action_parameters, build_application_view_state


def test_action_parameter_view_serialization() -> None:
    param = ActionParameterView(
        parameter_id="profile",
        display_name="OCR Execution Profile",
        kind="select",
        default_value="instant",
        options=(("instant", "Instant"), ("accurate", "Accurate")),
        is_required=True,
    )
    data = _serialize_dataclass(param)
    assert data["parameter_id"] == "profile"
    assert data["display_name"] == "OCR Execution Profile"
    assert data["kind"] == "select"
    assert data["default_value"] == "instant"
    assert len(data["options"]) == 2
    assert data["is_required"] is True


def test_build_action_parameters_ocr() -> None:
    params = _build_action_parameters("ocr")
    assert len(params) >= 3
    param_ids = [p.parameter_id for p in params]
    assert "profile" in param_ids
    assert "lang" in param_ids
    assert "preprocess" in param_ids

    profile_param = next(p for p in params if p.parameter_id == "profile")
    assert profile_param.kind == "select"
    assert profile_param.default_value == "instant"
    option_keys = [opt[0] for opt in profile_param.options]
    assert "instant" in option_keys
    assert "accurate" in option_keys
    assert "custom" in option_keys


def test_build_action_parameters_font_conversion() -> None:
    params = _build_action_parameters("font_conversion")
    assert len(params) == 2
    param_ids = [p.parameter_id for p in params]
    assert "source_font" in param_ids
    assert "font_mode" in param_ids

    source_param = next(p for p in params if p.parameter_id == "source_font")
    assert source_param.default_value == ""
    assert any("krutidev" in opt[0] for opt in source_param.options)


def test_build_action_parameters_empty_fallback() -> None:
    params = _build_action_parameters("unknown_action")
    assert params == ()


def test_application_view_state_includes_parameters() -> None:
    mock_agni = MagicMock()
    mock_runner = MagicMock()
    mock_snapshot = MagicMock()
    mock_snapshot.run_id = None
    mock_snapshot.is_alive = False
    mock_snapshot.terminal_status = None
    mock_snapshot.progress = None
    mock_runner.get_active_snapshot.return_value = mock_snapshot
    mock_runner.get_active_progress.return_value = None
    mock_runner.last_result = None

    mock_cap = MagicMock()
    mock_cap.capability_id = "ocr"
    mock_cap.name = "OCR"
    mock_agni.kosh.capabilities.return_value = [mock_cap]
    mock_agni.darpana = None

    state = build_application_view_state(mock_agni, mock_runner, "127.0.0.1", 8765)
    actions = {a.action_id: a for a in state.available_actions}
    assert "ocr" in actions
    ocr_action = actions["ocr"]
    assert len(ocr_action.parameters) > 0
    assert any(p.parameter_id == "profile" for p in ocr_action.parameters)
