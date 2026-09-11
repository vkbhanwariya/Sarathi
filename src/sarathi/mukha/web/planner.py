"""Mukha execution-plan preview for Sarathi."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.web.security import _format_public_error
from sarathi.sankalpa import CancellationToken, ExecutionProfile, Request

if TYPE_CHECKING:
    from sarathi.agni import Agni


def preview_execution_plan(
    agni: Agni,
    paths: list[Path],
    requirement: str = "read_native",
    profile: ExecutionProfile = ExecutionProfile.INSTANT,
    recursive: bool = True,
    custom_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preview capability resolution, stage sequence, and hardware devices for requested execution."""
    try:
        inputs, _, _ = MukhaPresenter.intake_from_paths(
            paths,
            kavacha=agni.kavacha,
            runtime_root=agni.runtime_root,
            output_root=agni.output_root,
            recursive=recursive,
        )
        if not inputs:
            return {
                "ok": False,
                "error": "No eligible input documents discovered.",
            }

        req_metadata: dict[str, Any] = {}
        if custom_options and custom_options.get("direction"):
            req_metadata["direction"] = custom_options["direction"]

        req = Request(
            request_id=f"preview-{uuid.uuid4().hex[:8]}",
            requirement=requirement,
            inputs=inputs,
            profile=profile,
            cancellation_token=CancellationToken(),
            custom_options=dict(custom_options or {}),
            metadata=req_metadata,
        )

        plan = agni.manthan.resolve(req)

        stages: list[dict[str, str]] = [
            {"stage_id": "intake", "name": "Input Ingestion & Validation (Kavacha)"},
            {"stage_id": "identification", "name": "MIME & Structure Identification (Darshana)"},
            {"stage_id": "routing", "name": "Capability Plan Resolution (Manthan)"},
        ]
        for capability_id in plan.capability_ids:
            capability = agni.kosh.get_capability(capability_id)
            display_name = getattr(capability, "display_name", None)
            name = getattr(capability, "name", None)
            if isinstance(display_name, str) and display_name.strip():
                capability_name = display_name.strip()
            elif isinstance(name, str) and name.strip():
                capability_name = name.strip()
            else:
                capability_name = capability_id
            stages.append({"stage_id": capability_id, "name": f"Execution: {capability_name} (Yantra)"})

        artifact_stage_name = (
            "Artifact Commitment & Smriti Persistence"
            if agni.smriti is not None
            else "Artifact Commitment"
        )
        stages.append({"stage_id": "artifacts", "name": artifact_stage_name})

        devices = [
            {
                "device_type": device.device_type.value,
                "device_id": device.device_id,
                "capacity": device.capacity,
                "memory_bytes": device.memory_bytes,
                "supported_backends": list(device.supported_backends or ()),
                "is_available": device.capacity > 0,
            }
            for device in agni.yantra.inventory.devices
        ]

        return {
            "ok": True,
            "requirement": requirement,
            "profile": profile.value,
            "document_count": len(inputs),
            "capabilities": list(plan.capability_ids),
            "stages": stages,
            "devices": devices,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": _format_public_error(exc),
        }
