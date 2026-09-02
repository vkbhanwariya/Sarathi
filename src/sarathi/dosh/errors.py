"""Dosh — Error System for Sarathi V2.

Defines the small common failure vocabulary required across the system:
- FailureCode: Canonical failure classifications.
- DoshError: Single typed canonical exception.

Dosh classifies and represents failures only; pipeline lifecycle decisions,
quarantine, retry, security enforcement, and telemetry remain with their
respective owners.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class FailureCode(StrEnum):
    """Canonical operational failure classifications."""

    UNSUPPORTED = "unsupported"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    EXECUTION_FAILED = "execution_failed"
    INVALID_CONFIGURATION = "invalid_configuration"
    VALIDATION_FAILED = "validation_failed"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    SECURITY_DENIED = "security_denied"


class DoshError(Exception):
    """Canonical typed Sarathi exception for classified operational failures."""

    def __init__(
        self,
        code: FailureCode,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(code, FailureCode):
            raise TypeError(f"code must be a FailureCode enum instance, got {type(code).__name__} ({code!r}).")

        if not isinstance(message, str):
            raise TypeError(f"message must be a string, got {type(message).__name__}.")

        cleaned_msg = message.strip()
        if not cleaned_msg:
            raise ValueError("message must be a non-empty string.")

        if context is not None and not isinstance(context, Mapping):
            raise TypeError(f"context must be a Mapping or None, got {type(context).__name__}.")

        self.code: FailureCode = code
        self.message: str = cleaned_msg
        self.context: Mapping[str, Any] = MappingProxyType(dict(context) if context else {})
        super().__init__(f"[{self.code.value}] {self.message}")
