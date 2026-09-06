"""Active run workspace providing staging, atomic commit, manifest generation, and cleanup."""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.artifacts.atomic_io import _write_bytes_atomically
from sarathi.nabhi.artifacts.finalization import (
    cleanup_workspace_on_failure,
    finalize_run_workspace,
)
from sarathi.nabhi.artifacts.paths import (
    _check_symlink_escape,
    _is_path_relative_to,
)
from sarathi.nabhi.artifacts.promotion import (
    normalize_path_key,
    preserve_partial_artifact_file,
    promote_direct_artifact,
    promote_staged_artifact,
    resolve_relative_path,
)
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactRef,
    ExecutionContext,
    ProvenanceRecord,
    WarningRecord,
)

if TYPE_CHECKING:
    from sarathi.darpana import Darpana


class RunWorkspace:
    """Active run workspace providing staging, atomic commit, manifest generation, and cleanup.

    Managed exclusively by ArtifactBoundary.
    """

    def __init__(
        self,
        run_id: str,
        requirement: str,
        staging_dir: Path,
        output_dir: Path,
        preserve_partial: bool = False,
        start_time_utc: datetime | None = None,
        darpana: Darpana | None = None,
        context: ExecutionContext | None = None,
    ) -> None:
        if darpana is not None:
            from sarathi.darpana import Darpana as DarpanaService

            if not isinstance(darpana, DarpanaService):
                raise TypeError(f"darpana must be a Darpana instance or None, got {type(darpana).__name__}.")
        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

        self._run_id: str = run_id
        self._requirement: str = requirement
        self._staging_dir: Path = staging_dir
        self._output_dir: Path = output_dir
        self._preserve_partial: bool = preserve_partial
        self._start_time_utc: datetime = start_time_utc if start_time_utc is not None else datetime.now(timezone.utc)
        self._darpana: Darpana | None = darpana
        self._context: ExecutionContext | None = context

        self._committed_artifacts: list[ArtifactRef] = []
        self._committed_relative_paths: set[str] = set()
        self._staged_relative_paths: set[str] = set()
        self._partial_relative_paths: set[str] = set()
        self._partial_artifacts: list[Path] = []
        self._is_finalized: bool = False

        # Ensure staging and output directories exist
        try:
            self._staging_dir.mkdir(parents=True, exist_ok=True)
            self._output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to initialize run workspace directories.",
            ) from err

    @property
    def run_id(self) -> str:
        """Return the validated run identifier."""
        return self._run_id

    @property
    def requirement(self) -> str:
        """Return the validated requirement identifier."""
        return self._requirement

    @property
    def staging_dir(self) -> Path:
        """Return the staging directory path (Runtime/Work/<run-id>/)."""
        return self._staging_dir

    @property
    def output_dir(self) -> Path:
        """Return the run output directory path (Output/<requirement>/Run-<timestamp>-<short-id>/)."""
        return self._output_dir

    @property
    def preserve_partial(self) -> bool:
        """Return whether partial artifacts are preserved on incomplete runs."""
        return self._preserve_partial

    @property
    def committed_artifacts(self) -> tuple[ArtifactRef, ...]:
        """Return an immutable tuple of confirmed committed ArtifactRefs."""
        return tuple(self._committed_artifacts)

    @property
    def is_finalized(self) -> bool:
        """Return whether this run workspace has finalized."""
        return self._is_finalized

    def _resolve_relative_path(self, intent: ArtifactIntent) -> Path:
        """Resolve and return the validated relative destination path declared by an ArtifactIntent."""
        return resolve_relative_path(intent)

    def _normalize_path_key(self, rel_path: Path) -> str:
        """Normalize a relative path to standard forward-slash key for uniqueness checking."""
        return normalize_path_key(rel_path)

    def _write_bytes_atomically(self, target_path: Path, content: bytes | bytearray) -> None:
        """Write content bytes into target_path atomically using a temporary file in the same directory."""
        _write_bytes_atomically(target_path, content)

    def stage_artifact(self, intent: ArtifactIntent, content: bytes | bytearray) -> Path:
        """Stage an artifact byte payload under Runtime/Work/<run-id>/<relative_path>."""
        if not isinstance(intent, ArtifactIntent):
            raise TypeError(f"intent must be an ArtifactIntent instance, got {type(intent).__name__}.")
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError(f"content must be bytes or bytearray, got {type(content).__name__}.")

        if self._is_finalized:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Cannot stage artifact in a finalized run workspace.",
            )

        rel_path = self._resolve_relative_path(intent)
        path_key = self._normalize_path_key(rel_path)

        if path_key in self._staged_relative_paths:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Duplicate staged artifact destination path.",
            )

        dest_path = self._staging_dir / rel_path

        if not _is_path_relative_to(dest_path, self._staging_dir):
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="Staging path escapes staging root.",
            )

        _check_symlink_escape(dest_path, self._staging_dir)

        if dest_path.exists():
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Staged artifact destination already exists on disk.",
            )

        self._write_bytes_atomically(dest_path, bytes(content))
        self._staged_relative_paths.add(path_key)
        return dest_path

    def commit_staged_artifact(self, intent: ArtifactIntent, staged_path: Path) -> ArtifactRef:
        """Atomically commit an already staged artifact to the final run output directory by streaming."""
        ref, path_key = promote_staged_artifact(
            intent=intent,
            staged_path=staged_path,
            staging_dir=self._staging_dir,
            output_dir=self._output_dir,
            committed_relative_paths=self._committed_relative_paths,
            is_finalized=self._is_finalized,
            committed_artifacts=self._committed_artifacts,
            darpana=self._darpana,
            context=self._context,
        )
        self._committed_artifacts.append(ref)
        self._committed_relative_paths.add(path_key)
        return ref

    def commit_artifact(self, intent: ArtifactIntent, content: bytes | bytearray) -> ArtifactRef:
        """Directly commit an artifact byte payload to the final run output directory."""
        ref, path_key = promote_direct_artifact(
            intent=intent,
            content=content,
            output_dir=self._output_dir,
            committed_relative_paths=self._committed_relative_paths,
            is_finalized=self._is_finalized,
            write_bytes_fn=self._write_bytes_atomically,
        )
        self._committed_artifacts.append(ref)
        self._committed_relative_paths.add(path_key)
        return ref

    def preserve_partial_artifact(
        self,
        intent: ArtifactIntent,
        content: bytes | bytearray | Path,
    ) -> Path | None:
        """Preserve an incomplete/partial artifact under Output/.../partial/<relative_path>."""
        dest_path, path_key = preserve_partial_artifact_file(
            intent=intent,
            content=content,
            staging_dir=self._staging_dir,
            output_dir=self._output_dir,
            partial_relative_paths=self._partial_relative_paths,
            preserve_partial=self._preserve_partial,
            is_finalized=self._is_finalized,
            write_bytes_fn=self._write_bytes_atomically,
        )
        if dest_path is not None and path_key is not None:
            self._partial_artifacts.append(dest_path)
            self._partial_relative_paths.add(path_key)
        return dest_path

    def _cleanup_run_on_failure(self) -> None:
        """Clean up uncommitted staging data, committed artifacts, and non-preserved partial data upon run failure or unfinalized exit."""
        cleanup_workspace_on_failure(
            staging_dir=self._staging_dir,
            output_dir=self._output_dir,
            committed_artifacts=self._committed_artifacts,
            preserve_partial=self._preserve_partial,
            partial_artifacts=self._partial_artifacts,
        )
        self._staged_relative_paths.clear()
        self._committed_artifacts.clear()
        self._committed_relative_paths.clear()
        if not self._preserve_partial:
            self._partial_artifacts.clear()
            self._partial_relative_paths.clear()

    def finalize(
        self,
        *,
        success: bool = True,
        status: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        provenance: Sequence[ProvenanceRecord] | None = None,
        warnings: Sequence[WarningRecord] | None = None,
        context: ExecutionContext | None = None,
    ) -> Path:
        """Finalize the run workspace by writing run-manifest.json and cleaning staging data."""
        if self._is_finalized:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Run workspace is already finalized.",
            )

        effective_ctx = context or self._context
        scope = (
            self._darpana.time_scope(
                context=effective_ctx,
                phase_name="artifact_finalization",
                component="nabhi.artifacts",
                attributes={
                    "committed_count": len(self._committed_artifacts),
                    "success": success,
                },
            )
            if self._darpana is not None and effective_ctx is not None
            else nullcontext()
        )
        with scope:
            manifest_file = finalize_run_workspace(
                run_id=self._run_id,
                requirement=self._requirement,
                staging_dir=self._staging_dir,
                output_dir=self._output_dir,
                committed_artifacts=self._committed_artifacts,
                partial_artifacts=self._partial_artifacts,
                preserve_partial=self._preserve_partial,
                start_time_utc=self._start_time_utc,
                success=success,
                status=status,
                metadata=metadata,
                provenance=provenance,
                warnings=warnings,
                write_bytes_fn=self._write_bytes_atomically,
            )

            effective_status = (
                status if isinstance(status, str) and status.strip() else ("completed" if success else "failed")
            )
            if not success or effective_status in ("failed", "cancelled"):
                if not self._preserve_partial:
                    self._partial_artifacts.clear()
                    self._partial_relative_paths.clear()

            self._staged_relative_paths.clear()
            self._is_finalized = True
            return manifest_file

    def cleanup(self) -> None:
        """Clean up uncommitted staging data from the staging directory."""
        if self._staging_dir.exists():
            try:
                shutil.rmtree(self._staging_dir)
            except OSError as err:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Failed to clean up run staging directory.",
                ) from err

    def __enter__(self) -> RunWorkspace:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if exc_type is not None:
            if not self._is_finalized:
                try:
                    self._cleanup_run_on_failure()
                except (OSError, DoshError):
                    if self._darpana is not None and self._context is not None:
                        from sarathi.darpana import MarutiRecord

                        self._darpana.record_maruti(
                            MarutiRecord(
                                run_id=self._context.run_id,
                                request_id=self._context.request_id,
                                trace_id=self._context.trace_id,
                                span_id=self._context.span_id,
                                phase_name="artifact.cleanup_failure",
                                component="nabhi.artifacts",
                                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                                duration_ns=0,
                                outcome="failure",
                                attributes={"error": "cleanup_failed_during_exception"},
                            )
                        )
                    # Preserve original exception while attaching safe cleanup-failure note if supported
                    if exc_val is not None and hasattr(exc_val, "add_note"):
                        exc_val.add_note("Failed to clean up run workspace upon exception.")
        elif not self._is_finalized:
            self._cleanup_run_on_failure()
