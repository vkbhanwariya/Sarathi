"""Unit tests for Dosh — Error System."""

import pytest

import sarathi.dosh as dosh_module
from sarathi.dosh import DoshError, FailureCode


class TestFailureCode:
    def test_canonical_failure_codes_exist_and_exact_count(self) -> None:
        expected_codes = {
            "unsupported": FailureCode.UNSUPPORTED,
            "dependency_unavailable": FailureCode.DEPENDENCY_UNAVAILABLE,
            "execution_failed": FailureCode.EXECUTION_FAILED,
            "invalid_configuration": FailureCode.INVALID_CONFIGURATION,
            "validation_failed": FailureCode.VALIDATION_FAILED,
            "resource_unavailable": FailureCode.RESOURCE_UNAVAILABLE,
            "security_denied": FailureCode.SECURITY_DENIED,
            "operation_cancelled": FailureCode.OPERATION_CANCELLED,
        }
        assert len(FailureCode) == 8
        for val, enum_member in expected_codes.items():
            assert enum_member.value == val


class TestDoshError:
    def test_valid_construction_with_enum(self) -> None:
        err = DoshError(
            code=FailureCode.UNSUPPORTED,
            message="Document format is not supported.",
            context={"format": "unknown_binary", "secret_key": "sensitive_data"},
        )
        assert err.code is FailureCode.UNSUPPORTED
        assert err.message == "Document format is not supported."
        assert err.context["format"] == "unknown_binary"
        assert str(err) == "[unsupported] Document format is not supported."

        # Verify repr does not expose context values
        error_repr = repr(err)
        assert "sensitive_data" not in error_repr
        assert "unknown_binary" not in error_repr

    def test_string_code_rejected_with_type_error(self) -> None:
        # Strict typing: callers must explicitly supply FailureCode enum, not raw strings
        with pytest.raises(TypeError, match="code must be a FailureCode enum instance"):
            DoshError(
                code="execution_failed",  # type: ignore
                message="Execution failed unexpectedly.",
            )

        with pytest.raises(TypeError, match="code must be a FailureCode enum instance"):
            DoshError(
                code="unsupported",  # type: ignore
                message="Unsupported format.",
            )

    def test_non_enum_object_code_rejected_with_type_error(self) -> None:
        with pytest.raises(TypeError, match="code must be a FailureCode enum instance"):
            DoshError(
                code=123,  # type: ignore
                message="Some failure.",
            )

        with pytest.raises(TypeError, match="code must be a FailureCode enum instance"):
            DoshError(
                code=None,  # type: ignore
                message="Some failure.",
            )

    def test_context_immutability(self) -> None:
        err = DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Running balance reconciliation mismatch.",
            context={"expected": "1000.00", "actual": "950.00"},
        )
        with pytest.raises(TypeError):
            err.context["expected"] = "2000.00"  # type: ignore

    def test_empty_or_whitespace_message_rejected(self) -> None:
        with pytest.raises(ValueError, match="message must be a non-empty string"):
            DoshError(code=FailureCode.EXECUTION_FAILED, message="")

        with pytest.raises(ValueError, match="message must be a non-empty string"):
            DoshError(code=FailureCode.EXECUTION_FAILED, message="   ")

    def test_non_string_message_rejected(self) -> None:
        with pytest.raises(TypeError, match="message must be a string"):
            DoshError(code=FailureCode.EXECUTION_FAILED, message=12345)  # type: ignore

    def test_invalid_context_type_rejected(self) -> None:
        with pytest.raises(TypeError, match="context must be a Mapping or None"):
            DoshError(code=FailureCode.SECURITY_DENIED, message="Denied", context=["not", "a", "mapping"])  # type: ignore

    def test_exception_chaining(self) -> None:
        try:
            try:
                raise FileNotFoundError("Missing model weights file")
            except FileNotFoundError as original:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Model weights could not be loaded.",
                    context={"engine": "indictrans2"},
                ) from original
        except DoshError as captured:
            assert isinstance(captured.__cause__, FileNotFoundError)
            assert str(captured.__cause__) == "Missing model weights file"
            assert captured.code is FailureCode.DEPENDENCY_UNAVAILABLE

    def test_dosh_exports(self) -> None:
        expected = {"DoshError", "FailureCode"}
        assert set(dosh_module.__all__) == expected
        for name in expected:
            assert hasattr(dosh_module, name)
