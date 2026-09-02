"""Retained Safe Terminal Run History for Darpana in Sarathi V2.

Defines:
- TerminalRunSummary: Privacy-filtered immutable terminal execution summary.
- TerminalRunHistoryStore: Persistent bounded JSONL/SQLite storage for historical run reopening.

Zero document content, raw filesystem paths, secrets, or raw exceptions are retained.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
from typing import Any, Sequence
import uuid

_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_SAFE_ISO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")
_SAFE_REL_PATH_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+(/[a-zA-Z0-9_.\-]+)*$")


@dataclass(frozen=True, slots=True)
class TerminalRunSummary:
    """Privacy-filtered factual terminal run summary for history and reopening."""

    run_id: str
    request_id: str
    requirement: str
    profile: str
    status: str
    start_time_utc: str
    completed_at_utc: str
    duration_ms: int
    artifact_count: int
    warning_count: int
    has_masked_identity: bool = False
    output_dir: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _SAFE_IDENTIFIER_PATTERN.match(self.run_id):
            raise ValueError(f"run_id must be a safe non-empty identifier, got {self.run_id!r}.")
        if not isinstance(self.request_id, str) or not _SAFE_IDENTIFIER_PATTERN.match(self.request_id):
            raise ValueError(f"request_id must be a safe non-empty identifier, got {self.request_id!r}.")
        if not isinstance(self.requirement, str) or not _SAFE_IDENTIFIER_PATTERN.match(self.requirement):
            raise ValueError(f"requirement must be a safe non-empty identifier, got {self.requirement!r}.")
        if not isinstance(self.profile, str) or not _SAFE_IDENTIFIER_PATTERN.match(self.profile):
            raise ValueError(f"profile must be a safe non-empty identifier, got {self.profile!r}.")
        if self.status not in ("completed", "failed", "cancelled"):
            raise ValueError(f"status must be 'completed', 'failed', or 'cancelled', got {self.status!r}.")
        if not isinstance(self.start_time_utc, str) or not _SAFE_ISO_PATTERN.match(self.start_time_utc):
            raise ValueError(f"start_time_utc must be a valid ISO-8601 timestamp string, got {self.start_time_utc!r}.")
        if not isinstance(self.completed_at_utc, str) or not _SAFE_ISO_PATTERN.match(self.completed_at_utc):
            raise ValueError(f"completed_at_utc must be a valid ISO-8601 timestamp string, got {self.completed_at_utc!r}.")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0:
            raise ValueError(f"duration_ms must be a non-negative integer, got {self.duration_ms!r}.")
        if isinstance(self.artifact_count, bool) or not isinstance(self.artifact_count, int) or self.artifact_count < 0:
            raise ValueError(f"artifact_count must be a non-negative integer, got {self.artifact_count!r}.")
        if isinstance(self.warning_count, bool) or not isinstance(self.warning_count, int) or self.warning_count < 0:
            raise ValueError(f"warning_count must be a non-negative integer, got {self.warning_count!r}.")
        if not isinstance(self.has_masked_identity, bool):
            raise ValueError(f"has_masked_identity must be a bool, got {self.has_masked_identity!r}.")
        if self.output_dir is not None:
            if not isinstance(self.output_dir, str) or "\\" in self.output_dir or ".." in self.output_dir or self.output_dir.startswith("/"):
                raise ValueError(f"output_dir must be a safe relative run reference, got {self.output_dir!r}.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to safe JSON dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TerminalRunSummary:
        """Construct a validated TerminalRunSummary from dictionary without unsafe type coercion."""
        if not isinstance(data, dict):
            raise TypeError(f"data must be a dict, got {type(data).__name__}.")

        required_str_fields = (
            "run_id",
            "request_id",
            "requirement",
            "profile",
            "status",
            "start_time_utc",
            "completed_at_utc",
        )
        for f in required_str_fields:
            val = data.get(f)
            if not isinstance(val, str):
                raise TypeError(f"Field '{f}' must be a string, got {type(val).__name__}.")

        required_int_fields = ("duration_ms", "artifact_count", "warning_count")
        for f in required_int_fields:
            val = data.get(f)
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"Field '{f}' must be an integer, got {type(val).__name__}.")

        has_masked = data.get("has_masked_identity", False)
        if not isinstance(has_masked, bool):
            raise TypeError(f"Field 'has_masked_identity' must be a bool, got {type(has_masked).__name__}.")

        out_dir = data.get("output_dir")
        if out_dir is not None and not isinstance(out_dir, str):
            raise TypeError(f"Field 'output_dir' must be a string or None, got {type(out_dir).__name__}.")

        return cls(
            run_id=data["run_id"],
            request_id=data["request_id"],
            requirement=data["requirement"],
            profile=data["profile"],
            status=data["status"],
            start_time_utc=data["start_time_utc"],
            completed_at_utc=data["completed_at_utc"],
            duration_ms=data["duration_ms"],
            artifact_count=data["artifact_count"],
            warning_count=data["warning_count"],
            has_masked_identity=has_masked,
            output_dir=out_dir,
        )


class TerminalRunHistoryStore:
    """Thread-safe persistent historical store for terminal run summaries."""

    def __init__(
        self,
        history_path: Path,
        format: str = "jsonl",
        max_records: int = 1000,
    ) -> None:
        if not isinstance(history_path, (Path, str)):
            raise TypeError(f"history_path must be a Path or str, got {type(history_path).__name__}.")
        fmt = str(format).lower().strip()
        if fmt not in ("jsonl", "sqlite"):
            raise ValueError(f"format must be 'jsonl' or 'sqlite', got {format!r}.")
        if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records <= 0:
            raise ValueError(f"max_records must be a positive integer, got {max_records!r}.")

        self._path = Path(history_path).resolve()
        self._format = fmt
        self._max_records = max_records
        self._lock = threading.Lock()

        if self._format == "sqlite":
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        """Initialize SQLite table for terminal runs."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self._path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS terminal_runs (
                        run_id TEXT PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        requirement TEXT NOT NULL,
                        profile TEXT NOT NULL,
                        status TEXT NOT NULL,
                        start_time_utc TEXT NOT NULL,
                        completed_at_utc TEXT NOT NULL,
                        duration_ms INTEGER NOT NULL,
                        artifact_count INTEGER NOT NULL,
                        warning_count INTEGER NOT NULL,
                        has_masked_identity INTEGER NOT NULL,
                        output_dir TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_completed_at ON terminal_runs (completed_at_utc DESC)"
                )
        except (OSError, sqlite3.Error):
            pass

    def save(self, summary: TerminalRunSummary) -> bool:
        """Persist a terminal run summary with bounded capacity. Returns True on success, False on error."""
        if not isinstance(summary, TerminalRunSummary):
            raise TypeError(f"summary must be a TerminalRunSummary instance, got {type(summary).__name__}.")

        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                if self._format == "jsonl":
                    from collections import deque

                    # Read only bounded tail into memory
                    tail_lines: deque[str] = deque(maxlen=self._max_records)
                    if self._path.exists():
                        with open(self._path, "r", encoding="utf-8") as f:
                            for line in f:
                                stripped = line.strip()
                                if stripped:
                                    tail_lines.append(stripped)

                    # Append new record (deque automatically maintains maxlen=self._max_records)
                    new_line = json.dumps(summary.to_dict(), ensure_ascii=False)
                    tail_lines.append(new_line)

                    # Atomic write
                    temp_file = self._path.parent / f".tmp_{uuid.uuid4().hex}_{self._path.name}"
                    with open(temp_file, "w", encoding="utf-8") as f:
                        for l in tail_lines:
                            f.write(l + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                    temp_file.replace(self._path)
                    return True

                elif self._format == "sqlite":
                    with sqlite3.connect(str(self._path)) as conn:
                        with conn:
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO terminal_runs (
                                    run_id, request_id, requirement, profile, status,
                                    start_time_utc, completed_at_utc, duration_ms,
                                    artifact_count, warning_count, has_masked_identity, output_dir
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    summary.run_id,
                                    summary.request_id,
                                    summary.requirement,
                                    summary.profile,
                                    summary.status,
                                    summary.start_time_utc,
                                    summary.completed_at_utc,
                                    summary.duration_ms,
                                    summary.artifact_count,
                                    summary.warning_count,
                                    1 if summary.has_masked_identity else 0,
                                    summary.output_dir,
                                ),
                            )
                            # Bounded retention pruning
                            conn.execute(
                                """
                                DELETE FROM terminal_runs
                                WHERE run_id NOT IN (
                                    SELECT run_id FROM terminal_runs
                                    ORDER BY completed_at_utc DESC
                                    LIMIT ?
                                )
                                """,
                                (self._max_records,),
                            )
                    return True
            except (OSError, sqlite3.Error):
                return False
        return False

    def query(self, limit: int = 50) -> tuple[TerminalRunSummary, ...]:
        """Query recent terminal runs in reverse chronological order up to limit."""
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be a positive integer.")

        with self._lock:
            try:
                results: list[TerminalRunSummary] = []
                if self._format == "jsonl":
                    if not self._path.exists():
                        return ()

                    from collections import deque

                    bounded_tail: deque[str] = deque(maxlen=limit)
                    with open(self._path, "r", encoding="utf-8") as f:
                        for line in f:
                            s = line.strip()
                            if s:
                                bounded_tail.append(s)

                    for line in reversed(bounded_tail):
                        try:
                            data = json.loads(line)
                            results.append(TerminalRunSummary.from_dict(data))
                        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                            continue
                    return tuple(results)

                elif self._format == "sqlite":
                    with sqlite3.connect(str(self._path)) as conn:
                        cursor = conn.execute(
                            """
                            SELECT run_id, request_id, requirement, profile, status,
                                   start_time_utc, completed_at_utc, duration_ms,
                                   artifact_count, warning_count, has_masked_identity, output_dir
                            FROM terminal_runs
                            ORDER BY completed_at_utc DESC
                            LIMIT ?
                            """,
                            (limit,),
                        )
                        rows = cursor.fetchall()
                        results = []
                        for row in rows:
                            results.append(
                                TerminalRunSummary(
                                    run_id=row[0],
                                    request_id=row[1],
                                    requirement=row[2],
                                    profile=row[3],
                                    status=row[4],
                                    start_time_utc=row[5],
                                    completed_at_utc=row[6],
                                    duration_ms=row[7],
                                    artifact_count=row[8],
                                    warning_count=row[9],
                                    has_masked_identity=bool(row[10]),
                                    output_dir=row[11],
                                )
                            )
                        return tuple(results)
            except (OSError, sqlite3.Error):
                return ()
        return ()

    def get(self, run_id: str) -> TerminalRunSummary | None:
        """Find a specific terminal run by run_id."""
        if not isinstance(run_id, str) or not run_id.strip():
            return None
        for run in self.query(limit=self._max_records):
            if run.run_id == run_id:
                return run
        return None
