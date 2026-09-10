"""Run Workspace Finalization and Failure Cleanup for Sarathi.

Provides atomic run manifest emission, in-memory pre-validation, staged directory
cleanup, and failure state purging.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.artifacts.atomic_io import _write_bytes_atomically
from sarathi.nabhi.artifacts.manifest import serialize_run_manifest
from sarathi.sankalpa import ArtifactRef, ProvenanceRecord, WarningRecord


def cleanup_workspace_on_failure(
    staging_dir: Path,
    output_dir: Path,
    committed_artifacts: list[ArtifactRef],
    preserve_partial: bool,
) -> None:
    """Clean up uncommitted staging data and non-preserved partial data upon failure.

    Committed artifacts are ALWAYS retained for recovery per Core Runtime requirements.
    """
    try:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        if not preserve_partial:
            partial_dir = output_dir / "partial"
            if partial_dir.exists():
                shutil.rmtree(partial_dir)

        if output_dir.exists():
            partial_dir = output_dir / "partial"
            has_partials = preserve_partial and partial_dir.exists() and any(partial_dir.iterdir())
            has_committed = any(art.path.exists() for art in committed_artifacts)
            if not has_partials and not has_committed:
                try:
                    if not any(output_dir.iterdir()):
                        shutil.rmtree(output_dir)
                except OSError:
                    pass
    except OSError as exc:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Failed to clean up unfinalized run workspace.",
        ) from exc


def finalize_run_workspace(
    run_id: str,
    requirement: str,
    staging_dir: Path,
    output_dir: Path,
    committed_artifacts: list[ArtifactRef],
    partial_artifacts: list[Path],
    preserve_partial: bool,
    start_time_utc: datetime,
    success: bool = True,
    status: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    provenance: Sequence[ProvenanceRecord] | None = None,
    warnings: Sequence[WarningRecord] | None = None,
    write_bytes_fn: Callable[[Path, bytes | bytearray], None] | None = None,
) -> Path:
    """Finalize run workspace by serializing run-manifest.json, cleaning staging data, and writing manifest atomically."""
    if not isinstance(success, bool):
        raise TypeError(f"success must be a bool, got {type(success).__name__}.")

    effective_status = (
        status if isinstance(status, str) and status.strip() else ("completed" if success else "failed")
    )

    if metadata is not None and not isinstance(metadata, Mapping):
        raise TypeError(f"metadata must be a Mapping or None, got {type(metadata).__name__}.")

    partial_manifest_entries: list[dict[str, Any]] = []
    if preserve_partial:
        for p in partial_artifacts:
            try:
                if p.exists():
                    partial_manifest_entries.append(
                        {
                            "relative_path": str(p.relative_to(output_dir)).replace("\\", "/"),
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
            run_id=run_id,
            requirement=requirement,
            effective_status=effective_status,
            start_time_utc=start_time_utc,
            committed_artifacts=committed_artifacts,
            partial_manifest_entries=partial_manifest_entries,
            output_dir=output_dir,
            provenance=provenance,
            warnings=warnings,
        )
    except DoshError as err:
        if err.code == FailureCode.EXECUTION_FAILED:
            cleanup_workspace_on_failure(staging_dir, output_dir, committed_artifacts, preserve_partial)
        raise

    try:
        if not success or effective_status in ("failed", "cancelled"):
            if not preserve_partial:
                partial_dir = output_dir / "partial"
                if partial_dir.exists():
                    shutil.rmtree(partial_dir)

        if staging_dir.exists():
            shutil.rmtree(staging_dir)
    except OSError as exc:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Failed to clean up staging or artifacts during finalization.",
        ) from exc

    manifest_file = output_dir / "run-manifest.json"
    writer = write_bytes_fn or _write_bytes_atomically
    try:
        writer(manifest_file, manifest_bytes)
    except DoshError:
        cleanup_workspace_on_failure(staging_dir, output_dir, committed_artifacts, preserve_partial)
        raise

    return manifest_file
