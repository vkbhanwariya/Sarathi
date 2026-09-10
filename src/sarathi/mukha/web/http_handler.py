"""Run-start response contracts retained while Mukha uses Starlette transport."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sarathi.mukha.web.security import (
    _ALLOWED_LOOPBACK_HOSTNAMES,
    _format_public_error,
    _is_authorized_loopback_host,
    _is_authorized_loopback_origin,
    _sanitize_message,
    _serialize_dataclass,
)


class StartRunStatus(StrEnum):
    """Result status of an attempt to start an interactive run."""

    OK = "ok"
    BUSY = "busy"
    INVALID_INPUTS = "invalid_inputs"


@dataclass(frozen=True, slots=True)
class StartRunResponse:
    """Typed result of an attempt to start an interactive run."""

    status: StartRunStatus
    run_id: str | None = None
    error_message: str | None = None


__all__ = [
    "StartRunResponse",
    "StartRunStatus",
    "_ALLOWED_LOOPBACK_HOSTNAMES",
    "_format_public_error",
    "_is_authorized_loopback_host",
    "_is_authorized_loopback_origin",
    "_sanitize_message",
    "_serialize_dataclass",
]
