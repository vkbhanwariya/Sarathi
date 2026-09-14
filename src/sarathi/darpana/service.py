"""Darpana - Telemetry & Tracing Service for Sarathi.

Exposes:
- Darpana: Injected telemetry service maintaining thread-safe bounded in-memory histories
  for Maruti runtime records and Pramana quality observations.

Contains no decision logic (no retry, fallback, execution strategy, or device allocation).
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from sarathi.darpana.history import TerminalRunHistoryStore, TerminalRunSummary
from sarathi.darpana.maruti import MarutiRecord
from sarathi.darpana.pramana import PramanaRecord
from sarathi.dosh import DoshError, FailureCode
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
        self._active_spans: dict[str, dict[str, Any]] = {}
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
        """Query recent terminal summaries without hiding current-process records after persistence failures."""
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be a positive integer.")

        with self._lock:
            memory = tuple(reversed(self._run_summaries))

        if self._history_store is None:
            return memory[:limit]

        persisted = self._history_store.query(limit=limit)
        combined: list[TerminalRunSummary] = []
        seen_run_ids: set[str] = set()
        for summary in (*memory, *persisted):
            if summary.run_id in seen_run_ids:
                continue
            combined.append(summary)
            seen_run_ids.add(summary.run_id)
            if len(combined) >= limit:
                break
        return tuple(combined)

    def get_run_summary(self, run_id: str) -> TerminalRunSummary | None:
        """Retrieve a specific terminal run summary by run_id."""
        with self._lock:
            for summary in self._run_summaries:
                if summary.run_id == run_id:
                    return summary
        if self._history_store is not None:
            return self._history_store.get(run_id)
        return None

    def clear_history(self) -> bool:
        """Clear historical run summaries, telemetry records, and persistent history store."""
        with self._lock:
            self._run_summaries.clear()
            self._maruti_history.clear()
            self._pramana_history.clear()
            self._history_persistence_failed = False
        if self._history_store is not None:
            return self._history_store.clear()
        return True

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
        """Time a block and record one Maruti outcome without swallowing failures."""
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")
        if not isinstance(phase_name, str) or not phase_name.strip():
            raise ValueError("phase_name must be a non-empty string.")
        if not isinstance(component, str) or not component.strip():
            raise ValueError("component must be a non-empty string.")
        if attributes is not None and not isinstance(attributes, Mapping):
            raise TypeError(f"attributes must be a Mapping or None, got {type(attributes).__name__}.")

        normalized_phase = phase_name.strip()
        normalized_component = component.strip()
        safe_attributes = dict(attributes) if attributes else {}
        start_time_utc = datetime.now(timezone.utc).isoformat()
        start_ns = time.perf_counter_ns()
        scope_key = f"{context.span_id}-{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._active_spans[scope_key] = {
                "run_id": context.run_id,
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "span_id": context.span_id,
                "phase_name": normalized_phase,
                "component": normalized_component,
                "start_time_utc": start_time_utc,
                "attributes": safe_attributes,
            }

        outcome = "success"
        error_type: str | None = None
        failure_code: FailureCode | None = None
        try:
            yield
        except BaseException as exc:
            failure_code = exc.code if isinstance(exc, DoshError) else None
            is_cancelled = (
                failure_code == FailureCode.OPERATION_CANCELLED
                or bool(isinstance(exc, DoshError) and exc.context.get("cancelled"))
                or (context.cancellation_token is not None and context.cancellation_token.is_cancelled)
            )
            outcome = "cancelled" if is_cancelled else "failure"
            error_type = type(exc).__name__
            raise
        finally:
            duration_ns = max(0, time.perf_counter_ns() - start_ns)
            try:
                self.record_maruti(
                    MarutiRecord(
                        run_id=context.run_id,
                        request_id=context.request_id,
                        trace_id=context.trace_id,
                        span_id=context.span_id,
                        phase_name=normalized_phase,
                        component=normalized_component,
                        timestamp_utc=start_time_utc,
                        duration_ns=duration_ns,
                        outcome=outcome,
                        error_type=error_type,
                        failure_code=failure_code,
                        attributes=safe_attributes,
                    )
                )
            finally:
                with self._lock:
                    self._active_spans.pop(scope_key, None)

    def active_spans(self) -> tuple[dict[str, Any], ...]:
        """Return an immutable snapshot of currently active in-flight execution spans."""
        with self._lock:
            return tuple(dict(s) for s in self._active_spans.values())

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
