"""Canonical Artifact Boundary for Sarathi.

Single global boundary responsible for staging, atomic commits, run manifests,
and storage root lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.artifacts.paths import (
    _REQUIREMENT_IDENTIFIER_PATTERN,
    _RUN_ID_PATTERN,
    _validate_root_directory,
    _validate_root_separation,
)
from sarathi.nabhi.artifacts.workspace import RunWorkspace
from sarathi.sankalpa import ExecutionContext, InputRef

if TYPE_CHECKING:
    from sarathi.darpana import Darpana
    from sarathi.kavacha import Kavacha


class ArtifactBoundary:
    """Canonical Artifact Boundary for Sarathi.

    Single global boundary responsible for staging, atomic commits, run manifests,
    and storage root lifecycle.
    """

    def __init__(
        self,
        runtime_root: Path | str,
        output_root: Path | str,
        *,
        kavacha: Kavacha | None = None,
        darpana: Darpana | None = None,
    ) -> None:
        """Construct an ArtifactBoundary with explicit runtime and output roots.

        Args:
            runtime_root: Explicit path to the runtime storage directory.
            output_root: Explicit path to the output storage directory.
            kavacha: Optional injected Kavacha security service.
            darpana: Optional injected Darpana telemetry service.

        Raises:
            TypeError: If roots are not Path or str, or if kavacha/darpana are of invalid type.
            DoshError(FailureCode.INVALID_CONFIGURATION): On empty paths, non-directory paths,
                equal roots, or nested roots.
        """
        if darpana is not None:
            from sarathi.darpana import Darpana as DarpanaService

            if not isinstance(darpana, DarpanaService):
                raise TypeError(f"darpana must be a Darpana instance or None, got {type(darpana).__name__}.")

        if kavacha is not None:
            from sarathi.kavacha import Kavacha as KavachaService

            if not isinstance(kavacha, KavachaService):
                raise TypeError(f"kavacha must be a Kavacha instance or None, got {type(kavacha).__name__}.")

        validated_runtime = _validate_root_directory(runtime_root, "runtime_root")
        validated_output = _validate_root_directory(output_root, "output_root")
        _validate_root_separation(validated_runtime, validated_output)

        try:
            validated_runtime.mkdir(parents=True, exist_ok=True)
            validated_output.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="Failed to create root storage directories.",
            ) from err

        self._runtime_root: Path = validated_runtime
        self._output_root: Path = validated_output
        self._kavacha: Kavacha | None = kavacha
        self._darpana: Darpana | None = darpana

    @property
    def runtime_root(self) -> Path:
        """Return the active runtime root directory."""
        return self._runtime_root

    @property
    def output_root(self) -> Path:
        """Return the active output root directory."""
        return self._output_root

    @property
    def darpana(self) -> Darpana | None:
        """Return the injected Darpana telemetry service, if present."""
        return self._darpana

    def begin_run(
        self,
        run_id: str,
        requirement: str,
        *,
        output_root: Path | str | None = None,
        preserve_partial: bool = False,
        timestamp: datetime | None = None,
        input_sources: Sequence[Path | str | InputRef] = (),
        context: ExecutionContext | None = None,
    ) -> RunWorkspace:
        """Begin a run workspace for safe staging and atomic artifact commits.

        Args:
            run_id: Safe non-empty run identifier (e.g. 'run-1', 'run-001').
            requirement: Safe stable requirement identifier (e.g. 'ocr', 'bank_statements').
            output_root: Optional per-run output root override.
            preserve_partial: Whether incomplete artifacts should be retained under partial/.
            timestamp: Optional UTC timestamp override (used for deterministic run folder naming).
            input_sources: Optional input sources to validate against storage directory overlap.
            context: Optional execution context for telemetry propagation.

        Returns:
            An active RunWorkspace.

        Raises:
            TypeError: If arguments are of invalid types.
            DoshError(FailureCode.VALIDATION_FAILED): If run_id or requirement is malformed.
            DoshError(FailureCode.INVALID_CONFIGURATION): If output_root override is invalid or nested,
                or if input_sources are supplied without an injected Kavacha security service.
            DoshError(FailureCode.SECURITY_DENIED): If input sources overlap with staging or output roots.
        """
        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

        if not isinstance(run_id, str):
            raise TypeError(f"run_id must be a string, got {type(run_id).__name__}.")
        cleaned_run_id = run_id.strip()
        if not cleaned_run_id or not _RUN_ID_PATTERN.match(cleaned_run_id):
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="run_id must be a safe non-empty identifier (alphanumeric, '_', '-').",
            )

        if not isinstance(requirement, str):
            raise TypeError(f"requirement must be a string, got {type(requirement).__name__}.")
        if not _REQUIREMENT_IDENTIFIER_PATTERN.match(requirement):
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="requirement must be a safe stable identifier (lowercase letters, digits, '_' and '-' only).",
            )

        if not isinstance(preserve_partial, bool):
            raise TypeError(f"preserve_partial must be a bool, got {type(preserve_partial).__name__}.")

        if timestamp is not None:
            if not isinstance(timestamp, datetime):
                raise TypeError(f"timestamp must be a datetime instance or None, got {type(timestamp).__name__}.")
            if timestamp.tzinfo is None:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message="timestamp must be timezone-aware.",
                )

        if input_sources is None:
            raise TypeError("input_sources cannot be None; pass a sequence or omit.")
        if not isinstance(input_sources, (list, tuple)):
            raise TypeError(
                f"input_sources must be a sequence of Path, str, or InputRef, got {type(input_sources).__name__}."
            )

        for i, src in enumerate(input_sources):
            if not isinstance(src, (Path, str, InputRef)):
                raise TypeError(f"input_sources[{i}] must be a Path, str, or InputRef, got {type(src).__name__}.")

        if input_sources and self._kavacha is None:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="Kavacha security service must be injected to validate input source containment.",
            )

        # Active output root determination (validated first without mutating filesystem)
        if output_root is not None:
            active_output_root = _validate_root_directory(output_root, "output_root")
            _validate_root_separation(self._runtime_root, active_output_root)
        else:
            active_output_root = self._output_root

        # Candidate staging directory: Runtime/Work/<run-id>/
        staging_dir = self._runtime_root / "Work" / cleaned_run_id

        # Unique run directory: Output/<requirement>/Run-<timestamp>-<short-id>/
        ts = timestamp if timestamp is not None else datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y%m%d-%H%M%S")

        req_output_dir = active_output_root / requirement
        while True:
            short_id = uuid.uuid4().hex[:8].upper()
            run_dir_name = f"Run-{ts_str}-{short_id}"
            run_output_dir = req_output_dir / run_dir_name
            if not run_output_dir.exists():
                break

        # Validate input/output overlap via constructor-injected Kavacha if input_sources are provided
        # MUST execute BEFORE creating active_output_root or any run directories
        if input_sources:
            dest_roots_to_check = [self._runtime_root, active_output_root, staging_dir, run_output_dir]
            self._kavacha.validate_source_destination_overlap(input_sources, dest_roots_to_check)

        if output_root is not None:
            try:
                active_output_root.mkdir(parents=True, exist_ok=True)
            except OSError as err:
                raise DoshError(
                    code=FailureCode.INVALID_CONFIGURATION,
                    message="Failed to create custom output root.",
                ) from err

        return RunWorkspace(
            run_id=cleaned_run_id,
            requirement=requirement,
            staging_dir=staging_dir,
            output_dir=run_output_dir,
            preserve_partial=preserve_partial,
            start_time_utc=ts,
            darpana=self._darpana,
            context=context,
        )
