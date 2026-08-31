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
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


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
        if self.relative_path is not None and not isinstance(self.relative_path, Path):
            object.__setattr__(self, "relative_path", Path(self.relative_path))
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
