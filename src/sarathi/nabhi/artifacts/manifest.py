"""Run manifest schema validation and serialization for the artifact boundary."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.artifacts.paths import (
    _ISO_TIMESTAMP_PATTERN,
    _SAFE_DOTTED_PATTERN,
    _SAFE_IDENTIFIER_PATTERN,
)
from sarathi.sankalpa import ArtifactRef, ProvenanceRecord, WarningRecord


def serialize_run_manifest(
    run_id: str,
    requirement: str,
    effective_status: str,
    start_time_utc: datetime,
    committed_artifacts: Sequence[ArtifactRef],
    partial_manifest_entries: list[dict[str, Any]],
    output_dir: Path,
    provenance: Sequence[ProvenanceRecord] | None = None,
    warnings: Sequence[WarningRecord] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> bytes:
    """Validate and serialize the run manifest according to strict schema invariants.

    Returns encoded UTF-8 bytes ready for atomic write.
    """
    manifest_data: dict[str, Any] = {
        "run_id": run_id,
        "requirement": requirement,
        "status": effective_status,
        "created_at_utc": start_time_utc.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": [
            {
                "artifact_id": art.artifact_id,
                "role": art.role,
                "media_type": art.media_type,
                "relative_path": str(art.path.relative_to(output_dir)).replace("\\", "/"),
                "size_bytes": art.size_bytes,
                "checksum_sha256": art.checksum_sha256,
            }
            for art in committed_artifacts
        ],
        "partial_artifacts": partial_manifest_entries,
    }

    if metadata is not None:
        if not isinstance(metadata, Mapping):
            raise TypeError(f"metadata must be a Mapping or None, got {type(metadata).__name__}.")
        if "total_inputs" in metadata:
            try:
                manifest_data["total_inputs"] = int(metadata["total_inputs"])
            except (ValueError, TypeError):
                pass
        if "input_outcomes" in metadata and isinstance(metadata["input_outcomes"], Mapping):
            safe_outcomes = {}
            for k, v in metadata["input_outcomes"].items():
                if isinstance(k, str) and isinstance(v, str):
                    safe_outcomes[k] = v
            if safe_outcomes:
                manifest_data["input_outcomes"] = safe_outcomes

    # Safe provenance identity recording only (strictly validated against safe identifiers when present)
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

    try:
        return json.dumps(manifest_data, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as err:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Failed to serialize run manifest.",
        ) from err
