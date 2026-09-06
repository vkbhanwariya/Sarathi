"""Atomic file writing and streaming cryptographic hashing for artifacts."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.artifacts.paths import _CHUNK_SIZE


def _compute_sha256(file_path: Path) -> str:
    """Compute and return the hex-encoded SHA-256 checksum of file_path using streaming chunks."""
    h = hashlib.sha256()
    try:
        with file_path.open("rb") as f:
            while chunk := f.read(_CHUNK_SIZE):
                h.update(chunk)
    except OSError as err:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Failed to compute checksum for artifact.",
        ) from err
    return h.hexdigest().lower()


def _write_bytes_atomically(target_path: Path, content: bytes | bytearray) -> None:
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
