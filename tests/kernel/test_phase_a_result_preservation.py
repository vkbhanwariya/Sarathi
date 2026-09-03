"""Tests for Phase A remediation: Pravaha Result field preservation across warning sync."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.pravaha import Pravaha
from sarathi.sankalpa import (
    ArtifactPayload,
    ArtifactRef,
    Capability,
    CapabilityDeclaration,
    ConfidenceValue,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    ProvenanceRecord,
    Request,
    Result,
    WarningRecord,
)


class MockWarningEmittingCapability:
    """Mock capability that emits warnings alongside confidence, artifacts, and metadata."""

    @property
    def declaration(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            capability_id="mock_cap",
            plugin_id="shakti.mock",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )

    def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
        return Result(
            data="output_data_content",
            confidence=ConfidenceValue(score=0.92, method="test_eval", evidence={"sample_count": 100}),
            artifacts=(
                ArtifactRef(
                    artifact_id="art-1",
                    role="primary",
                    media_type="text/plain",
                    path=Path("output/test.txt"),
                    size_bytes=42,
                ),
            ),
            warnings=(
                WarningRecord(
                    code="TEST_WARNING",
                    message="A non-fatal test warning occurred.",
                    stage="mock_cap",
                ),
            ),
            metadata={"source_encoding": "utf-8", "custom_flag": True},
            provenance=(
                ProvenanceRecord(
                    stage="mock_cap",
                    plugin_id="shakti.mock",
                    capability_id="mock_cap",
                    evidence={"test": 1},
                ),
            ),
        )


def test_pravaha_preserves_all_result_fields_during_warning_sync() -> None:
    """Verify Pravaha pipeline preserves confidence, artifacts, and metadata when warnings are synchronized."""
    from sarathi.nabhi.kosh import Kosh
    from sarathi.nabhi.manthan import CapabilityPlan, Manthan
    from sarathi.sankalpa import PluginInfo

    kosh = Kosh()
    mock_cap = MockWarningEmittingCapability()

    kosh.register_plugin(
        PluginInfo(
            plugin_id="shakti.mock",
            name="Mock Plugin",
            version="1.0.0",
            capabilities=("mock_cap",),
        )
    )
    kosh.register_capability(mock_cap.declaration)

    from sarathi.sankalpa.capability import DeviceType
    from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra

    inv = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4)])
    yantra = Yantra(inv)
    manthan = Manthan(registry=kosh)
    capabilities_map = {"mock_cap": mock_cap}

    pravaha = Pravaha(
        manthan=manthan,
        yantra=yantra,
        capabilities=capabilities_map,
        quarantine_store=None,
    )

    plan = CapabilityPlan(
        request_id="req-1",
        capability_ids=("mock_cap",),
    )

    inp = InputRef(input_id="inp-1", source_path=Path("sample.txt"), display_name="sample.txt", size_bytes=10)
    req = Request(request_id="req-1", requirement="mock_req", inputs=(inp,))
    ctx = ExecutionContext("run-1", "req-1", "t-1", "s-1")

    res = pravaha.execute(plan, req, ctx)

    assert res is not None
    assert res.data == "output_data_content"

    # CRITICAL: Verify fields that were previously destroyed by _sync_warnings
    assert res.confidence is not None
    assert res.confidence.score == 0.92
    assert res.confidence.method == "test_eval"

    assert len(res.artifacts) == 1
    assert res.artifacts[0].artifact_id == "art-1"

    assert res.metadata.get("source_encoding") == "utf-8"
    assert res.metadata.get("custom_flag") is True

    # Warnings and provenance preserved
    assert len(res.warnings) == 1
    assert res.warnings[0].code == "TEST_WARNING"
    assert len(res.provenance) == 1
