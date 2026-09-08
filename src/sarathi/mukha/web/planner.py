"""Mukha Execution Plan Previewer for Sarathi V2.

Queries Agni, Darshana, Manthan, and Yantra to compute preflight execution
plans, stage breakdowns, and hardware device allocations without executing pipelines.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from sarathi.dosh import DoshError
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

        req_metadata = {}
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

        # Collect planned stages
        stages: list[dict[str, str]] = [
            {"stage_id": "intake", "name": "Input Ingestion & Validation (Kavacha)"},
            {"stage_id": "identification", "name": "MIME & Structure Identification (Darshana)"},
            {"stage_id": "routing", "name": "Capability Plan Resolution (Manthan)"},
        ]
        for cid in plan.capability_ids:
            cap = agni.kosh.get_capability(cid)
            cname = cap.name if cap and hasattr(cap, "name") else cid
            stages.append({"stage_id": cid, "name": f"Execution: {cname} (Yantra)"})
        has_smriti = bool(hasattr(agni, "smriti") and agni.smriti is not None)
        artifact_stage_name = (
            "Artifact Commitment & Smriti Persistence"
            if has_smriti
            else "Artifact Commitment"
        )
        stages.append({"stage_id": "artifacts", "name": artifact_stage_name})

        # Collect hardware device inventory
        devices: list[dict[str, Any]] = []
        if hasattr(agni, "yantra") and agni.yantra is not None:
            inv = None
            if hasattr(agni.yantra, "device_inventory") and hasattr(agni.yantra.device_inventory, "devices") and isinstance(agni.yantra.device_inventory.devices, list):
                inv = agni.yantra.device_inventory
            elif hasattr(agni.yantra, "inventory"):
                inv = agni.yantra.inventory
            if inv is not None and hasattr(inv, "devices"):
                for d in inv.devices:
                    dev_type_val = d.device_type.value if hasattr(d.device_type, "value") else str(d.device_type)
                    devices.append(
                        {
                            "device_type": str(dev_type_val),
                            "device_id": str(d.device_id),
                            "capacity": d.capacity,
                            "memory_bytes": d.memory_bytes,
                            "supported_backends": list(d.supported_backends or ()),
                            "is_available": d.capacity > 0,
                        }
                    )

        return {
            "ok": True,
            "requirement": requirement,
            "profile": profile.value,
            "document_count": len(inputs),
            "capabilities": list(plan.capability_ids),
            "stages": stages,
            "devices": devices,
        }
    except (DoshError, Exception) as exc:
        return {
            "ok": False,
            "error": _format_public_error(exc),
        }
