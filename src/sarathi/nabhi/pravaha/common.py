"""Shared hashing, authorization, and telemetry observation helpers for Pravaha."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sarathi.nabhi.kosh import Kosh
from sarathi.sankalpa import Capability, ExecutionContext, Request, Result
from sarathi.smriti import compute_input_fingerprint

if TYPE_CHECKING:
    from sarathi.darpana import Darpana
    from sarathi.kavacha import Kavacha

_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def authorize_capability(kavacha: Kavacha | None, registry: Kosh, cap: Capability) -> None:
    """Authorize capability's owning plugin security declaration via Kavacha if configured."""
    if kavacha is not None:
        plugin = registry.get_plugin(cap.declaration.plugin_id)
        if plugin is not None:
            kavacha.authorize(plugin.security)


def compute_input_hash(request: Request, capability: Capability, context: ExecutionContext) -> str:
    """Compute a deterministic, privacy-safe hash identifying the canonical execution attempt.

    Reuses the canonical input fingerprint from Smriti combined with execution scope.
    """
    fingerprint = compute_input_fingerprint(request.inputs)
    clean_options = (
        {k: v for k, v in request.custom_options.items() if not callable(v) and k != "progress_callback"}
        if request.custom_options
        else {}
    )
    options_str = json.dumps(clean_options, sort_keys=True, default=str) if clean_options else ""
    content = (
        f"{context.run_id}:{request.request_id}:{capability.declaration.capability_id}:"
        f"{context.profile.value}:{options_str}:{fingerprint}"
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def record_pramana_if_available(
    darpana: Darpana | None,
    capability: Capability,
    result: Result,
    context: ExecutionContext,
) -> None:
    """Record quality observation to Darpana Pramana telemetry if evidence-backed facts exist."""
    if darpana is None:
        return

    from sarathi.darpana import AccuracyValue, PramanaRecord

    accuracy_val = (
        result.metadata.get("accuracy") if isinstance(result.metadata.get("accuracy"), AccuracyValue) else None
    )

    if result.confidence is not None or accuracy_val is not None:
        pramana_rec = PramanaRecord(
            run_id=context.run_id,
            request_id=context.request_id,
            trace_id=context.trace_id,
            span_id=context.span_id,
            capability_id=capability.declaration.capability_id,
            stage=capability.declaration.capability_id,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            confidence=result.confidence,
            accuracy=accuracy_val,
            attributes={
                "plugin_id": capability.declaration.plugin_id,
                "profile": context.profile.value,
                **(
                    {"device_type": context.execution_binding.device_type.value}
                    if context.execution_binding is not None
                    else {}
                ),
            },
        )
        darpana.record_pramana(pramana_rec)


def quarantine_transition_scope(
    darpana: Darpana | None,
    context: ExecutionContext | None,
    capability_id: str,
    lifecycle_status: str,
    attempt_count: int,
    max_retries: int,
):
    """Timing scope for actual quarantine lifecycle state transitions."""
    if darpana is not None and context is not None:
        return darpana.time_scope(
            context=context,
            phase_name="quarantine_lifecycle",
            component="nabhi.pravaha",
            attributes={
                "capability_id": capability_id,
                "lifecycle_status": lifecycle_status,
                "attempt_count": attempt_count,
                "max_retries": max_retries,
            },
        )
    return nullcontext()
