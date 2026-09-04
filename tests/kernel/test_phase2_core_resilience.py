"""Comprehensive unit and regression tests for Phase 2 Core State, Lifecycle & Cache fixes.

Verifies:
- Finding 3: Central warning accumulation across pipeline stages
- Finding 4: Mixed-batch OCR handoff for Font, Translation, and Bank
- Finding 27: Cache key completeness (bounding boxes, layout, metadata, structured objects)
- Finding 28: Auxiliary cache put failure records Darpana warning without breaking execution
- Finding 29: Agni restart prevention after close (INVALID_STATE)
- Finding 30: Singular lifecycle teardown via Prana for unstarted components
- Finding 31: Dvara preflight rejection of capability without owning plugin
- Finding 32: Mukha dynamic capability readiness inspection
- Finding 33: Yantra secondary error note sanitization
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.darpana import Darpana, MarutiRecord
from sarathi.nabhi import Dvara, Kosh, Prana
from sarathi.sankalpa import (
    CapabilityDeclaration,
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    PluginInfo,
    Request,
    Result,
    SecurityDeclaration,
    TableData,
    TextSpan,
    WarningRecord,
)
from sarathi.smriti import compute_cache_key, compute_prior_result_digest
from sarathi.shakti.font_conversion.capability import FontConversionCapability
from sarathi.shakti.translation.capability import TranslationCapability
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.yantra import Yantra, DeviceInventory


def test_cache_key_includes_bounding_box() -> None:
    """Finding 27: Two documents with same text but different bounding boxes must produce different cache keys."""
    req = Request(
        request_id="req-1",
        requirement="ocr",
        inputs=(InputRef("i1", Path("doc.pdf"), "doc.pdf", 100),),
    )

    span1 = TextSpan(text="Sarathi", confidence=0.99, bounding_box=(0.0, 0.0, 10.0, 10.0))
    span2 = TextSpan(text="Sarathi", confidence=0.99, bounding_box=(50.0, 50.0, 60.0, 60.0))

    page1 = PageData(page_number=1, text="Sarathi", spans=(span1,))
    page2 = PageData(page_number=1, text="Sarathi", spans=(span2,))

    doc1 = CanonicalDocument(document_id="d1", source_input_id="i1", text="Sarathi", pages=(page1,))
    doc2 = CanonicalDocument(document_id="d1", source_input_id="i1", text="Sarathi", pages=(page2,))

    key1 = compute_cache_key(req, "ocr", prior_result=Result(data=doc1))
    key2 = compute_cache_key(req, "ocr", prior_result=Result(data=doc2))

    assert key1.key_hash != key2.key_hash


def test_cache_key_prior_result_digest_dataclass() -> None:
    """Finding 27: Non-CanonicalDocument dataclass prior results must hash structured attributes, not type name."""
    @dataclass
    class CustomFinancialSummary:
        total_amount: Decimal
        account_id: str

    res_a = Result(data=CustomFinancialSummary(Decimal("1000.00"), "ACC1"))
    res_b = Result(data=CustomFinancialSummary(Decimal("9999.00"), "ACC1"))

    digest_a = compute_prior_result_digest(res_a)
    digest_b = compute_prior_result_digest(res_b)

    assert digest_a != digest_b


def test_mixed_batch_ocr_handoff_font_and_translation() -> None:
    """Finding 4: When a batch has one document with text and one empty document, OCR handoff must trigger."""
    doc_with_text = CanonicalDocument(document_id="d1", source_input_id="i1", text="Already extracted text")
    doc_empty = CanonicalDocument(
        document_id="d2",
        source_input_id="i2",
        text="",
        pages=(PageData(page_number=1, text=""),),
    )

    req = Request(
        request_id="req-batch",
        requirement="font_conversion",
        inputs=(
            InputRef("i1", Path("d1.txt"), "d1.txt", 10),
            InputRef("i2", Path("d2.pdf"), "d2.pdf", 20),
        ),
    )
    ctx = ExecutionContext("run-1", "req-batch", "t1", "s1")

    # Font conversion capability: item-scoped escalation (Directive 26: populated docs converted, empty doc records warning)
    font_cap = FontConversionCapability()
    res_font = font_cap.execute(req, ctx, prior_result=Result(data=(doc_with_text, doc_empty)))
    assert res_font.next_requirement is None
    assert any(w.code == "EMPTY_DOCUMENT_SKIPPED" for w in res_font.warnings)

    # Translation capability
    trans_cap = TranslationCapability()
    res_trans = trans_cap.execute(req, ctx, prior_result=Result(data=(doc_with_text, doc_empty)))
    assert res_trans.next_requirement == "ocr"
    assert res_trans.resume_self is True

    # Bank statement capability
    bank_cap = BankStatementCapability()
    res_bank = bank_cap.execute(req, ctx, prior_result=Result(data=(doc_with_text, doc_empty)))
    assert res_bank.next_requirement == "ocr"
    assert res_bank.resume_self is True


def test_agni_forbids_restart_after_close(tmp_path: Path) -> None:
    """Finding 29: Agni instance cannot report fake restart after close()."""
    from sarathi.agni import Agni

    agni = Agni(runtime_root=tmp_path / "runtime", output_root=tmp_path / "output")
    agni.start()
    assert agni.is_started is True
    agni.close()
    assert agni.is_started is False

    with pytest.raises(DoshError) as exc_info:
        agni.start()
    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "cannot be restarted after close" in exc_info.value.message


def test_agni_singular_lifecycle_ownership(tmp_path: Path) -> None:
    """Finding 30: Agni routes all shutdown exclusively through Prana without bypassing."""
    from sarathi.agni import Agni

    class TrackingDarpana(Darpana):
        def __init__(self) -> None:
            super().__init__()
            self.start_called = False
            self.close_called = False

        def start(self) -> None:
            self.start_called = True

        def close(self) -> None:
            super().close()
            self.close_called = True

    mock_darpana = TrackingDarpana()

    agni = Agni(
        runtime_root=tmp_path / "runtime",
        output_root=tmp_path / "output",
        darpana=mock_darpana,
    )
    # When started, Prana starts darpana
    agni.start()
    assert mock_darpana.start_called is True

    # When closed, Prana closes darpana
    agni.close()
    assert mock_darpana.close_called is True
    assert agni.is_closed is True


def test_dvara_rejects_capability_without_registered_plugin() -> None:
    """Finding 31: Dvara must not synthesize synthetic plugins; owning plugin must be registered."""
    kosh = Kosh()
    dvara = Dvara(kosh)

    orphan_cap = CapabilityDeclaration(
        capability_id="orphan_cap",
        plugin_id="unregistered_plugin",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.CUSTOM,),
    )

    with pytest.raises(DoshError) as exc_info:
        dvara.register_capability(orphan_cap)
    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "must be registered before capability" in exc_info.value.message


def test_mukha_dynamic_capability_readiness(tmp_path: Path) -> None:
    """Finding 32: MukhaPresenter dynamically queries actual bank profiles and mapping packs."""
    data_dir = tmp_path / "data"
    banks_dir = data_dir / "banks"
    banks_dir.mkdir(parents=True)
    # Write a test bank profile
    (banks_dir / "icici.yaml").write_text("profile_id: icici\nbank_name: ICICI Bank\nkeywords: [icici]\n", encoding="utf-8")

    fonts_dir = data_dir / "fonts"
    fonts_dir.mkdir(parents=True)
    (fonts_dir / "krutidev010.json").write_text("{}", encoding="utf-8")

    statuses = MukhaPresenter.audit_capability_status(data_root=data_dir)
    assert "bank_statements" in statuses
    is_ready, desc = statuses["bank_statements"]
    assert is_ready is True
    assert "ICICI" in desc

    assert "font_conversion" in statuses
    font_ready, font_desc = statuses["font_conversion"]
    assert font_ready is True
    assert "krutidev010" in font_desc


def test_yantra_exception_note_sanitization() -> None:
    """Finding 33: Secondary release errors must be sanitized to type name only."""
    inv = DeviceInventory.default_inventory()
    yantra = Yantra(inv)

    class MockFailingCapability:
        @property
        def declaration(self) -> CapabilityDeclaration:
            return CapabilityDeclaration(
                capability_id="test_cap",
                plugin_id="test_plugin",
                version="1.0.0",
                supported_profiles=(ExecutionProfile.CUSTOM,),
            )

        def execute(
            self,
            request: Request,
            context: ExecutionContext,
            prior_result: Result | None = None,
        ) -> Result:
            raise RuntimeError("Primary failure in capability")

    failing_cap = MockFailingCapability()
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1")
    req = Request("req-1", "test_cap", (InputRef("i1", Path("test.txt"), "test.txt", 10),))

    # Mock release to raise a secondary exception with sensitive details
    yantra.release = MagicMock(side_effect=ValueError("Sensitive database path /secret/db.sqlite"))

    with pytest.raises(RuntimeError) as exc_info:
        yantra.execute(failing_cap, req, ctx)

    notes = getattr(exc_info.value, "__notes__", [])
    assert len(notes) == 1
    # Must contain type name ValueError, but NOT the sensitive text
    assert "ValueError" in notes[0]
    assert "/secret/db.sqlite" not in notes[0]


def test_pipeline_multi_stage_warning_accumulation(tmp_path: Path) -> None:
    """Finding 3: Pravaha centrally accumulates warnings across continuation and resumption stages."""
    from sarathi.nabhi import CapabilityPlan, Manthan, Pravaha, QuarantineStore, RetryPolicy
    from sarathi.sankalpa import Capability, DeviceRequirement, DeviceType

    plugin = PluginInfo(
        plugin_id="p1",
        name="P1",
        version="1.0.0",
        security=SecurityDeclaration(),
        capabilities=("stage_a", "stage_b"),
    )
    decl_a = CapabilityDeclaration("stage_a", "p1", "1.0.0", (ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE))
    decl_b = CapabilityDeclaration("stage_b", "p1", "1.0.0", (ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE))

    kosh = Kosh()
    kosh.register_plugin(plugin)
    kosh.register_capability(decl_a)
    kosh.register_capability(decl_b)

    manthan = Manthan(kosh)
    yantra = Yantra(DeviceInventory.default_inventory())
    qstore = QuarantineStore(tmp_path / "quarantine")

    class StageA(Capability):
        def __init__(self) -> None:
            self.executions = 0

        @property
        def declaration(self) -> CapabilityDeclaration:
            return decl_a

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            self.executions += 1
            if self.executions == 1:
                # Stage 1: detects issue, emits warning, requests stage_b with resume_self
                return Result(
                    data="data_a",
                    next_requirement="stage_b",
                    resume_self=True,
                    warnings=(WarningRecord("WARN_A", "Stage A warning", stage="stage_a"),),
                )
            # Resumed execution
            return Result(data=f"{prior_result.data if prior_result else ''}+resumed_a")

    class StageB(Capability):
        @property
        def declaration(self) -> CapabilityDeclaration:
            return decl_b

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            # Stage B returns without warnings
            return Result(data=f"{prior_result.data if prior_result else ''}+stage_b")

    caps = {"stage_a": StageA(), "stage_b": StageB()}
    pravaha = Pravaha(
        manthan=manthan,
        yantra=yantra,
        capabilities=caps,
        quarantine_store=qstore,
        retry_policy=RetryPolicy(),
    )

    req = Request("req-flow", "stage_a", (InputRef("i1", Path("f.txt"), "f.txt", 10),))
    ctx = ExecutionContext("run-1", "req-flow", "t1", "s1")
    plan = CapabilityPlan("req-flow", ("stage_a",))

    res = pravaha.execute(plan, req, ctx)
    # The warning from stage A must be centrally preserved in the final Result!
    assert any(w.code == "WARN_A" for w in res.warnings)
    assert res.data == "data_a+stage_b+resumed_a"


def test_smriti_cache_put_failure_records_darpana_telemetry(tmp_path: Path) -> None:
    """Finding 28: Smriti cache write failure emits telemetry without failing the execution."""
    from sarathi.darpana import Darpana
    from sarathi.nabhi import CapabilityPlan, Manthan, Pravaha, QuarantineStore, RetryPolicy
    from sarathi.smriti import SmritiCache

    plugin = PluginInfo(
        plugin_id="p_cache",
        name="PCache",
        version="1.0.0",
        security=SecurityDeclaration(),
        capabilities=("calc_stage",),
    )
    decl = CapabilityDeclaration("calc_stage", "p_cache", "1.0.0", (ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE))

    kosh = Kosh()
    kosh.register_plugin(plugin)
    kosh.register_capability(decl)

    manthan = Manthan(kosh)
    yantra = Yantra(DeviceInventory.default_inventory())
    qstore = QuarantineStore(tmp_path / "quarantine")
    darpana = Darpana()

    mock_smriti = MagicMock(spec=SmritiCache)
    mock_smriti.get_with_tier.return_value = (None, None)
    mock_smriti.put.side_effect = RuntimeError("Disk full writing cache")

    class CalcCap:
        @property
        def declaration(self) -> CapabilityDeclaration:
            return decl

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            return Result(data="calc_success")

    pravaha = Pravaha(
        manthan=manthan,
        yantra=yantra,
        capabilities={"calc_stage": CalcCap()},
        quarantine_store=qstore,
        retry_policy=RetryPolicy(),
        darpana=darpana,
        smriti=mock_smriti,
    )

    req = Request("req-cache", "calc_stage", (InputRef("i1", Path("f.txt"), "f.txt", 10),))
    ctx = ExecutionContext("run-1", "req-cache", "t1", "s1")
    plan = CapabilityPlan("req-cache", ("calc_stage",))

    # Must succeed despite cache.put raising RuntimeError
    res = pravaha.execute(plan, req, ctx)
    assert res.data == "calc_success"

    # Telemetry must record cache.write_failure
    records = darpana.maruti_records()
    write_failures = [r for r in records if r.phase_name == "cache.write_failure"]
    assert len(write_failures) >= 1
    assert write_failures[0].outcome == "failure"
    assert write_failures[0].attributes.get("error_type") == "RuntimeError"
