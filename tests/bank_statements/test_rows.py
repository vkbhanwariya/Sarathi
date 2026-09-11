"""Tests for Raw Row Classification."""

from sarathi.shakti.bank_statements.row_classifier import RowType, classify_row


def test_classify_transaction_row() -> None:
    row = ["01/01/2026", "UPI-1234-Merchant", "UPI1234", "100.00", "", "5000.00"]
    assert classify_row(row, date_col_idx=0) == RowType.TRANSACTION


def test_classify_opening_balance_row() -> None:
    row = ["01/01/2026", "OPENING BALANCE", "", "", "", "5100.00"]
    assert classify_row(row) == RowType.OPENING_BALANCE


def test_classify_closing_balance_row() -> None:
    row = ["31/01/2026", "CLOSING BALANCE B/F", "", "", "", "10500.00"]
    assert classify_row(row) == RowType.CLOSING_BALANCE


def test_classify_noise_and_summary_row() -> None:
    assert classify_row(["", "", "", ""]) == RowType.NOISE
    assert classify_row(["Total Debits / Credits", "1000.00", "5000.00"]) == RowType.SUMMARY


def test_classify_row_with_financial_figures_but_no_date() -> None:
    """Rows with financial figures but no date must be classified as TRANSACTION, not CONTINUATION."""
    row = ["", "Second Transfer Same Day", "REF999", "250.00", "", "4750.00"]
    # With explicit amount col indices
    assert classify_row(row, date_col_idx=0, amount_col_indices=[3, 4, 5]) == RowType.TRANSACTION
    # With fallback monetary inspection
    assert classify_row(row, date_col_idx=0) == RowType.TRANSACTION


def test_classify_row_pure_continuation() -> None:
    """Rows with text but no financial figures are classified as CONTINUATION."""
    row = ["", "Extended details of prior transaction with no amounts", "", "", "", ""]
    assert classify_row(row, date_col_idx=0, amount_col_indices=[3, 4, 5]) == RowType.CONTINUATION


def test_date_inheritance_resolution_in_capability() -> None:
    """A row with financial figures but no date inherits date from previous transaction and stays distinct."""
    from datetime import date
    from decimal import Decimal
    from pathlib import Path

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability
    from sarathi.shakti.bank_statements.models import BankStatement

    headers = ("Date", "Description", "Debit", "Credit", "Balance")
    row1 = ("01/01/2026", "First Tx", "100.00", "", "5000.00")
    row2 = ("", "Second Tx No Date", "200.00", "", "4800.00")
    row3 = ("", "Narration for second tx", "", "", "")

    table = TableData(rows=(headers, row1, row2, row3))
    doc = CanonicalDocument(
        document_id="doc-date-inherit",
        text="Bank Statement\nAccount Number: 1234567890",
        tables=(table,),
    )
    req = Request(
        request_id="req-date-inherit",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-date-inherit", "t1", "s1")
    cap = BankStatementCapability()
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt: BankStatement = res.data.statements[0]

    assert len(stmt.transactions) == 2
    tx1, tx2 = stmt.transactions[0], stmt.transactions[1]
    assert tx1.transaction_date == date(2026, 1, 1)
    assert tx1.description == "First Tx"
    assert tx1.debit == Decimal("100.00")

    # Inherited date from previous transaction, narration kept separate
    assert tx2.transaction_date == date(2026, 1, 1)
    assert "Second Tx No Date" in tx2.description
    assert "Narration for second tx" in tx2.description
    assert tx2.debit == Decimal("200.00")


def test_classify_row_with_summary_keyword_in_narration() -> None:
    """Row with valid date and financial amount must not be dropped as SUMMARY merely because narration contains 'total'."""
    row = ["01/01/2026", "TOTAL petrol payment", "100.00"]
    assert classify_row(row, date_col_idx=0, amount_col_indices=[2]) == RowType.TRANSACTION


def test_classify_row_with_integer_amount() -> None:
    """Row with integer amount (e.g. '1000') must be recognized as TRANSACTION, not CONTINUATION."""
    row = ["", "second payment", "1000"]
    assert classify_row(row, date_col_idx=0, amount_col_indices=[2]) == RowType.TRANSACTION


def test_bank_statement_continuation_row_strictly_table_scoped() -> None:
    """Verify continuation row in Table 2 does not leak onto preceding transaction of Table 1."""
    from pathlib import Path

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability
    from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult

    cap = BankStatementCapability()

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


class TestBankStatementsBatchIntegrity:
    """Verify multi-statement consolidation, table headers, and ambiguous amounts."""

    def test_bank_statement_table_headers_used_directly(self, tmp_path) -> None:
        """TableData.headers is parsed as primary transaction header row."""
        from decimal import Decimal

        from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, PageData, Request, Result, TableData
        from sarathi.shakti.bank_statements.capability import BankStatementCapability
        from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult

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
        assert res.data.total_transactions == 1
        assert res.data.total_debit == Decimal("250")
        assert len(res.artifact_payloads) == 2

    def test_bank_statement_multi_document_consolidation(self, tmp_path) -> None:
        """Multiple CanonicalDocuments are consolidated in stable chronological order."""
        from decimal import Decimal

        from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
        from sarathi.shakti.bank_statements.capability import BankStatementCapability
        from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult

        cap = BankStatementCapability()
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
        assert res.data.statements[0].transactions[0].description == "Jan Payment"
        assert res.data.statements[1].transactions[0].description == "Feb Payment"

    def test_ambiguous_amount_direction_yields_validation_issue(self, tmp_path) -> None:
        """Ambiguous Amount direction produces validation issue and is omitted from transactions."""
        from decimal import Decimal

        from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
        from sarathi.shakti.bank_statements.capability import BankStatementCapability
        from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult, ValidationStatus

        cap = BankStatementCapability()
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
