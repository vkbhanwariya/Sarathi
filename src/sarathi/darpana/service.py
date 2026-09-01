"""Darpana - Telemetry & Tracing Service for Sarathi V2.

Exposes:
- Darpana: Injected telemetry service maintaining thread-safe bounded in-memory histories
  for Maruti runtime records and Pramana quality observations.

Contains no decision logic (no retry, fallback, execution strategy, or device allocation).
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import threading
import time
from typing import Any, Iterator, Mapping

from sarathi.darpana.maruti import MarutiRecord
from sarathi.darpana.pramana import PramanaRecord
from sarathi.sankalpa import ExecutionContext


class Darpana:
    """Thread-safe bounded in-memory telemetry service."""

    def __init__(self, capacity: int) -> None:
        if not isinstance(capacity, int) or isinstance(capacity, bool):
            raise TypeError(f"capacity must be an integer, got {type(capacity).__name__}.")
        if capacity <= 0:
            raise ValueError(f"capacity must be a positive integer (> 0), got {capacity}.")

        self._capacity: int = capacity
        self._lock: threading.Lock = threading.Lock()
        self._maruti_history: deque[MarutiRecord] = deque(maxlen=capacity)
        self._pramana_history: deque[PramanaRecord] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        """Return the maximum bounded capacity for each telemetry history."""
        return self._capacity

    def record_maruti(self, record: MarutiRecord) -> None:
        """Record a structured Maruti runtime performance event."""
        if not isinstance(record, MarutiRecord):
            raise TypeError(f"record must be a MarutiRecord instance, got {type(record).__name__}.")
        with self._lock:
            self._maruti_history.append(record)

    def record_pramana(self, record: PramanaRecord) -> None:
        """Record a structured Pramana quality observation."""
        if not isinstance(record, PramanaRecord):
            raise TypeError(f"record must be a PramanaRecord instance, got {type(record).__name__}.")
        with self._lock:
            self._pramana_history.append(record)

    @contextmanager
    def time_scope(
        self,
        context: ExecutionContext,
        phase_name: str,
        component: str,
        *,
        attributes: Mapping[str, Any] | None = None,
    ) -> Iterator[None]:
        """Context manager timing a block of execution and recording a MarutiRecord.

        Validates all instrumentation arguments before execution begins.
        Records outcome='success' on normal exit.
        Records outcome='failure', exception type name, and FailureCode (if DoshError) if any BaseException occurs,
        then re-raises without leaking raw exception message text.
        """
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")

        if not isinstance(phase_name, str) or not phase_name.strip():
            raise ValueError("phase_name must be a non-empty string.")

        if not isinstance(component, str) or not component.strip():
            raise ValueError("component must be a non-empty string.")

        if attributes is not None and not isinstance(attributes, Mapping):
            raise TypeError(f"attributes must be a Mapping or None, got {type(attributes).__name__}.")

        safe_attributes = dict(attributes) if attributes else {}

        start_time_utc = datetime.now(timezone.utc).isoformat()
        start_ns = time.perf_counter_ns()
        try:
            yield
            duration_ns = max(0, time.perf_counter_ns() - start_ns)
            record = MarutiRecord(
                run_id=context.run_id,
                request_id=context.request_id,
                trace_id=context.trace_id,
                span_id=context.span_id,
                phase_name=phase_name.strip(),
                component=component.strip(),
                timestamp_utc=start_time_utc,
                duration_ns=duration_ns,
                outcome="success",
                error_type=None,
                failure_code=None,
                attributes=safe_attributes,
            )
            self.record_maruti(record)
        except BaseException as exc:
            duration_ns = max(0, time.perf_counter_ns() - start_ns)
            from sarathi.dosh import DoshError

            f_code = exc.code if isinstance(exc, DoshError) else None

            record = MarutiRecord(
                run_id=context.run_id,
                request_id=context.request_id,
                trace_id=context.trace_id,
                span_id=context.span_id,
                phase_name=phase_name.strip(),
                component=component.strip(),
                timestamp_utc=start_time_utc,
                duration_ns=duration_ns,
                outcome="failure",
                error_type=type(exc).__name__,
                failure_code=f_code,
                attributes=safe_attributes,
            )
            self.record_maruti(record)
            raise

    def maruti_records(self) -> tuple[MarutiRecord, ...]:
        """Return an immutable snapshot of recent Maruti runtime records."""
        with self._lock:
            return tuple(self._maruti_history)

    def pramana_records(self) -> tuple[PramanaRecord, ...]:
        """Return an immutable snapshot of recent Pramana quality observations."""
        with self._lock:
            return tuple(self._pramana_history)
