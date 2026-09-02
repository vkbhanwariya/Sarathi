"""Retained Safe Terminal Run History for Darpana in Sarathi V2.

Defines:
- TerminalRunSummary: Privacy-filtered immutable terminal execution summary.
- TerminalRunHistoryStore: Persistent bounded JSONL/SQLite storage for historical run reopening.

Zero document content, raw filesystem paths, secrets, or raw exceptions are retained.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Sequence


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
        if not self.run_id or not isinstance(self.run_id, str):
            raise ValueError("run_id must be a non-empty string.")
        if not self.request_id or not isinstance(self.request_id, str):
            raise ValueError("request_id must be a non-empty string.")
        if not self.requirement or not isinstance(self.requirement, str):
            raise ValueError("requirement must be a non-empty string.")
        if not self.profile or not isinstance(self.profile, str):
            raise ValueError("profile must be a non-empty string.")
        if self.status not in ("completed", "failed", "cancelled"):
            raise ValueError(f"status must be 'completed', 'failed', or 'cancelled', got {self.status!r}.")
        if not self.start_time_utc or not isinstance(self.start_time_utc, str):
            raise ValueError("start_time_utc must be a non-empty string.")
        if not self.completed_at_utc or not isinstance(self.completed_at_utc, str):
            raise ValueError("completed_at_utc must be a non-empty string.")
        if not isinstance(self.duration_ms, int) or isinstance(self.duration_ms, bool) or self.duration_ms < 0:
            raise ValueError(f"duration_ms must be a non-negative integer, got {self.duration_ms!r}.")
        if not isinstance(self.artifact_count, int) or isinstance(self.artifact_count, bool) or self.artifact_count < 0:
            raise ValueError(f"artifact_count must be a non-negative integer, got {self.artifact_count!r}.")
        if not isinstance(self.warning_count, int) or isinstance(self.warning_count, bool) or self.warning_count < 0:
            raise ValueError(f"warning_count must be a non-negative integer, got {self.warning_count!r}.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to safe JSON dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TerminalRunSummary:
        """Construct a validated TerminalRunSummary from dictionary."""
        return cls(
            run_id=str(data["run_id"]),
            request_id=str(data["request_id"]),
            requirement=str(data["requirement"]),
            profile=str(data["profile"]),
            status=str(data["status"]),
            start_time_utc=str(data["start_time_utc"]),
            completed_at_utc=str(data["completed_at_utc"]),
            duration_ms=int(data["duration_ms"]),
            artifact_count=int(data["artifact_count"]),
            warning_count=int(data["warning_count"]),
            has_masked_identity=bool(data.get("has_masked_identity", False)),
            output_dir=str(data["output_dir"]) if data.get("output_dir") else None,
        )


class TerminalRunHistoryStore:
    """Thread-safe persistent historical store for terminal run summaries."""

    def __init__(
        self,
        history_path: Path,
        format: str = "jsonl",
        max_records: int = 1000,
    ) -> None:
        self._path = history_path.resolve()
        self._format = format.lower()
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
        except OSError:
            pass

    def save(self, summary: TerminalRunSummary) -> bool:
        """Persist a terminal run summary. Returns True on success, False on error."""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                if self._format == "jsonl":
                    line = json.dumps(summary.to_dict()) + "\n"
                    with open(self._path, "a", encoding="utf-8") as f:
                        f.write(line)
                    return True
                elif self._format == "sqlite":
                    with sqlite3.connect(str(self._path)) as conn:
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
                    return True
            except Exception:
                # Storage failures must never break the main document processing pipeline
                return False
        return False

    def query(self, limit: int = 50) -> tuple[TerminalRunSummary, ...]:
        """Query recent terminal run summaries ordered from newest to oldest."""
        if not self._path.exists():
            return ()

        with self._lock:
            try:
                if self._format == "jsonl":
                    lines = self._path.read_text(encoding="utf-8").splitlines()
                    results: list[TerminalRunSummary] = []
                    for line in reversed(lines):
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            results.append(TerminalRunSummary.from_dict(data))
                            if len(results) >= limit:
                                break
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
            except Exception:
                return ()
        return ()

    def get(self, run_id: str) -> TerminalRunSummary | None:
        """Find a specific terminal run by run_id."""
        for run in self.query(limit=self._max_records):
            if run.run_id == run_id:
                return run
        return None
