"""Canonical Artifact Boundary for Nabhi Kernel in Sarathi V2.

Defines:
- ArtifactBoundary: The single injected boundary for artifact lifecycle management.
- RunWorkspace: Per-run active workspace providing safe staging, atomic commits,
  manifest generation, and cleanup.

Owns:
- Root validation and separation of runtime and output directories.
- Staging directory under Runtime/Work/<run-id>/
- Output directory under Output/<requirement>/Run-<timestamp>-<short-id>/
- Atomic writes via unique temporary files in the destination filesystem.
- Measurement of actual size and SHA-256 checksums for ArtifactRef creation.
- Canonical run-manifest.json written last upon completion.
- Cleanup of staging files and explicit partial preservation under partial/.
- Input file safety: inputs are never modified, moved, deleted, or copied.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import TYPE_CHECKING, Any, Mapping, Sequence
import uuid

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import ArtifactIntent, ArtifactRef, InputRef, ProvenanceRecord, WarningRecord

if TYPE_CHECKING:
    from sarathi.kavacha import Kavacha

_REQUIREMENT_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_-]+$")
_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_SAFE_DOTTED_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)*$")
_ISO_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")
_CHUNK_SIZE = 65536


def _is_path_relative_to(path: Path, base: Path) -> bool:
    """Check if path is strictly located within or equal to base directory."""
    try:
        resolved_path = path.resolve()
        resolved_base = base.resolve()
        resolved_path.relative_to(resolved_base)
        return True
    except ValueError:
        return False
    except OSError as err:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Failed to inspect filesystem path containment.",
        ) from err


def _check_symlink_escape(target_path: Path, base_dir: Path) -> None:
    """Verify that neither target_path nor any of its ancestor directories up to base_dir

    symlink outside of base_dir.
    """
    try:
        resolved_base = base_dir.resolve()
    except OSError as err:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Filesystem access error inspecting boundary base directory.",
        ) from err

    current = target_path
    while True:
        try:
            if current.is_symlink():
                resolved_link = current.resolve()
                if not _is_path_relative_to(resolved_link, resolved_base):
                    raise DoshError(
                        code=FailureCode.SECURITY_DENIED,
                        message="Symlink escape detected: target path resolves outside boundary root.",
                    )
            resolved_current = current.resolve()
        except OSError as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Filesystem access error inspecting path.",
            ) from err

        if resolved_current == resolved_base or current == current.parent:
            break
        current = current.parent


def _validate_root_directory(
    root: Path | str,
    param_name: str,
) -> Path:
    """Validate that a root path argument is a valid non-empty path and can serve as a directory."""
    if isinstance(root, bool) or not isinstance(root, (str, Path)):
        raise TypeError(f"{param_name} must be a Path or str, got {type(root).__name__}.")

    raw_str = str(root).strip()
    if not raw_str:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"{param_name} cannot be an empty or whitespace path.",
        )

    try:
        resolved_path = Path(root).resolve()
    except OSError as err:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Failed to inspect {param_name} directory.",
        ) from err

    try:
        if resolved_path.exists() and not resolved_path.is_dir():
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"{param_name} exists but is not a directory.",
            )
    except OSError as err:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Failed to inspect {param_name} directory.",
        ) from err

    return resolved_path


def _validate_root_separation(runtime_root: Path, output_root: Path) -> None:
    """Ensure runtime_root and output_root are distinct and not nested within each other."""
    if runtime_root == output_root:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message="runtime_root and output_root cannot be the same directory.",
        )

    if _is_path_relative_to(output_root, runtime_root) or _is_path_relative_to(runtime_root, output_root):
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message="runtime_root and output_root cannot be nested within each other.",
        )


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
    ) -> None:
        self._run_id: str = run_id
        self._requirement: str = requirement
        self._staging_dir: Path = staging_dir
        self._output_dir: Path = output_dir
        self._preserve_partial: bool = preserve_partial
        self._start_time_utc: datetime = (
            start_time_utc if start_time_utc is not None else datetime.now(timezone.utc)
        )

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

    def _write_bytes_atomically(self, target_path: Path, content: bytes) -> None:
        """Write content bytes into target_path atomically using a temporary file in the same directory."""
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError(f"content must be bytes or bytearray, got {type(content).__name__}.")

        target_dir = target_path.parent
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to create artifact destination directory.",
            ) from err

        temp_file = target_dir / f".tmp_{uuid.uuid4().hex}_{target_path.name}"
        try:
            with temp_file.open("wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            temp_file.replace(target_path)
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

        try:
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
        """Clean up uncommitted staging data and non-preserved partial data upon run failure or unfinalized exit.

        Preserves already confirmed/committed artifacts on disk and keeps committed artifact state truthful.
        """
        try:
            # 1. Clean staging directory
            if self._staging_dir.exists():
                shutil.rmtree(self._staging_dir)
            self._staged_relative_paths.clear()

            # 2. Clean partial directory if not preserving partials
            if not self._preserve_partial:
                partial_dir = self._output_dir / "partial"
                if partial_dir.exists():
                    shutil.rmtree(partial_dir)
                self._partial_artifacts.clear()
                self._partial_relative_paths.clear()

            # 3. If output directory is empty (no committed artifacts and no preserved partials), remove it
            if self._output_dir.exists():
                try:
                    if not any(self._output_dir.iterdir()):
                        self._output_dir.rmdir()
                except OSError:
                    pass
        except OSError as exc:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to clean up unfinalized run workspace.",
            ) from exc

    def finalize(
        self,
        *,
        success: bool = True,
        metadata: Mapping[str, Any] | None = None,
        provenance: Sequence[ProvenanceRecord] | None = None,
        warnings: Sequence[WarningRecord] | None = None,
    ) -> Path:
        """Finalize the run workspace by writing run-manifest.json and cleaning staging data.

        All validation and serialization happen in-memory BEFORE any state mutation or filesystem cleanup.

        Args:
            success: Whether the overall run completed successfully.
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

        if metadata is not None and not isinstance(metadata, Mapping):
            raise TypeError(f"metadata must be a Mapping or None, got {type(metadata).__name__}.")

        if self._is_finalized:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Run workspace is already finalized.",
            )

        partial_manifest_entries: list[dict[str, Any]] = []
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

        manifest_data: dict[str, Any] = {
            "run_id": self._run_id,
            "requirement": self._requirement,
            "status": "completed" if success else "failed",
            "created_at_utc": self._start_time_utc.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "artifacts": [
                {
                    "artifact_id": art.artifact_id,
                    "role": art.role,
                    "media_type": art.media_type,
                    "relative_path": str(art.path.relative_to(self._output_dir)).replace("\\", "/"),
                    "size_bytes": art.size_bytes,
                    "checksum_sha256": art.checksum_sha256,
                }
                for art in self._committed_artifacts
            ],
            "partial_artifacts": partial_manifest_entries,
        }

        # Safe provenance identity recording only (strictly validated against safe identifiers when present)
        # MUST validate all inputs before any destructive filesystem mutation
        if provenance is not None:
            if not isinstance(provenance, (list, tuple)):
                raise TypeError(f"provenance must be a sequence of ProvenanceRecord, got {type(provenance).__name__}.")
            cleaned_prov: list[dict[str, Any]] = []
            for i, p in enumerate(provenance):
                if not isinstance(p, ProvenanceRecord):
                    raise TypeError(f"provenance[{i}] must be a ProvenanceRecord, got {type(p).__name__}.")
                prov_entry: dict[str, Any] = {}
                if p.stage is not None:
                    if not isinstance(p.stage, str) or not _SAFE_IDENTIFIER_PATTERN.match(p.stage):
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message="Provenance record contains invalid stage identifier.",
                        )
                    prov_entry["stage"] = p.stage
                if p.plugin_id is not None:
                    if not isinstance(p.plugin_id, str) or not _SAFE_DOTTED_PATTERN.match(p.plugin_id):
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message="Provenance record contains invalid plugin_id identifier.",
                        )
                    prov_entry["plugin_id"] = p.plugin_id
                if p.capability_id is not None:
                    if not isinstance(p.capability_id, str) or not _SAFE_DOTTED_PATTERN.match(p.capability_id):
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message="Provenance record contains invalid capability_id identifier.",
                        )
                    prov_entry["capability_id"] = p.capability_id
                if p.page_number is not None:
                    if isinstance(p.page_number, bool) or not isinstance(p.page_number, int) or p.page_number <= 0:
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message="Provenance record contains invalid page_number.",
                        )
                    prov_entry["page_number"] = p.page_number
                if p.region is not None:
                    if not isinstance(p.region, str) or not _SAFE_IDENTIFIER_PATTERN.match(p.region):
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message="Provenance record contains invalid region identifier.",
                        )
                    prov_entry["region"] = p.region
                if p.source_input_id is not None:
                    if not isinstance(p.source_input_id, str) or not _SAFE_IDENTIFIER_PATTERN.match(p.source_input_id):
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message="Provenance record contains invalid source_input_id identifier.",
                        )
                    prov_entry["source_input_id"] = p.source_input_id
                if p.timestamp_utc is not None:
                    if not isinstance(p.timestamp_utc, str) or not _ISO_TIMESTAMP_PATTERN.match(p.timestamp_utc):
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message="Provenance record contains invalid timestamp_utc format.",
                        )
                    prov_entry["timestamp_utc"] = p.timestamp_utc
                cleaned_prov.append(prov_entry)
            manifest_data["provenance"] = cleaned_prov

        # Safe warning code/stage recording only (strictly validated against safe identifiers when present)
        # MUST validate all inputs before any destructive filesystem mutation
        if warnings is not None:
            if not isinstance(warnings, (list, tuple)):
                raise TypeError(f"warnings must be a sequence of WarningRecord, got {type(warnings).__name__}.")
            cleaned_warn: list[dict[str, Any]] = []
            for i, w in enumerate(warnings):
                if not isinstance(w, WarningRecord):
                    raise TypeError(f"warnings[{i}] must be a WarningRecord, got {type(w).__name__}.")
                if not isinstance(w.code, str) or not _SAFE_IDENTIFIER_PATTERN.match(w.code):
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message="Warning record contains invalid warning code.",
                    )
                warn_entry: dict[str, Any] = {"code": w.code}
                if w.stage is not None:
                    if not isinstance(w.stage, str) or not _SAFE_IDENTIFIER_PATTERN.match(w.stage):
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message="Warning record contains invalid warning stage.",
                        )
                    warn_entry["stage"] = w.stage
                cleaned_warn.append(warn_entry)
            manifest_data["warnings"] = cleaned_warn

        # Validate JSON serialization safety before attempting any state mutation or file write
        try:
            manifest_bytes = json.dumps(manifest_data, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as err:
            self._cleanup_run_on_failure()
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to serialize run manifest.",
            ) from err

        # Only after all validation and serialization succeed do we perform final filesystem cleanup
        try:
            if self._staging_dir.exists():
                shutil.rmtree(self._staging_dir)
            self._staged_relative_paths.clear()

            if not success and not self._preserve_partial:
                partial_dir = self._output_dir / "partial"
                if partial_dir.exists():
                    shutil.rmtree(partial_dir)
                self._partial_artifacts.clear()
                self._partial_relative_paths.clear()
        except OSError as exc:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to clean up staging directory during finalization.",
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
                    # Preserve original exception while attaching safe cleanup-failure note/state
                    if exc_val is not None:
                        if hasattr(exc_val, "add_note"):
                            exc_val.add_note("Failed to clean up run workspace upon exception.")
                        try:
                            exc_val.__cleanup_failed__ = True
                        except (AttributeError, TypeError):
                            pass
        elif not self._is_finalized:
            self._cleanup_run_on_failure()


class ArtifactBoundary:
    """Canonical Artifact Boundary for Sarathi V2.

    Single global boundary responsible for staging, atomic commits, run manifests,
    and storage root lifecycle.
    """

    def __init__(
        self,
        runtime_root: Path | str,
        output_root: Path | str,
        *,
        kavacha: Kavacha | None = None,
    ) -> None:
        """Construct an ArtifactBoundary with explicit runtime and output roots.

        Args:
            runtime_root: Explicit path to the runtime storage directory.
            output_root: Explicit path to the output storage directory.
            kavacha: Optional injected Kavacha security service.

        Raises:
            TypeError: If roots are not Path or str, or if kavacha is not a Kavacha instance.
            DoshError(FailureCode.INVALID_CONFIGURATION): On empty paths, non-directory paths,
                equal roots, or nested roots.
        """
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

    @property
    def runtime_root(self) -> Path:
        """Return the active runtime root directory."""
        return self._runtime_root

    @property
    def output_root(self) -> Path:
        """Return the active output root directory."""
        return self._output_root

    def begin_run(
        self,
        run_id: str,
        requirement: str,
        *,
        output_root: Path | str | None = None,
        preserve_partial: bool = False,
        timestamp: datetime | None = None,
        input_sources: Sequence[Path | str | InputRef] = (),
    ) -> RunWorkspace:
        """Begin a run workspace for safe staging and atomic artifact commits.

        Args:
            run_id: Safe non-empty run identifier (e.g. 'run-1', 'run-001').
            requirement: Safe stable requirement identifier (e.g. 'ocr', 'bank_statements').
            output_root: Optional per-run output root override.
            preserve_partial: Whether incomplete artifacts should be retained under partial/.
            timestamp: Optional UTC timestamp override (used for deterministic run folder naming).
            input_sources: Optional input sources to validate against storage directory overlap.

        Returns:
            An active RunWorkspace.

        Raises:
            TypeError: If arguments are of invalid types.
            DoshError(FailureCode.VALIDATION_FAILED): If run_id or requirement is malformed.
            DoshError(FailureCode.INVALID_CONFIGURATION): If output_root override is invalid or nested,
                or if input_sources are supplied without an injected Kavacha security service.
            DoshError(FailureCode.SECURITY_DENIED): If input sources overlap with staging or output roots.
        """
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
            raise TypeError(f"input_sources must be a sequence of Path, str, or InputRef, got {type(input_sources).__name__}.")

        for i, src in enumerate(input_sources):
            if not isinstance(src, (Path, str, InputRef)):
                raise TypeError(
                    f"input_sources[{i}] must be a Path, str, or InputRef, got {type(src).__name__}."
                )

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
        )
