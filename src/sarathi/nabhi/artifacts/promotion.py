"""Artifact Promotion, Staging Commits, and Partial Preservation for Sarathi V2.

Provides atomic promotion of staged files, direct byte payload commits, rollback handling,
and partial artifact preservation under Output/.../partial/.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.artifacts.atomic_io import _write_bytes_atomically
from sarathi.nabhi.artifacts.paths import (
    _CHUNK_SIZE,
    _check_symlink_escape,
    _is_path_relative_to,
)
from sarathi.sankalpa import ArtifactIntent, ArtifactRef, ExecutionContext

if TYPE_CHECKING:
    from sarathi.darpana import Darpana


def resolve_relative_path(intent: ArtifactIntent) -> Path:
    """Resolve and return the validated relative destination path declared by an ArtifactIntent."""
    if not isinstance(intent, ArtifactIntent):
        raise TypeError(f"intent must be an ArtifactIntent instance, got {type(intent).__name__}.")
    if intent.relative_path is None:
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="ArtifactIntent has no resolved relative path.",
        )
    return intent.relative_path


def normalize_path_key(rel_path: Path) -> str:
    """Normalize a relative path to standard forward-slash key for uniqueness checking."""
    return str(rel_path).replace("\\", "/")


def promote_staged_artifact(
    intent: ArtifactIntent,
    staged_path: Path,
    staging_dir: Path,
    output_dir: Path,
    committed_relative_paths: set[str],
    is_finalized: bool,
    committed_artifacts: list[ArtifactRef] | None = None,
    darpana: Darpana | None = None,
    context: ExecutionContext | None = None,
) -> tuple[ArtifactRef, str]:
    """Atomically promote a staged artifact file to the final run output directory by streaming.

    Returns:
        (confirmed_ref, path_key)
    """
    if not isinstance(intent, ArtifactIntent):
        raise TypeError(f"intent must be an ArtifactIntent instance, got {type(intent).__name__}.")

    if is_finalized:
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

    if not _is_path_relative_to(staged_path, staging_dir):
        raise DoshError(
            code=FailureCode.SECURITY_DENIED,
            message="staged_path is not within the active staging directory.",
        )

    rel_path = resolve_relative_path(intent)
    path_key = normalize_path_key(rel_path)

    if path_key in committed_relative_paths:
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Duplicate artifact destination path.",
        )

    dest_path = output_dir / rel_path

    if not _is_path_relative_to(dest_path, output_dir):
        raise DoshError(
            code=FailureCode.SECURITY_DENIED,
            message="Artifact destination path escapes output root.",
        )

    _check_symlink_escape(dest_path, output_dir)

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
        darpana.time_scope(
            context=context,
            phase_name="artifact_commit",
            component="nabhi.artifacts",
            attributes={
                "role": intent.role,
                "media_type": intent.media_type,
            },
        )
        if darpana is not None and context is not None
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
            if committed_artifacts is not None:
                committed_artifacts.append(ref)
                committed_relative_paths.add(path_key)
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to clean up staged file and failed to roll back promoted artifact.",
            ) from rollback_err

    return ref, path_key


def promote_direct_artifact(
    intent: ArtifactIntent,
    content: bytes | bytearray,
    output_dir: Path,
    committed_relative_paths: set[str],
    is_finalized: bool,
    write_bytes_fn: Callable[[Path, bytes | bytearray], None] | None = None,
) -> tuple[ArtifactRef, str]:
    """Directly commit an artifact byte payload to the final run output directory.

    Returns:
        (confirmed_ref, path_key)
    """
    if not isinstance(intent, ArtifactIntent):
        raise TypeError(f"intent must be an ArtifactIntent instance, got {type(intent).__name__}.")
    if not isinstance(content, (bytes, bytearray)):
        raise TypeError(f"content must be bytes or bytearray, got {type(content).__name__}.")

    if is_finalized:
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Cannot commit artifact in a finalized run workspace.",
        )

    rel_path = resolve_relative_path(intent)
    path_key = normalize_path_key(rel_path)

    if path_key in committed_relative_paths:
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Duplicate artifact destination path.",
        )

    dest_path = output_dir / rel_path

    if not _is_path_relative_to(dest_path, output_dir):
        raise DoshError(
            code=FailureCode.SECURITY_DENIED,
            message="Artifact destination path escapes output root.",
        )

    _check_symlink_escape(dest_path, output_dir)

    if dest_path.exists():
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Artifact destination already exists on disk.",
        )

    byte_payload = bytes(content)
    actual_size = len(byte_payload)
    sha256_hash = hashlib.sha256(byte_payload).hexdigest()

    writer = write_bytes_fn or _write_bytes_atomically
    writer(dest_path, byte_payload)

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

    return ref, path_key


def preserve_partial_artifact_file(
    intent: ArtifactIntent,
    content: bytes | bytearray | Path,
    staging_dir: Path,
    output_dir: Path,
    partial_relative_paths: set[str],
    preserve_partial: bool,
    is_finalized: bool,
    write_bytes_fn: Callable[[Path, bytes | bytearray], None] | None = None,
) -> tuple[Path | None, str | None]:
    """Preserve an incomplete/partial artifact under Output/.../partial/<relative_path>.

    Returns:
        (dest_path, path_key) or (None, None) if preserve_partial is False.
    """
    if not isinstance(intent, ArtifactIntent):
        raise TypeError(f"intent must be an ArtifactIntent instance, got {type(intent).__name__}.")

    if is_finalized:
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Cannot preserve partial artifact in a finalized run workspace.",
        )

    if not preserve_partial:
        return None, None

    rel_path = resolve_relative_path(intent)
    path_key = normalize_path_key(rel_path)

    if path_key in partial_relative_paths:
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Duplicate partial artifact destination path.",
        )

    partial_dir = output_dir / "partial"
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
            real_staging = staging_dir.resolve()
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
        writer = write_bytes_fn or _write_bytes_atomically
        writer(dest_path, bytes(content))
    else:
        raise TypeError(f"content must be bytes, bytearray, or Path, got {type(content).__name__}.")

    return dest_path, path_key
