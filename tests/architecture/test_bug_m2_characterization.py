"""Characterization tests for M2 refactoring (pinning Result structure, helpers, and behavior)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.darpana import Darpana, MarutiRecord, record_maruti
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    ExecutionContext,
    InputRef,
    Request,
    Result,
    check_cancelled,
)


@pytest.mark.unit
def test_bug_m2_check_cancelled_helper():
    """Verify check_cancelled behaves uniformly across targets."""
    # 1. None target -> no error
    check_cancelled(None)

    # 2. Uncancelled token -> no error
    token = CancellationToken()
    check_cancelled(token)

    # 3. Cancelled token -> raises DoshError(OPERATION_CANCELLED)
    token.cancel()
    with pytest.raises(DoshError) as exc_info:
        check_cancelled(token)
    assert exc_info.value.code == FailureCode.OPERATION_CANCELLED

    # 4. Request with cancelled token
    inp = InputRef(
        input_id="in-1",
        source_path=Path("doc.pdf"),
        display_name="doc.pdf",
        size_bytes=100,
    )
    req = Request(
        request_id="r1",
        requirement="read_native",
        inputs=(inp,),
        cancellation_token=token,
    )
    with pytest.raises(DoshError) as exc_info2:
        check_cancelled(req)
    assert exc_info2.value.code == FailureCode.OPERATION_CANCELLED

    # 5. ExecutionContext with cancelled token
    ctx = ExecutionContext(
        run_id="run1",
        request_id="r1",
        trace_id="tr1",
        span_id="sp1",
        cancellation_token=token,
    )
    with pytest.raises(DoshError) as exc_info3:
        check_cancelled(ctx)
    assert exc_info3.value.code == FailureCode.OPERATION_CANCELLED


@pytest.mark.unit
def test_bug_m2_record_maruti_helper():
    """Verify record_maruti gracefully handles None and valid Darpana."""
    # 1. darpana is None -> returns None, no exception
    assert record_maruti(None, phase_name="test") is None

    # 2. with real darpana
    darpana = Darpana()
    ctx = ExecutionContext(run_id="run-1", request_id="req-1", trace_id="tr-1", span_id="sp-1")
    rec = record_maruti(
        darpana=darpana,
        context=ctx,
        phase_name="test_phase",
        component="test_comp",
        duration_ns=1000,
        outcome="success",
        attributes={"k": "v"},
    )
    assert isinstance(rec, MarutiRecord)
    assert rec.run_id == "run-1"
    assert rec.phase_name == "test_phase"
    assert rec.component == "test_comp"
    assert rec.attributes == {"k": "v"}
    assert len(darpana.maruti_records()) == 1


@pytest.mark.unit
def test_bug_m2_characterization_result_structure():
    """Pin the Result contract properties and behavior."""
    from sarathi.sankalpa import ConfidenceValue

    conf = ConfidenceValue(score=1.0, method="exact", evidence={"count": 1})
    res = Result(
        data=None,
        artifacts=(),
        confidence=conf,
        warnings=(),
        metadata={"run_id": "run-test", "request_id": "req-test"},
    )
    assert res.data is None
    assert res.artifacts == ()
    assert res.confidence == conf
    assert res.metadata["run_id"] == "run-test"
    assert res.metadata["request_id"] == "req-test"
