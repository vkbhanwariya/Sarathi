"""Mukha Run Diagnostics Exporter for Sarathi V2.

Generates sanitized, privacy-safe diagnostics bundles for execution runs,
capturing platform facts, hardware devices, stage timing distributions,
and error records without leaking raw document text or filesystem roots.
"""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sarathi.mukha.web.security import _sanitize_message
from sarathi.mukha.web.state_builder import get_run_telemetry

if TYPE_CHECKING:
    from sarathi.agni import Agni


def export_run_diagnostics(
    agni: Agni,
    run_id: str,
    host: str = "127.0.0.1",
    port: int = 0,
) -> dict[str, Any]:
    """Generate a sanitized diagnostics report bundle for troubleshooting."""
    maruti_recs, pramana_recs = get_run_telemetry(agni, run_id)

    # 1. System environment facts
    system_facts = {
        "python_version": sys.version.split()[0],
        "os_platform": platform.platform(),
        "processor": platform.processor() or "Unknown",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "port": port,
        "security_policy": "Kavacha Local Isolation",
    }

    # 2. Hardware device inventory
    devices: list[dict[str, Any]] = []
    if hasattr(agni, "yantra") and agni.yantra is not None:
        inv = getattr(agni.yantra, "device_inventory", None)
        if inv is not None and hasattr(inv, "devices"):
            for d in inv.devices:
                devices.append(
                    {
                        "device_type": str(d.device_type),
                        "device_id": str(d.device_id),
                        "is_available": bool(getattr(d, "is_available", True)),
                        "is_preferred": bool(getattr(d, "is_preferred", False)),
                    }
                )

    # 3. Stage timing and performance summary (Sanitized)
    stage_durations: dict[str, dict[str, Any]] = {}
    activity_events: list[dict[str, Any]] = []

    for m in maruti_recs:
        p_name = m.phase_name or "unknown_phase"
        dur_ns = max(0, int(m.duration_ns or 0))
        if p_name not in stage_durations:
            stage_durations[p_name] = {"calls": 0, "total_duration_ns": 0}
        stage_durations[p_name]["calls"] += 1
        stage_durations[p_name]["total_duration_ns"] += dur_ns

        # Privacy-safe activity log
        attr_sanitized = {
            k: _sanitize_message(str(v))
            for k, v in (m.attributes or {}).items()
            if k not in ("text", "content", "raw_path", "source_text")
        }
        dev = str((m.attributes or {}).get("device_type", "cpu")) if m.attributes else "cpu"
        activity_events.append(
            {
                "timestamp_utc": m.timestamp_utc,
                "phase": p_name,
                "component": m.component,
                "duration_ms": round(dur_ns / 1_000_000, 2),
                "device_type": dev,
                "attributes": attr_sanitized,
            }
        )

    # 4. Confidence statistics (Sanitized, no text)
    confidences = [
        float(p.confidence.score if hasattr(p.confidence, "score") else p.confidence)
        for p in pramana_recs
        if p.confidence is not None
    ]
    conf_stats: dict[str, Any] = {
        "sample_count": len(confidences),
        "min_confidence": min(confidences) if confidences else None,
        "max_confidence": max(confidences) if confidences else None,
        "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
    }

    return {
        "schema": "sarathi.diagnostics.v1",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "system": system_facts,
        "hardware_devices": devices,
        "stages": stage_durations,
        "confidence_statistics": conf_stats,
        "event_count": len(activity_events),
        "events": activity_events[:200],
    }
