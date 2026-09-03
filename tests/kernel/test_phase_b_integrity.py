"""Tests for Phase B remediation: Translation equivalence, Bank table-scoping, Agni plugin validation, and data root portability."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from sarathi.agni import Agni
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
    CapabilityDeclaration,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    Request,
    Result,
    TableData,
)
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.models import BankStatement, Transaction
from sarathi.shakti.translation.capability import TranslationCapability
from sarathi.sutra.settings import get_canonical_data_root


def test_translation_artifact_matches_canonical_doc_exactly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify Translation produces byte-for-byte identical text in doc.text and Translated_Document.txt artifact."""
    from sarathi.shakti.translation.models import Language, TranslationDirection, TranslationResult

    class MockTranslationEngine:
        def __init__(self) -> None:
            self.call_count = 0

        def translate(self, text: str, direction: TranslationDirection) -> TranslationResult:
            self.call_count += 1
            return TranslationResult(
                translated_text=f"Translated: {text}",
                source_language=Language.HINDI,
                target_language=Language.ENGLISH,
                direction=direction,
                protected_spans_count=0,
                metadata={},
            )

    cap = TranslationCapability()
    cap._engine = MockTranslationEngine()  # inject mock engine

    doc = CanonicalDocument(
        document_id="doc-tr-1",
        text="यह एक परीक्षण दस्तावेज़ है।",
        pages=(
            PageData(
                page_number=1,
                text="यह एक परीक्षण दस्तावेज़ है।",
            ),
        ),
    )
    prior = Result(data=doc)
    ctx = ExecutionContext("run-1", "req-1", "t-1", "s-1")
    inp = InputRef(input_id="inp-1", source_path=tmp_path / "sample.txt", display_name="sample.txt", size_bytes=10)
    req = Request(request_id="req-1", requirement="translation", inputs=(inp,))

    result = cap.execute(req, ctx, prior_result=prior)

    assert result.data is not None
    assert isinstance(result.data, CanonicalDocument)
    canonical_text = result.data.text

    # Verify TXT artifact content
    txt_payload = next(p for p in result.artifact_payloads if p.intent.name.endswith(".txt"))
    assert txt_payload.content.decode("utf-8") == canonical_text

    # Verify that identical doc.text was not translated repeatedly (memoization worked)
    assert cap._engine.call_count == 1


def test_bank_statement_continuation_row_strictly_table_scoped() -> None:
    """Verify continuation row in Table 2 does not leak onto preceding transaction of Table 1."""
    from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult

    cap = BankStatementCapability()

    # Create document with two separate tables
    # Table 1: Date | Description | Debit | Credit | Balance
    # Row 1: 01/01/2026 | Txn Table 1 | 1000.00 | | 5000.00
    # Table 2:
    # Row 1 (Continuation): Continued orphan text from table 2 | | | |
    # Row 2: 02/01/2026 | Txn Table 2 | | 2000.00 | 7000.00
    t1 = TableData(
        headers=("Date", "Description", "Debit", "Credit", "Balance"),
        rows=(("01/01/2026", "Txn Table 1", "1000.00", "", "5000.00"),),
    )
    t2 = TableData(
        headers=("Date", "Description", "Debit", "Credit", "Balance"),
        rows=(
            ("Continued orphan text from table 2", "", "", "", ""),
            ("02/01/2026", "Txn Table 2", "", "2000.00", "7000.00"),
        ),
    )

    doc = CanonicalDocument(
        document_id="doc-bank-multi-tbl",
        text="State Bank of India Statement",
        tables=(t1, t2),
    )
    prior = Result(data=doc)
    ctx = ExecutionContext("run-1", "req-1", "t-1", "s-1")
    inp = InputRef(input_id="inp-1", source_path=Path("bank.pdf"), display_name="bank.pdf", size_bytes=10)
    req = Request(request_id="req-1", requirement="bank_statements", inputs=(inp,))

    result = cap.execute(req, ctx, prior_result=prior)

    assert result.data is not None
    assert isinstance(result.data, BankStatementConsolidationResult)
    consolidation: BankStatementConsolidationResult = result.data
    assert len(consolidation.statements) == 1
    stmt = consolidation.statements[0]
    assert len(stmt.transactions) == 2

    # Txn 1 from Table 1 must NOT have Table 2's continuation text attached
    assert stmt.transactions[0].description == "Txn Table 1"
    assert "Continued orphan text" not in stmt.transactions[0].description

    # An explicit warning issue should be recorded for the orphan continuation row
    orphan_issues = [i for i in stmt.issues if i.code == "ORPHAN_CONTINUATION_ROW"]
    assert len(orphan_issues) >= 1


def test_agni_rejects_custom_capability_without_registered_plugin() -> None:
    """Verify Agni does not invent synthetic PluginInfo and rejects unowned capabilities with VALIDATION_FAILED."""
    class FakeCustomCapability:
        @property
        def declaration(self) -> CapabilityDeclaration:
            return CapabilityDeclaration(
                capability_id="unregistered_cap",
                plugin_id="unknown.plugin",
                version="1.0.0",
                supported_profiles=(ExecutionProfile.INSTANT,),
            )

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            return Result(data="fake")

    fake_cap = FakeCustomCapability()

    with pytest.raises(DoshError) as exc_info:
        Agni(capabilities={"unregistered_cap": fake_cap})

    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "unknown.plugin" in str(exc_info.value.message)
    assert "owning plugin 'unknown.plugin' is not registered in Kosh" in str(exc_info.value.message)


def test_get_canonical_data_root_respects_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify get_canonical_data_root resolves custom directory when SARATHI_DATA_DIR is set."""
    custom_data = tmp_path / "custom_data_dir"
    custom_data.mkdir()

    monkeypatch.setenv("SARATHI_DATA_DIR", str(custom_data))
    assert get_canonical_data_root() == custom_data.resolve()

    monkeypatch.delenv("SARATHI_DATA_DIR", raising=False)
    # Default should resolve to repository or packaged data directory
    default_root = get_canonical_data_root()
    assert default_root.name == "data"
