"""Canonical Artifact Boundary for Nabhi Kernel in Sarathi.

Defines:
- ArtifactBoundary: The single injected boundary for artifact lifecycle management.
- RunWorkspace: Per-run active workspace providing safe staging, atomic commits,
  manifest generation, and cleanup.
"""

from __future__ import annotations

from sarathi.nabhi.artifacts.atomic_io import _compute_sha256, _write_bytes_atomically
from sarathi.nabhi.artifacts.boundary import ArtifactBoundary
from sarathi.nabhi.artifacts.manifest import serialize_run_manifest
from sarathi.nabhi.artifacts.paths import (
    _CHUNK_SIZE,
    _ISO_TIMESTAMP_PATTERN,
    _REQUIREMENT_IDENTIFIER_PATTERN,
    _RUN_ID_PATTERN,
    _SAFE_DOTTED_PATTERN,
    _SAFE_IDENTIFIER_PATTERN,
    _check_symlink_escape,
    _is_path_relative_to,
    _validate_root_directory,
    _validate_root_separation,
)
from sarathi.nabhi.artifacts.workspace import RunWorkspace

__all__ = [
    "ArtifactBoundary",
    "RunWorkspace",
    "_CHUNK_SIZE",
    "_ISO_TIMESTAMP_PATTERN",
    "_REQUIREMENT_IDENTIFIER_PATTERN",
    "_RUN_ID_PATTERN",
    "_SAFE_DOTTED_PATTERN",
    "_SAFE_IDENTIFIER_PATTERN",
    "_check_symlink_escape",
    "_compute_sha256",
    "_is_path_relative_to",
    "_validate_root_directory",
    "_validate_root_separation",
    "_write_bytes_atomically",
    "serialize_run_manifest",
]
