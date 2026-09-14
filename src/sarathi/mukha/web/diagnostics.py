"""Privacy-safe Mukha run diagnostics export for Sarathi."""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sarathi.darpana.pramana import select_aggregate_confidence_records
from sarathi.mukha.web.security import _sanitize_message
from sarathi.mukha.web.state_builder import get_run_telemetry

if TYPE_CHECKING:
    from sarathi.agni import Agni

_SAFE_EVENT_ATTRIBUTES = frozenset(
    {
        "attempt",
        "attempt_count",
        "cache_tier",
        "cancelled",
        "capability_id",
        "chars",
        "committed_count",
        "device_type",
        "error_type",
        "fallback_applied",
        "fallback_engine",
        "fallback_improved_count",
        "fallback_intercepted_count",
        "input_count",
        "lifecycle_status",
        "max_retries",
        "outcome",
        "page",
        "page_number",
        "pages_processed",
        "plugin_id",
        "requirement",
        "success",
        "worker_id",
    }
)


def export_run_diagnostics(
    agni: Agni,
    run_id: str,
    host: str = "127.0.0.1",
    port: int = 0,
) -> dict[str, Any]:
    """Generate a sanitized diagnostics report bundle for troubleshooting."""
    maruti_recs, pramana_recs = get_run_telemetry(agni, run_id)

    system_facts = {
        "python_version": sys.version.split()[0],
        "os_platform": platform.platform(),
        "processor": platform.processor() or "Unknown",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "port": port,
        "security_policy": "Kavacha Local Isolation",
    }

    devices = [
        {
            "device_type": device.device_type.value,
            "device_id": device.device_id,
            "is_available": device.capacity > 0,
            "is_preferred": False,
        }
        for device in agni.yantra.inventory.devices
    ]

    stage_durations: dict[str, dict[str, Any]] = {}
    activity_events: list[dict[str, Any]] = []

    for record in maruti_recs:
        phase_name = record.phase_name or "unknown_phase"
        duration_ns = max(0, int(record.duration_ns or 0))
        if phase_name not in stage_durations:
            stage_durations[phase_name] = {"calls": 0, "total_duration_ns": 0}
        stage_durations[phase_name]["calls"] += 1
        stage_durations[phase_name]["total_duration_ns"] += duration_ns

        sanitized_attributes = {
            key: _sanitize_message(str(value))
            for key, value in (record.attributes or {}).items()
            if key in _SAFE_EVENT_ATTRIBUTES
        }
        device_type = str((record.attributes or {}).get("device_type", "cpu"))
        activity_events.append(
            {
                "timestamp_utc": record.timestamp_utc,
                "phase": phase_name,
                "component": record.component,
                "duration_ms": round(duration_ns / 1_000_000, 2),
                "device_type": device_type,
                "attributes": sanitized_attributes,
            }
        )

    aggregate_pramana = select_aggregate_confidence_records(pramana_recs)
    confidences = [record.confidence.score for record in aggregate_pramana if record.confidence is not None]
    confidence_statistics: dict[str, Any] = {
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
        "confidence_statistics": confidence_statistics,
        "event_count": len(activity_events),
        "events": activity_events[:200],
    }
