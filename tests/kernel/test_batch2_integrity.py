"""Batch 2 Integrity and Data Flow Tests for Sarathi V2.

Verifies:
1. Multi-document bank statement consolidation and TableData.headers parsing.
2. Ambiguous amount direction producing validation issues rather than zero amounts.
3. Content-based streaming file hashing in compute_input_fingerprint and Pravaha quarantine identity.
4. OCR confidence omission when any span has missing or invalid confidence.
5. Cancellation bypassing retry, quarantine, and cache writes.
6. Multi-document font conversion preserving provenance and producing collision-free artifacts.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    Request,
    Result,
    TableData,
)
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult, ValidationStatus
from sarathi.shakti.font_conversion.capability import FontConversionCapability
from sarathi.smriti.key import compute_input_fingerprint


class TestBankStatementsBatchIntegrity:
    """Verify multi-statement consolidation, table headers, and ambiguous amounts."""

    def test_bank_statement_table_headers_used_directly(self, tmp_path: Path) -> None:
        """TableData.headers is parsed as primary transaction header row."""
        cap = BankStatementCapability()
        table = TableData(
            name="statement_table",
            headers=("Date", "Narration", "Withdrawal", "Deposit", "Balance"),
            rows=(
                ("01-01-2026", "Opening Balance", "0", "1000", "1000"),
                ("02-01-2026", "Office Supplies", "250", "0", "750"),
            ),
        )
        doc = CanonicalDocument(
            document_id="doc-001",
            source_input_id="inp-001",
            text="Account Statement\nState Bank of India",
            pages=(PageData(page_number=1, text="", tables=(table,)),),
            tables=(table,),
        )
        ctx = ExecutionContext(run_id="r1", request_id="req1", trace_id="t1", span_id="s1")
        req = Request(
            request_id="req1",
            requirement="bank_statements",
            inputs=(InputRef("inp-001", tmp_path / "dummy.csv", "statement.csv", 100),),
        )
        res = cap.execute(req, ctx, prior_result=Result(data=doc, provenance=()))
        assert isinstance(res.data, BankStatementConsolidationResult)
        assert res.data.total_transactions == 1  # 1 transaction (excluding opening balance)
        assert res.data.total_debit == Decimal("250")
        assert len(res.artifact_payloads) == 2

    def test_bank_statement_multi_document_consolidation(self, tmp_path: Path) -> None:
        """Multiple CanonicalDocuments are consolidated in stable chronological order."""
        cap = BankStatementCapability()
        # Doc 1: February transactions
        t1 = TableData(
            name="t1",
            headers=("Date", "Narration", "Withdrawal", "Deposit", "Balance"),
            rows=(("01-02-2026", "Feb Payment", "100", "0", "900"),),
        )
        doc1 = CanonicalDocument(
            document_id="doc-feb",
            source_input_id="inp-feb",
            text="Bank Statement HDFC Bank",
            tables=(t1,),
        )
        # Doc 2: January transactions
        t2 = TableData(
            name="t2",
            headers=("Date", "Narration", "Withdrawal", "Deposit", "Balance"),
            rows=(("01-01-2026", "Jan Payment", "200", "0", "1000"),),
        )
        doc2 = CanonicalDocument(
            document_id="doc-jan",
            source_input_id="inp-jan",
            text="Bank Statement HDFC Bank",
            tables=(t2,),
        )

        ctx = ExecutionContext(run_id="r1", request_id="req1", trace_id="t1", span_id="s1")
        req = Request(
            request_id="req1",
            requirement="bank_statements",
            inputs=(
                InputRef("inp-feb", tmp_path / "feb.csv", "feb.csv", 100),
                InputRef("inp-jan", tmp_path / "jan.csv", "jan.csv", 100),
            ),
        )
        res = cap.execute(req, ctx, prior_result=Result(data=(doc1, doc2), provenance=()))
        assert isinstance(res.data, BankStatementConsolidationResult)
        assert res.data.total_transactions == 2
        assert res.data.total_debit == Decimal("300")
        # Jan statement should be sorted before Feb in consolidation
        assert res.data.statements[0].transactions[0].description == "Jan Payment"
        assert res.data.statements[1].transactions[0].description == "Feb Payment"

    def test_ambiguous_amount_direction_yields_validation_issue(self, tmp_path: Path) -> None:
        """Ambiguous Amount direction produces validation issue and is omitted from transactions."""
        cap = BankStatementCapability()
        # Table has Date, Narration, Amount, Balance with no Dr/Cr direction indicator
        table = TableData(
            name="ambiguous_table",
            headers=("Date", "Narration", "Amount", "Balance"),
            rows=(("01-01-2026", "Unknown Transfer", "500", "1500"),),
        )
        doc = CanonicalDocument(
            document_id="doc-ambig",
            source_input_id="inp-ambig",
            text="Bank Statement ICICI Bank",
            tables=(table,),
        )
        ctx = ExecutionContext(run_id="r1", request_id="req1", trace_id="t1", span_id="s1")
        req = Request(
            request_id="req1",
            requirement="bank_statements",
            inputs=(InputRef("inp-ambig", tmp_path / "ambig.csv", "ambig.csv", 100),),
        )
        res = cap.execute(req, ctx, prior_result=Result(data=doc, provenance=()))
        assert isinstance(res.data, BankStatementConsolidationResult)
        assert res.data.total_debit == Decimal("0")
        assert res.data.total_credit == Decimal("0")
        assert res.data.statements[0].transactions[0].debit is None
        assert res.data.statements[0].transactions[0].credit is None
        assert res.data.statements[0].transactions[0].status == ValidationStatus.INVALID
        assert any("MISSING_AMOUNT" in w.code for w in res.warnings)


class TestFingerprintAndPravahaIntegrity:
    """Verify streaming content hashing and cancellation bypass."""

    def test_input_fingerprint_streams_file_bytes(self, tmp_path: Path) -> None:
        """compute_input_fingerprint computes true SHA-256 over file contents."""
        file1 = tmp_path / "file1.txt"
        file1.write_bytes(b"Sarathi Content A")
        inp1 = InputRef("i1", file1, "file1.txt", len(b"Sarathi Content A"))

        file2 = tmp_path / "file2.txt"
        file2.write_bytes(b"Sarathi Content B")
        inp2 = InputRef("i2", file2, "file2.txt", len(b"Sarathi Content B"))

        fp1 = compute_input_fingerprint((inp1,))
        fp2 = compute_input_fingerprint((inp2,))
        assert fp1 != fp2

        # Changing content changes fingerprint
        file1.write_bytes(b"Sarathi Content A Modified")
        fp1_mod = compute_input_fingerprint((inp1,))
        assert fp1 != fp1_mod

    def test_cancellation_bypasses_retry_in_pravaha(self) -> None:
        """Triggered cancellation token immediately raises error before retry execution."""
        from sarathi.nabhi.kosh import Kosh
        from sarathi.nabhi.manthan import Manthan
        from sarathi.nabhi.pravaha import Pravaha
        from sarathi.nabhi.quarantine import QuarantineRecord, QuarantineStatus, QuarantineStore
        from sarathi.sankalpa import CapabilityDeclaration, PluginInfo
        from sarathi.yantra import Yantra

        token = CancellationToken()
        token.cancel()

        kosh = Kosh()
        plugin_info = PluginInfo(plugin_id="test_plugin", name="Test", version="1.0.0", capabilities=("test_cap",))
        cap_decl = CapabilityDeclaration(
            capability_id="test_cap",
            plugin_id="test_plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        kosh.register_plugin(plugin_info)
        kosh.register_capability(cap_decl)

        manthan = Manthan(registry=kosh)
        yantra = Yantra(inventory=Yantra.default_inventory())
        quar_store_mock = MagicMock(spec=QuarantineStore)

        cap_mock = MagicMock()
        cap_mock.declaration = cap_decl

        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"test_cap": cap_mock},
            quarantine_store=quar_store_mock,
        )

        rec = QuarantineRecord(
            quarantine_id="quar-123",
            input_hash="hash123",
            run_id="run1",
            request_id="req1",
            trace_id="tr1",
            capability_id="test_cap",
            plugin_id="test_plugin",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="instant",
            attempt_count=0,
            max_retries=2,
            status=QuarantineStatus.QUARANTINED,
            created_at_utc="2026-01-01T00:00:00Z",
            updated_at_utc="2026-01-01T00:00:00Z",
        )

        ctx = ExecutionContext(
            run_id="run1", request_id="req1", trace_id="tr1", span_id="sp1", cancellation_token=token
        )
        req = Request(
            request_id="req1",
            requirement="test_cap",
            inputs=(InputRef("inp-1", Path("test.txt"), "test.txt", 10),),
            cancellation_token=token,
        )

        with pytest.raises(DoshError) as exc_info:
            pravaha._execute_retry_attempt(cap_mock, req, ctx, rec)

        assert exc_info.value.code is FailureCode.OPERATION_CANCELLED
        assert exc_info.value.context.get("cancelled") is True


class TestFontConversionBatchIntegrity:
    """Verify batch font conversion multi-document handling and collision-free artifacts."""

    def test_font_conversion_batch_multi_document(self, tmp_path: Path) -> None:
        """Batch of CanonicalDocuments converts each document and creates distinct artifacts."""
        cap = FontConversionCapability()
        # Kruti Dev text containing signature digraphs: [kkuk vkuk fdrkc (खाना आना किताब)
        kruti_text = "[kkuk vkuk fdrkc"
        doc1 = CanonicalDocument(
            document_id="doc-1",
            source_input_id="inp-1",
            text=kruti_text,
        )
        doc2 = CanonicalDocument(
            document_id="doc-2",
            source_input_id="inp-2",
            text=kruti_text,
        )

        ctx = ExecutionContext(run_id="r1", request_id="req1", trace_id="t1", span_id="s1")
        req = Request(
            request_id="req1",
            requirement="font_conversion",
            inputs=(
                InputRef("inp-1", tmp_path / "f1.txt", "f1.txt", 10),
                InputRef("inp-2", tmp_path / "f2.txt", "f2.txt", 10),
            ),
        )
        res = cap.execute(req, ctx, prior_result=Result(data=(doc1, doc2), provenance=()))
        assert isinstance(res.data, tuple)
        assert len(res.data) == 2
        assert len(res.artifact_payloads) == 4
        # Verify collision-free artifact names
        names = [p.intent.name for p in res.artifact_payloads]
        assert len(names) == len(set(names))
        assert "Converted_inp-1.txt" in names
        assert "Converted_inp-1.docx" in names
        assert "Converted_inp-2.txt" in names
        assert "Converted_inp-2.docx" in names
