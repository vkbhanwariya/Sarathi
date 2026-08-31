"""Artifact and Input Contracts for Sarathi V2.

Defines:
- InputRef: typed reference to an input source with measured facts.
- ArtifactIntent: capability intent to produce an artifact.
- ArtifactRef: confirmed reference to an existing committed artifact.

Contains contracts only: performs absolutely no filesystem I/O, path creation,
staging, commit, or artifact management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Mapping


def _validate_safe_relative_path(path: Path | str) -> Path:
    """Validate that path is genuinely relative, non-empty, and free of traversal under both Windows and POSIX rules."""
    raw_str = str(path).strip()
    if not raw_str:
        raise ValueError("relative_path cannot be empty.")

    win_path = PureWindowsPath(raw_str)
    posix_path = PurePosixPath(raw_str)

    # Reject Windows drive letters, roots, and absolute paths
    if win_path.is_absolute() or win_path.drive or win_path.root:
        raise ValueError(f"relative_path must be genuinely relative, got absolute or rooted path: {path!r}")

    # Reject POSIX roots and absolute paths
    if posix_path.is_absolute() or posix_path.root:
        raise ValueError(f"relative_path must be genuinely relative, got absolute or rooted path: {path!r}")

    # Reject leading slashes/backslashes or drive letters
    if raw_str.startswith("/") or raw_str.startswith("\\"):
        raise ValueError(f"relative_path must be genuinely relative, got rooted path: {path!r}")

    if len(raw_str) >= 2 and raw_str[1] == ":" and raw_str[0].isalpha():
        raise ValueError(f"relative_path cannot contain a drive specifier: {path!r}")

    # Normalized split check for directory traversal '..' across both slash styles
    normalized_slash = raw_str.replace("\\", "/")
    parts = [p for p in normalized_slash.split("/") if p != ""]

    if not parts or all(p == "." for p in parts):
        raise ValueError(f"relative_path cannot be empty or dot: {path!r}")

    if ".." in parts:
        raise ValueError(f"relative_path cannot contain '..' directory traversal parts: {path!r}")

    for p in parts:
        if p in (".", "..") or not p.strip():
            raise ValueError(f"relative_path contains invalid path component: {p!r}")

    return Path(path)


@dataclass(frozen=True, slots=True)
class InputRef:
    """Normalized typed reference to an input document or file."""

    input_id: str
    source_path: Path
    display_name: str
    size_bytes: int
    media_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.input_id or not self.input_id.strip():
            raise ValueError("input_id must be a non-empty string.")
        if not isinstance(self.source_path, Path):
            object.__setattr__(self, "source_path", Path(self.source_path))
        if not self.display_name or not self.display_name.strip():
            raise ValueError("display_name must be a non-empty string.")
        if self.size_bytes < 0:
            raise ValueError(f"size_bytes cannot be negative (got {self.size_bytes}).")
        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")


@dataclass(frozen=True, slots=True)
class ArtifactIntent:
    """Declared intent from a capability to produce a specific artifact."""

    name: str
    role: str
    media_type: str
    relative_path: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("name must be a non-empty string.")
        if not self.role or not self.role.strip():
            raise ValueError("role must be a non-empty string.")
        if not self.media_type or not self.media_type.strip():
            raise ValueError("media_type must be a non-empty string.")
        if self.relative_path is not None:
            if not isinstance(self.relative_path, (Path, str)):
                raise TypeError(f"relative_path must be a Path or str, got {type(self.relative_path)}.")
            object.__setattr__(self, "relative_path", _validate_safe_relative_path(self.relative_path))
        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Confirmed reference to an existing, committed output artifact."""

    artifact_id: str
    role: str
    media_type: str
    path: Path
    size_bytes: int
    checksum_sha256: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.artifact_id.strip():
            raise ValueError("artifact_id must be a non-empty string.")
        if not self.role or not self.role.strip():
            raise ValueError("role must be a non-empty string.")
        if not self.media_type or not self.media_type.strip():
            raise ValueError("media_type must be a non-empty string.")
        if not isinstance(self.path, Path):
            object.__setattr__(self, "path", Path(self.path))
        if self.size_bytes < 0:
            raise ValueError(f"size_bytes cannot be negative (got {self.size_bytes}).")
        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")
