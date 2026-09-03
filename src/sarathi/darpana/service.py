"""Darpana - Telemetry & Tracing Service for Sarathi V2.

Exposes:
- Darpana: Injected telemetry service maintaining thread-safe bounded in-memory histories
  for Maruti runtime records and Pramana quality observations.

Contains no decision logic (no retry, fallback, execution strategy, or device allocation).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from sarathi.darpana.history import TerminalRunHistoryStore, TerminalRunSummary
from sarathi.darpana.maruti import MarutiRecord
from sarathi.darpana.pramana import PramanaRecord
from sarathi.sankalpa import ExecutionContext


class Darpana:
    """Thread-safe bounded in-memory and persistent telemetry service."""

    def __init__(
        self,
        capacity: int = 1000,
        history_path: Path | None = None,
        history_format: str = "jsonl",
        history_max_records: int = 1000,
    ) -> None:
        if not isinstance(capacity, int) or isinstance(capacity, bool):
            raise TypeError(f"capacity must be an integer, got {type(capacity).__name__}.")
        if capacity <= 0:
            raise ValueError(f"capacity must be a positive integer (> 0), got {capacity}.")

        self._capacity: int = capacity
        self._lock: threading.Lock = threading.Lock()
        self._maruti_history: deque[MarutiRecord] = deque(maxlen=capacity)
        self._pramana_history: deque[PramanaRecord] = deque(maxlen=capacity)
        self._run_summaries: deque[TerminalRunSummary] = deque(maxlen=capacity)
        self._history_persistence_failed: bool = False
        self._history_store: TerminalRunHistoryStore | None = (
            TerminalRunHistoryStore(history_path, format=history_format, max_records=history_max_records)
            if history_path is not None
            else None
        )

    @property
    def capacity(self) -> int:
        """Return the maximum bounded capacity for each telemetry history."""
        return self._capacity

    @property
    def history_persistence_failed(self) -> bool:
        """Return True if any historical run summary persistence failed."""
        return self._history_persistence_failed

    def record_run_summary(self, summary: TerminalRunSummary) -> None:
        """Record a privacy-filtered terminal run summary in memory and to configured persistent history."""
        if not isinstance(summary, TerminalRunSummary):
            raise TypeError(f"summary must be a TerminalRunSummary instance, got {type(summary).__name__}.")
        with self._lock:
            self._run_summaries.append(summary)
        if self._history_store is not None:
            saved = self._history_store.save(summary)
            if not saved:
                self._history_persistence_failed = True
                self.record_maruti(
                    MarutiRecord(
                        run_id=summary.run_id,
                        request_id=summary.request_id,
                        trace_id=f"tr-{summary.run_id}",
                        span_id=f"sp-{summary.run_id[:8]}",
                        phase_name="telemetry.history_persistence_failure",
                        component="darpana.history",
                        timestamp_utc=datetime.now(timezone.utc).isoformat(),
                        duration_ns=0,
                        outcome="failure",
                        attributes={"run_id": summary.run_id},
                    )
                )

    def query_run_history(self, limit: int = 50) -> tuple[TerminalRunSummary, ...]:
        """Query recent terminal run summaries from persistent store or in-memory history."""
        if self._history_store is not None:
            persisted = self._history_store.query(limit=limit)
            if persisted:
                return persisted
        with self._lock:
            return tuple(list(self._run_summaries)[-limit:][::-1])

    def get_run_summary(self, run_id: str) -> TerminalRunSummary | None:
        """Retrieve a specific terminal run summary by run_id."""
        with self._lock:
            for summary in self._run_summaries:
                if summary.run_id == run_id:
                    return summary
        if self._history_store is not None:
            return self._history_store.get(run_id)
        return None

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

    def start(self) -> None:
        """Start Darpana telemetry service (no-op; initializes on instantiation)."""
        pass

    def close(self) -> None:
        """Flush and close underlying persistent history store if configured."""
        if self._history_store is not None:
            self._history_store.close()
