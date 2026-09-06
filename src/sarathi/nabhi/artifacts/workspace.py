"""Active run workspace providing staging, atomic commit, manifest generation, and cleanup."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.artifacts.atomic_io import _write_bytes_atomically
from sarathi.nabhi.artifacts.manifest import serialize_run_manifest
from sarathi.nabhi.artifacts.paths import (
    _CHUNK_SIZE,
    _check_symlink_escape,
    _is_path_relative_to,
)
from sarathi.sankalpa import ArtifactIntent, ArtifactRef, ExecutionContext, ProvenanceRecord, WarningRecord

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
        if not isinstance(intent, ArtifactIntent):
            raise TypeError(f"intent must be an ArtifactIntent instance, got {type(intent).__name__}.")
        if intent.relative_path is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="ArtifactIntent has no resolved relative path.",
            )
        return intent.relative_path

    def _normalize_path_key(self, rel_path: Path) -> str:
        """Normalize a relative path to standard forward-slash key for uniqueness checking."""
        return str(rel_path).replace("\\", "/")

    def _write_bytes_atomically(self, target_path: Path, content: bytes | bytearray) -> None:
        """Write content bytes into target_path atomically using a temporary file in the same directory."""
        _write_bytes_atomically(target_path, content)

    def stage_artifact(self, intent: ArtifactIntent, content: bytes | bytearray) -> Path:
        """Stage an artifact byte payload under Runtime/Work/<run-id>/<relative_path>.

        Args:
            intent: Declared artifact intent.
            content: Raw byte payload (bytes or bytearray).

        Returns:
            Path to the staged file.

        Raises:
            TypeError: If intent or content is not of expected type.
            DoshError(FailureCode.VALIDATION_FAILED): If workspace is finalized, duplicate destination, or exists.
            DoshError(FailureCode.SECURITY_DENIED): On traversal, escape, or symlink violations.
            DoshError(FailureCode.EXECUTION_FAILED): On write/filesystem failure.
        """
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
        """Atomically commit an already staged artifact to the final run output directory by streaming.

        Measures actual size and SHA-256 checksum during the stream, cleans up the staged file,
        and returns a confirmed ArtifactRef without loading the whole file into memory.

        Args:
            intent: Declared artifact intent.
            staged_path: Path to the staged file in Runtime/Work/<run-id>/.

        Returns:
            Confirmed ArtifactRef.

        Raises:
            TypeError: If intent or staged_path is not of expected type.
            DoshError(FailureCode.VALIDATION_FAILED): On duplicate destination or missing staged file.
            DoshError(FailureCode.SECURITY_DENIED): On traversal or root escape.
            DoshError(FailureCode.EXECUTION_FAILED): On I/O failure.
        """
        if not isinstance(intent, ArtifactIntent):
            raise TypeError(f"intent must be an ArtifactIntent instance, got {type(intent).__name__}.")

        if self._is_finalized:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Cannot commit artifact in a finalized run workspace.",
            )

        if not isinstance(staged_path, Path):
            if isinstance(staged_path, str):
                staged_path = Path(staged_path)
            else:
                raise TypeError(f"staged_path must be a Path or str, got {type(staged_path).__name__}.")

        if not staged_path.exists():
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Staged artifact file does not exist.",
            )

        if not _is_path_relative_to(staged_path, self._staging_dir):
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="staged_path is not within the active staging directory.",
            )

        rel_path = self._resolve_relative_path(intent)
        path_key = self._normalize_path_key(rel_path)

        if path_key in self._committed_relative_paths:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Duplicate artifact destination path.",
            )

        dest_path = self._output_dir / rel_path

        if not _is_path_relative_to(dest_path, self._output_dir):
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="Artifact destination path escapes output root.",
            )

        _check_symlink_escape(dest_path, self._output_dir)

        if dest_path.exists():
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Artifact destination already exists on disk.",
            )

        dest_dir = dest_path.parent
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to create artifact destination directory.",
            ) from err

        temp_file = dest_dir / f".tmp_{uuid.uuid4().hex}_{dest_path.name}"
        hasher = hashlib.sha256()
        total_bytes = 0

        scope = (
            self._darpana.time_scope(
                context=self._context,
                phase_name="artifact_commit",
                component="nabhi.artifacts",
                attributes={
                    "role": intent.role,
                    "media_type": intent.media_type,
                },
            )
            if self._darpana is not None and self._context is not None
            else nullcontext()
        )

        try:
            with scope:
                with staged_path.open("rb") as src, temp_file.open("wb") as dst:
                    while True:
                        chunk = src.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        dst.write(chunk)
                        hasher.update(chunk)
                        total_bytes += len(chunk)
                    dst.flush()
                    os.fsync(dst.fileno())
                temp_file.replace(dest_path)
        except OSError as err:
            if temp_file.exists():
                try:
                    temp_file.unlink(missing_ok=True)
                except OSError as cleanup_err:
                    dosh_err = DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message="Failed to atomically write artifact file and failed to clean up temporary file.",
                    )
                    dosh_err.__cause__ = err
                    dosh_err.__cleanup_cause__ = cleanup_err  # type: ignore[attr-defined]
                    raise dosh_err
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to atomically write artifact file.",
            ) from err

        # Promotion succeeded on disk: dest_path exists.
        artifact_id = f"art-{uuid.uuid4().hex[:12]}"
        ref = ArtifactRef(
            artifact_id=artifact_id,
            role=intent.role,
            media_type=intent.media_type,
            path=dest_path,
            size_bytes=total_bytes,
            checksum_sha256=hasher.hexdigest(),
            metadata=intent.metadata,
        )

        # Attempt staging cleanup
        try:
            staged_path.unlink(missing_ok=True)
        except OSError as unlink_err:
            # Staging cleanup failed. Attempt atomic rollback of dest_path.
            try:
                dest_path.unlink(missing_ok=True)
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Failed to clean up staged file; promoted artifact rolled back.",
                ) from unlink_err
            except OSError as rollback_err:
                # Rollback also failed: dest_path STILL exists on disk!
                # Track surviving promoted file in committed artifacts to ensure deterministic state
                self._committed_artifacts.append(ref)
                self._committed_relative_paths.add(path_key)
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Failed to clean up staged file and failed to roll back promoted artifact.",
                ) from rollback_err

        # Normal success path: dest_path promoted, staged_path unlinked
        self._committed_artifacts.append(ref)
        self._committed_relative_paths.add(path_key)
        return ref

    def commit_artifact(self, intent: ArtifactIntent, content: bytes | bytearray) -> ArtifactRef:
        """Directly commit an artifact byte payload to the final run output directory.

        Writes atomically through a temporary file in the destination filesystem,
        computes actual size and SHA-256 checksum from the exact byte payload,
        and immediately registers the confirmed ArtifactRef without a post-promotion stat window.

        Args:
            intent: Declared artifact intent.
            content: Raw byte payload (bytes or bytearray).

        Returns:
            Confirmed ArtifactRef.

        Raises:
            TypeError: If intent or content is not of expected type.
            DoshError(FailureCode.VALIDATION_FAILED): If already committed or destination exists.
            DoshError(FailureCode.SECURITY_DENIED): On traversal, root escape, or symlink violations.
            DoshError(FailureCode.EXECUTION_FAILED): On write/filesystem failure.
        """
        if not isinstance(intent, ArtifactIntent):
            raise TypeError(f"intent must be an ArtifactIntent instance, got {type(intent).__name__}.")
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError(f"content must be bytes or bytearray, got {type(content).__name__}.")

        if self._is_finalized:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Cannot commit artifact in a finalized run workspace.",
            )

        rel_path = self._resolve_relative_path(intent)
        path_key = self._normalize_path_key(rel_path)

        if path_key in self._committed_relative_paths:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Duplicate artifact destination path.",
            )

        dest_path = self._output_dir / rel_path

        if not _is_path_relative_to(dest_path, self._output_dir):
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="Artifact destination path escapes output root.",
            )

        _check_symlink_escape(dest_path, self._output_dir)

        if dest_path.exists():
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Artifact destination already exists on disk.",
            )

        byte_payload = bytes(content)
        actual_size = len(byte_payload)
        sha256_hash = hashlib.sha256(byte_payload).hexdigest()

        self._write_bytes_atomically(dest_path, byte_payload)

        artifact_id = f"art-{uuid.uuid4().hex[:12]}"
        ref = ArtifactRef(
            artifact_id=artifact_id,
            role=intent.role,
            media_type=intent.media_type,
            path=dest_path,
            size_bytes=actual_size,
            checksum_sha256=sha256_hash,
            metadata=intent.metadata,
        )

        self._committed_artifacts.append(ref)
        self._committed_relative_paths.add(path_key)
        return ref

    def preserve_partial_artifact(
        self,
        intent: ArtifactIntent,
        content: bytes | bytearray | Path,
    ) -> Path | None:
        """Preserve an incomplete/partial artifact under Output/.../partial/<relative_path>
        only when preserve_partial is True.

        When content is a Path, it must reside strictly within this run's staging directory.

        Args:
            intent: Declared artifact intent.
            content: Raw byte payload or path to a staged file.

        Returns:
            Path to the preserved partial artifact, or None if preserve_partial is False.

        Raises:
            TypeError: If intent or content is of invalid type.
            DoshError(FailureCode.VALIDATION_FAILED): If workspace is finalized, duplicate destination, or exists.
            DoshError(FailureCode.SECURITY_DENIED): On traversal, escape, symlink violations, or foreign source path.
            DoshError(FailureCode.EXECUTION_FAILED): On write/filesystem failure.
        """
        if not isinstance(intent, ArtifactIntent):
            raise TypeError(f"intent must be an ArtifactIntent instance, got {type(intent).__name__}.")

        if self._is_finalized:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Cannot preserve partial artifact in a finalized run workspace.",
            )

        if not self._preserve_partial:
            return None

        rel_path = self._resolve_relative_path(intent)
        path_key = self._normalize_path_key(rel_path)

        if path_key in self._partial_relative_paths:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Duplicate partial artifact destination path.",
            )

        partial_dir = self._output_dir / "partial"
        dest_path = partial_dir / rel_path

        if not _is_path_relative_to(dest_path, partial_dir):
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="Partial artifact path escapes partial root.",
            )

        _check_symlink_escape(dest_path, partial_dir)

        if dest_path.exists():
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Partial artifact destination already exists on disk.",
            )

        if isinstance(content, Path):
            try:
                real_staging = self._staging_dir.resolve()
                real_content = content.resolve()
                real_content.relative_to(real_staging)
            except (ValueError, OSError) as err:
                raise DoshError(
                    code=FailureCode.SECURITY_DENIED,
                    message="Partial artifact source path must reside strictly within this run's staging directory.",
                ) from err

            if not real_content.is_file():
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message="Source partial file is not a regular file.",
                )

            dest_dir = dest_path.parent
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
            except OSError as err:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Failed to create artifact destination directory.",
                ) from err

            temp_file = dest_dir / f".tmp_{uuid.uuid4().hex}_{dest_path.name}"
            try:
                with real_content.open("rb") as src, temp_file.open("wb") as dst:
                    while True:
                        chunk = src.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        dst.write(chunk)
                    dst.flush()
                    os.fsync(dst.fileno())
                temp_file.replace(dest_path)
            except OSError as err:
                if temp_file.exists():
                    try:
                        temp_file.unlink(missing_ok=True)
                    except OSError as cleanup_err:
                        dosh_err = DoshError(
                            code=FailureCode.EXECUTION_FAILED,
                            message="Failed to preserve partial artifact and failed to clean up temporary file.",
                        )
                        dosh_err.__cause__ = err
                        dosh_err.__cleanup_cause__ = cleanup_err  # type: ignore[attr-defined]
                        raise dosh_err
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Failed to atomically write artifact file.",
                ) from err
        elif isinstance(content, (bytes, bytearray)):
            self._write_bytes_atomically(dest_path, bytes(content))
        else:
            raise TypeError(f"content must be bytes, bytearray, or Path, got {type(content).__name__}.")

        self._partial_artifacts.append(dest_path)
        self._partial_relative_paths.add(path_key)
        return dest_path

    def _cleanup_run_on_failure(self) -> None:
        """Clean up uncommitted staging data, committed artifacts, and non-preserved partial data upon run failure or unfinalized exit."""
        try:
            # 1. Clean staging directory
            if self._staging_dir.exists():
                shutil.rmtree(self._staging_dir)
            self._staged_relative_paths.clear()

            # 2. Clean ordinary committed artifacts
            for art in self._committed_artifacts:
                if art.path.exists():
                    art.path.unlink(missing_ok=True)
            self._committed_artifacts.clear()
            self._committed_relative_paths.clear()

            # 3. Clean partial directory if not preserving partials
            if not self._preserve_partial:
                partial_dir = self._output_dir / "partial"
                if partial_dir.exists():
                    shutil.rmtree(partial_dir)
                self._partial_artifacts.clear()
                self._partial_relative_paths.clear()

            # 4. If output directory is empty (no preserved partials), remove it
            if self._output_dir.exists():
                partial_dir = self._output_dir / "partial"
                has_partials = self._preserve_partial and partial_dir.exists() and any(partial_dir.iterdir())
                if not has_partials:
                    shutil.rmtree(self._output_dir)
        except OSError as exc:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to clean up unfinalized run workspace.",
            ) from exc

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
            return self._finalize_internal(
                success=success,
                status=status,
                metadata=metadata,
                provenance=provenance,
                warnings=warnings,
            )

    def _finalize_internal(
        self,
        *,
        success: bool = True,
        status: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        provenance: Sequence[ProvenanceRecord] | None = None,
        warnings: Sequence[WarningRecord] | None = None,
    ) -> Path:
        """Finalize the run workspace by writing run-manifest.json and cleaning staging data.

        All validation and serialization happen in-memory BEFORE any state mutation or filesystem cleanup.

        Args:
            success: Whether the overall run completed successfully.
            status: Optional explicit status string ('completed', 'failed', 'cancelled').
            metadata: Optional caller metadata (ignored for privacy in Phase 1 manifest).
            provenance: Optional sequence of ProvenanceRecord objects.
            warnings: Optional sequence of WarningRecord objects.

        Returns:
            Path to the written run-manifest.json.

        Raises:
            DoshError(FailureCode.VALIDATION_FAILED): If already finalized or invalid record identifiers.
            DoshError(FailureCode.EXECUTION_FAILED): If manifest write, stat, or cleanup fails.
            TypeError: If input sequences contain invalid record types.
        """
        if not isinstance(success, bool):
            raise TypeError(f"success must be a bool, got {type(success).__name__}.")

        effective_status = (
            status if isinstance(status, str) and status.strip() else ("completed" if success else "failed")
        )

        if metadata is not None and not isinstance(metadata, Mapping):
            raise TypeError(f"metadata must be a Mapping or None, got {type(metadata).__name__}.")

        if self._is_finalized:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Run workspace is already finalized.",
            )

        partial_manifest_entries: list[dict[str, Any]] = []
        if self._preserve_partial:
            for p in self._partial_artifacts:
                try:
                    if p.exists():
                        partial_manifest_entries.append(
                            {
                                "relative_path": str(p.relative_to(self._output_dir)).replace("\\", "/"),
                                "size_bytes": p.stat().st_size,
                            }
                        )
                except OSError as err:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message="Failed to inspect partial artifact for manifest generation.",
                    ) from err

        try:
            manifest_bytes = serialize_run_manifest(
                run_id=self._run_id,
                requirement=self._requirement,
                effective_status=effective_status,
                start_time_utc=self._start_time_utc,
                committed_artifacts=self._committed_artifacts,
                partial_manifest_entries=partial_manifest_entries,
                output_dir=self._output_dir,
                provenance=provenance,
                warnings=warnings,
            )
        except DoshError as err:
            if err.code == FailureCode.EXECUTION_FAILED:
                self._cleanup_run_on_failure()
            raise

        # Only after all validation and serialization succeed do we perform final filesystem cleanup
        try:
            if not success or effective_status in ("failed", "cancelled"):
                # Clean up partial artifacts if not preserving partials
                if not self._preserve_partial:
                    partial_dir = self._output_dir / "partial"
                    if partial_dir.exists():
                        shutil.rmtree(partial_dir)
                    self._partial_artifacts.clear()
                    self._partial_relative_paths.clear()

            if self._staging_dir.exists():
                shutil.rmtree(self._staging_dir)
            self._staged_relative_paths.clear()
        except OSError as exc:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to clean up staging or artifacts during finalization.",
            ) from exc

        manifest_file = self._output_dir / "run-manifest.json"
        try:
            self._write_bytes_atomically(manifest_file, manifest_bytes)
        except DoshError:
            self._cleanup_run_on_failure()
            raise

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
