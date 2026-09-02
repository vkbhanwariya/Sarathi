"""Cancellation Contracts for Sarathi V2.

Defines:
- CancellationToken: Thread-safe cooperative cancellation token for execution pipelines.
"""

from __future__ import annotations

import threading


class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Signal cancellation request."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """Return True if cancellation has been requested."""
        return self._event.is_set()

    def check_cancelled(self) -> None:
        """Raise DoshError(FailureCode.EXECUTION_FAILED) if cancellation was requested."""
        if self._event.is_set():
            from sarathi.dosh import DoshError, FailureCode

            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Execution was cancelled.",
                context={"cancelled": True},
            )

    def __repr__(self) -> str:
        return f"CancellationToken(cancelled={self.is_cancelled})"
