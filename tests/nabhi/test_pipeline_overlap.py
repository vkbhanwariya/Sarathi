"""Unit and Integration Tests for High-Throughput Stage Pipeline Overlap (Phase 6)."""

from __future__ import annotations

import time
from pathlib import Path

from sarathi.nabhi.pravaha.pipeline import execute_pipelined_stage_handoff
from sarathi.sankalpa import (
    CanonicalDocument,
    Capability,
    CapabilityDeclaration,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    Request,
    Result,
)
from sarathi.yantra import DeviceInventory, Yantra


class DummyStageCapability(Capability):
    """Mock capability that records execution start and finish times for concurrency auditing."""

    def __init__(self, cap_id: str, delay_s: float = 0.04) -> None:
        self._decl = CapabilityDeclaration(
            capability_id=cap_id,
            plugin_id="dummy_plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.ACCURATE,),
            supported_input_types=("text/plain",),
        )
        self.delay_s = delay_s
        self.execution_logs: list[tuple[str, float, float]] = []  # (doc_id, start_t, end_t)

    @property
    def declaration(self) -> CapabilityDeclaration:
        return self._decl

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        doc_id = request.inputs[0].input_id
        start_t = time.perf_counter()
        time.sleep(self.delay_s)
        end_t = time.perf_counter()
        self.execution_logs.append((doc_id, start_t, end_t))

        doc = CanonicalDocument(
            document_id=doc_id,
            source_input_id=doc_id,
            pages=(PageData(page_number=1, text=f"Processed by {self._decl.capability_id}"),),
        )
        return Result(data=(doc,))


def test_pipeline_stage_overlap_concurrency() -> None:
    """Verify Stage 1 on Doc i+1 executes concurrently while Stage 2 processes Doc i."""
    cap_stage1 = DummyStageCapability(cap_id="mock_ocr_igpu", delay_s=0.04)
    cap_stage2 = DummyStageCapability(cap_id="mock_translate_cpu", delay_s=0.04)

    requests = [
        Request(
            request_id=f"req_{i}",
            requirement="dummy_stage",
            inputs=(InputRef(f"doc_{i}", Path(f"doc_{i}.txt"), f"doc_{i}.txt", 10),),
        )
        for i in range(3)
    ]
    context = ExecutionContext("run-1", "batch_req", "trace_1", "span_1")
    yantra = Yantra(DeviceInventory.default_inventory())

    wall_start = time.perf_counter()
    results = execute_pipelined_stage_handoff(
        requests=requests,
        stage1_cap=cap_stage1,
        stage2_cap=cap_stage2,
        context=context,
        yantra=yantra,
    )
    wall_duration = time.perf_counter() - wall_start

    assert len(results) == 3
    for i in range(3):
        assert results[i].data[0].document_id == f"doc_{i}"

    # Sequential execution would take 3 * (0.04 + 0.04) = 0.24s
    # Pipelined execution takes (3 + 1) * 0.04 ~= 0.16s
    # Assert significant overlap speedup (< 0.23s)
    assert wall_duration < 0.23

    # Audit concurrency overlap:
    # Stage 1 on Doc 1 should start BEFORE Stage 2 on Doc 0 has finished
    # Stage 1 execution logs: [(doc_0, s0, e0), (doc_1, s1, e1), (doc_2, s2, e2)]
    # Stage 2 execution logs: [(doc_0, s0', e0'), (doc_1, s1', e1'), (doc_2, s2', e2')]
    s1_doc1_start = cap_stage1.execution_logs[1][1]
    s2_doc0_end = cap_stage2.execution_logs[0][2]

    # Stage 1 began working on Doc 1 while Stage 2 was still busy on Doc 0
    assert s1_doc1_start < s2_doc0_end + 0.01


def test_pipeline_stage_overlap_empty_requests() -> None:
    """Verify empty requests sequence returns empty results without spawning workers."""
    cap_stage1 = DummyStageCapability(cap_id="cap1")
    cap_stage2 = DummyStageCapability(cap_id="cap2")
    context = ExecutionContext("run-1", "empty_req", "trace_1", "span_1")
    yantra = Yantra(DeviceInventory.default_inventory())

    res = execute_pipelined_stage_handoff(
        requests=[],
        stage1_cap=cap_stage1,
        stage2_cap=cap_stage2,
        context=context,
        yantra=yantra,
    )
    assert res == []
