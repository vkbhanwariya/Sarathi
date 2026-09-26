from datetime import date, datetime, time
from pathlib import Path

from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    PageData,
    Request,
    Result,
    TableData,
    TextSpan,
)
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.models import BankStatement, Transaction, ValidationStatus
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
        assert len(res.artifact_payloads) >= 2

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


def test_bounded_date_inheritance_and_missing_date_issue() -> None:
    """Missing date only inherits within same table; unparsed initial date records explicit issue."""
    cap = BankStatementCapability()

    t1 = TableData(
        name="t1",
        headers=("Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(
            ("01/01/2026", "Txn 1", "100.00", "", "900.00"),
            ("", "Txn 2 continuation date", "200.00", "", "700.00"),
        ),
    )
    t2 = TableData(
        name="t2",
        headers=("Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(
            ("", "Orphan Date Row", "300.00", "", "400.00"),
            ("05/01/2026", "Valid Row", "100.00", "", "300.00"),
        ),
    )

    doc = CanonicalDocument(
        document_id="doc-bounded-date",
        source_input_id="inp-bounded",
        text="State Bank of India Statement Account Number: 12345678901",
        tables=(t1, t2),
    )
    req = Request(
        request_id="req-test",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-test", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))

    assert res.data is not None
    stmt = res.data.statements[0]
    assert len(stmt.transactions) == 3
    assert stmt.transactions[0].transaction_date == date(2026, 1, 1)
    assert stmt.transactions[1].transaction_date == date(2026, 1, 1)
    assert stmt.transactions[2].transaction_date == date(2026, 1, 5)
    assert any(iss.code == "MISSING_TRANSACTION_DATE" for iss in stmt.issues)


def test_invalid_date_does_not_inherit_previous_date() -> None:
    """Invalid non-blank date must emit INVALID_TRANSACTION_DATE and not inherit predecessor date."""
    cap = BankStatementCapability()

    table = TableData(
        name="txns",
        headers=("Date", "Narration", "Withdrawal", "Deposit", "Balance"),
        rows=(
            ("01/01/2026", "Valid Txn 1", "100.00", "", "1000.00"),
            ("31/02/2026", "Invalid Date Txn", "50.00", "", "950.00"),
            ("", "Continuation Txn with Blank Date", "25.00", "", "925.00"),
        ),
    )

    doc = CanonicalDocument(
        document_id="doc-bad-date",
        source_input_id="inp-bad-date",
        text="State Bank of India Statement Account Number: 12345678901",
        tables=(table,),
    )
    req = Request(
        request_id="req-test-bad-date",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-bad-date", "req-test-bad-date", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt = res.data.statements[0]

    invalid_date_issues = [iss for iss in stmt.issues if iss.code == "INVALID_TRANSACTION_DATE"]
    assert len(invalid_date_issues) == 1
    assert "31/02/2026" in invalid_date_issues[0].message
    assert len(stmt.transactions) == 2
    assert stmt.transactions[0].description == "Valid Txn 1"
    assert stmt.transactions[0].transaction_date == date(2026, 1, 1)
    assert stmt.transactions[1].description == "Continuation Txn with Blank Date"
    assert stmt.transactions[1].transaction_date == date(2026, 1, 1)


def test_time_and_value_date_wiring() -> None:
    """Time and Value Date mapped and populated on Transaction."""
    cap = BankStatementCapability()

    table = TableData(
        name="icici_txns",
        headers=(
            "Transaction Date",
            "Value Date",
            "Time",
            "Particulars",
            "Cheque No.",
            "Withdrawal",
            "Deposit",
            "Balance",
        ),
        rows=(("10/02/2026", "11/02/2026", "14:30:00", "Cheque Clearing", "000123", "1500.00", "", "8500.00"),),
    )

    doc = CanonicalDocument(
        document_id="doc-icici-val",
        source_input_id="inp-icici",
        text="ICICI Bank Statement Account Number: 000105001234",
        tables=(table,),
    )
    req = Request(
        request_id="req-test",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-test", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))

    assert res.data is not None
    stmt = res.data.statements[0]
    assert len(stmt.transactions) == 1
    tx = stmt.transactions[0]
    assert tx.transaction_date == date(2026, 2, 10)
    assert tx.value_date == date(2026, 2, 11)
    assert tx.transaction_time == time(14, 30, 0)
    assert tx.cheque_number == "000123"


def test_bank_eod_balance_row_classification() -> None:
    """Rows marked with EOD Balance must be classified as EOD_BALANCE."""
    row = ("31/01/2026", "EOD BALANCE", "", "", "50000.00")
    assert classify_row(row) == RowType.EOD_BALANCE


def test_bank_models_expose_canonical_veda_properties() -> None:
    """Verify statement_from, statement_to, and posting_datetime properties on models."""
    d_start = date(2026, 1, 1)
    d_end = date(2026, 1, 31)
    stmt = BankStatement(
        bank_name="Test Bank",
        bank_profile="generic",
        statement_period_start=d_start,
        statement_period_end=d_end,
    )
    assert stmt.statement_from == d_start
    assert stmt.statement_to == d_end

    tx = Transaction(
        transaction_date=d_start,
        description="Test",
        bank_name="Test Bank",
        posting_date=d_start,
    )
    assert tx.posting_datetime == datetime(2026, 1, 1, 0, 0)


def test_scanned_ocr_table_reconstruction_from_spans(tmp_path: Path) -> None:
    """Scanned OCR document without explicit tables must reconstruct table grid from bounding box spans."""
    from decimal import Decimal

    # Header metadata spans
    spans = [
        TextSpan(text="State Bank of India", bounding_box=(20.0, 30.0, 180.0, 45.0)),
        TextSpan(text="Account Number: 30123456789", bounding_box=(20.0, 50.0, 220.0, 65.0)),
        TextSpan(text="IFSC: SBIN0001234", bounding_box=(20.0, 70.0, 150.0, 85.0)),
        # Column headers row (y ~ 100)
        TextSpan(text="Txn Date", bounding_box=(20.0, 100.0, 80.0, 115.0)),
        TextSpan(text="Narration", bounding_box=(90.0, 100.0, 250.0, 115.0)),
        TextSpan(text="Withdrawal (Dr)", bounding_box=(260.0, 100.0, 360.0, 115.0)),
        TextSpan(text="Deposit (Cr)", bounding_box=(370.0, 100.0, 470.0, 115.0)),
        TextSpan(text="Closing Balance", bounding_box=(480.0, 100.0, 580.0, 115.0)),
        # Transaction row 1 (y ~ 140)
        TextSpan(text="05/01/2026", bounding_box=(20.0, 140.0, 80.0, 155.0)),
        TextSpan(text="ATM CASH WDL", bounding_box=(90.0, 140.0, 240.0, 155.0)),
        TextSpan(text="2000.00", bounding_box=(260.0, 140.0, 330.0, 155.0)),
        TextSpan(text="18000.00", bounding_box=(480.0, 140.0, 550.0, 155.0)),
        # Transaction row 2 (y ~ 180)
        TextSpan(text="10/01/2026", bounding_box=(20.0, 180.0, 80.0, 195.0)),
        TextSpan(text="SALARY CREDIT", bounding_box=(90.0, 180.0, 240.0, 195.0)),
        TextSpan(text="50000.00", bounding_box=(370.0, 180.0, 440.0, 195.0)),
        TextSpan(text="68000.00", bounding_box=(480.0, 180.0, 550.0, 195.0)),
    ]

    doc_text = (
        "State Bank of India\n"
        "Account Statement for Account Number: 30123456789\n"
        "IFSC: SBIN0001234\n"
        "Available Balance: 68000.00\n"
        "Closing Balance: 68000.00\n"
        "Txn Date Narration Withdrawal Deposit Closing Balance\n"
    )
    page = PageData(page_number=1, text=doc_text, spans=tuple(spans), tables=())
    doc = CanonicalDocument(
        document_id="doc-scanned-1",
        source_input_id="in-scanned-1",
        pages=(page,),
        tables=(),  # No tables extracted natively (OCR output)
        text=doc_text,
    )

    cap = BankStatementCapability()
    dummy_file = tmp_path / "dummy.pdf"
    dummy_file.write_bytes(b"dummy")
    req = Request(
        request_id="req-scanned-1",
        requirement="bank_statements",
        inputs=(InputRef("in-scanned-1", dummy_file, "dummy.pdf", dummy_file.stat().st_size),),
    )
    ctx = ExecutionContext("run-1", "req-scanned-1", "t1", "s1")

    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    assert isinstance(res, Result)
    assert res.metadata["input_outcomes"]["in-scanned-1"] == "SUCCESS"
    consolidation = res.data
    assert len(consolidation.statements) == 1
    stmt = consolidation.statements[0]
    assert stmt.status == ValidationStatus.VALID
    assert len(stmt.transactions) == 2

    # Check parsed transaction values
    tx1, tx2 = stmt.transactions
    assert tx1.transaction_date == date(2026, 1, 5)
    assert tx1.debit == Decimal("2000.00")
    assert tx1.credit is None
    assert tx1.running_balance == Decimal("18000.00")

    assert tx2.transaction_date == date(2026, 1, 10)
    assert tx2.credit == Decimal("50000.00")
    assert tx2.debit is None
    assert tx2.running_balance == Decimal("68000.00")


def test_classify_bd_and_cd_rows() -> None:
    """Rows with B/D and C/D ledger balance tokens must classify accurately."""
    assert classify_row(["01/01/2026", "BAL B/D", "", "", "", "12000.00"]) == RowType.OPENING_BALANCE
    assert classify_row(["01/01/2026", "BALANCE B/D", "", "", "", "12000.00"]) == RowType.OPENING_BALANCE
    assert classify_row(["31/01/2026", "BAL C/D", "", "", "", "25000.00"]) == RowType.CLOSING_BALANCE
    assert classify_row(["31/01/2026", "BALANCE C/D", "", "", "", "25000.00"]) == RowType.CLOSING_BALANCE


def test_single_amount_with_single_letter_d_c_indicators(tmp_path: Path) -> None:
    """Single amount column with D / C direction flags resolves accurately to debit / credit."""
    from decimal import Decimal

    doc_text = """
    STATE BANK OF INDIA
    Account Number: 12345678901
    IFSC: SBIN0001234
    """
    table = TableData(
        headers=("Txn Date", "Narration", "Ref No", "Amount", "Type", "Balance"),
        rows=(
            ("01/01/2026", "ATM CASH WDL", "ATM101", "2,000.00", "D", "18,000.00"),
            ("05/01/2026", "SALARY DEPOSIT", "NEFT202", "50,000.00", "C", "68,000.00"),
        ),
    )
    doc = CanonicalDocument(
        document_id="doc-single-amt",
        text=doc_text,
        tables=(table,),
    )
    dummy = tmp_path / "dummy.pdf"
    dummy.write_bytes(b"dummy")
    cap = BankStatementCapability()
    req = Request(
        request_id="req-single-amt",
        requirement="bank_statements",
        inputs=(InputRef("in-single-amt", dummy, "dummy.pdf", dummy.stat().st_size),),
    )
    ctx = ExecutionContext("run-1", "req-single-amt", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    assert isinstance(res, Result)
    stmt = res.data.statements[0]
    assert len(stmt.transactions) == 2
    assert stmt.transactions[0].debit == Decimal("2000.00")
    assert stmt.transactions[0].credit is None
    assert stmt.transactions[1].credit == Decimal("50000.00")
    assert stmt.transactions[1].debit is None


def test_boundary_balance_from_metadata_patterns_fallback(tmp_path: Path) -> None:
    """Boundary balances in header text outside the table are extracted via metadata_patterns."""
    from decimal import Decimal

    # Profile with opening/closing balance regex
    custom_banks = tmp_path / "banks"
    custom_banks.mkdir(parents=True)
    custom_profile = custom_banks / "sbi_test.yaml"
    custom_profile.write_text(
        """
profile_id: "sbi_test"
parent_bank: "sbi"
bank_name: "State Bank of India"
headers:
  date: ["txn date"]
  description: ["narration"]
  debit: ["debit"]
  credit: ["credit"]
  balance: ["balance"]
metadata_patterns:
  account_number: 'A\\/c\\s*No\\.?\\s*[:\\-]?\\s*([0-9]{11})'
  opening_balance: 'Opening\\s*Balance\\s*[:\\-]?\\s*([0-9,]+\\.\\d{2})'
  closing_balance: 'Closing\\s*Balance\\s*[:\\-]?\\s*([0-9,]+\\.\\d{2})'
""",
        encoding="utf-8",
    )

    doc_text = """
    STATE BANK OF INDIA
    A/c No: 12345678901
    Opening Balance: 10,000.00
    Closing Balance: 13,000.00
    """
    table = TableData(
        headers=("Txn Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(("01/01/2026", "INTEREST CR", "", "3,000.00", "13,000.00"),),
    )
    doc = CanonicalDocument(
        document_id="doc-meta-bal",
        text=doc_text,
        tables=(table,),
    )
    dummy = tmp_path / "dummy.pdf"
    dummy.write_bytes(b"dummy")
    cap = BankStatementCapability(banks_dir=custom_banks)
    req = Request(
        request_id="req-meta-bal",
        requirement="bank_statements",
        inputs=(InputRef("in-meta-bal", dummy, "dummy.pdf", dummy.stat().st_size),),
    )
    ctx = ExecutionContext("run-1", "req-meta-bal", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt = res.data.statements[0]
    assert stmt.opening_balance == Decimal("10000.00")
    assert stmt.closing_balance == Decimal("13000.00")


def test_value_date_only_statement_extracts_transactions(tmp_path: Path) -> None:
    """Statements containing only 'Value Date' (no Txn Date) must extract rows and record date_supplied."""
    from decimal import Decimal

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    table = TableData(
        headers=("Value Date", "Description", "Ref No", "Debit", "Credit", "Balance"),
        rows=(("15/01/2026", "CLEARING PAYMENT", "CLR12345", "500.00", "", "9500.00"),),
    )
    doc = CanonicalDocument(
        document_id="doc-val-date-only",
        text="BANK STATEMENT\nAccount: 12345678901\n",
        tables=(table,),
    )
    dummy = tmp_path / "dummy.pdf"
    dummy.write_bytes(b"dummy")
    cap = BankStatementCapability()
    req = Request(
        request_id="req-val-date",
        requirement="bank_statements",
        inputs=(InputRef("inp-val-date", dummy, "dummy.pdf", dummy.stat().st_size),),
    )
    ctx = ExecutionContext("run-vd", "req-val-date", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt = res.data.statements[0]
    assert len(stmt.transactions) == 1
    tx = stmt.transactions[0]
    assert tx.transaction_date == date(2026, 1, 15)
    assert tx.value_date == date(2026, 1, 15)
    assert tx.debit == Decimal("500.00")
    assert tx.metadata.get("date_supplied") == "value_date"


def test_currency_detection_and_grouping(tmp_path: Path) -> None:
    """Non-INR statements (e.g. USD) preserve currency in Statement, Transaction, and totals_by_currency."""
    from decimal import Decimal

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    doc_text = """
    GLOBAL COMMERCIAL BANK
    Account No: 987654321012
    Currency: USD
    Opening Balance: 1,000.00
    Closing Balance: 1,200.00
    """
    table = TableData(
        headers=("Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(("10/01/2026", "WIRE TRANSFER USD", "", "200.00", "1200.00"),),
    )
    doc = CanonicalDocument(
        document_id="doc-usd",
        text=doc_text,
        tables=(table,),
    )
    dummy = tmp_path / "dummy.pdf"
    dummy.write_bytes(b"dummy")
    cap = BankStatementCapability()
    req = Request(
        request_id="req-usd",
        requirement="bank_statements",
        inputs=(InputRef("inp-usd", dummy, "dummy.pdf", dummy.stat().st_size),),
    )
    ctx = ExecutionContext("run-usd", "req-usd", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    cons = res.data
    stmt = cons.statements[0]
    assert stmt.currency == "USD"
    assert len(stmt.transactions) == 1
    tx = stmt.transactions[0]
    assert tx.currency == "USD"
    assert "USD" in cons.totals_by_currency
    assert cons.totals_by_currency["USD"] == (Decimal("0.00"), Decimal("200.00"))


def test_parenthesized_and_dr_overdraft_header_balances(tmp_path: Path) -> None:
    """Opening/closing balances with parenthesized or (Dr) overdraft expressions parse to negative Decimals."""
    from decimal import Decimal

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    doc_text = """
    STATE BANK OF INDIA
    Account No: 12345678901
    Opening Balance: 100.00 (Dr)
    Closing Balance: (250.00)
    """
    table = TableData(
        headers=("Txn Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(("01/01/2026", "CHARGE", "150.00", "", "-250.00"),),
    )
    doc = CanonicalDocument(
        document_id="doc-od-headers",
        text=doc_text,
        tables=(table,),
    )
    dummy = tmp_path / "dummy.pdf"
    dummy.write_bytes(b"dummy")
    cap = BankStatementCapability()
    req = Request(
        request_id="req-od",
        requirement="bank_statements",
        inputs=(InputRef("inp-od", dummy, "dummy.pdf", dummy.stat().st_size),),
    )
    ctx = ExecutionContext("run-od", "req-od", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt = res.data.statements[0]
    assert stmt.opening_balance == Decimal("-100.00")
    assert stmt.closing_balance == Decimal("-250.00")


def test_stable_statement_id_across_different_input_labels(tmp_path: Path) -> None:
    """Statement IDs must remain identical even if imported with different transient input labels."""
    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    doc_text = """
    BANK OF INDIA
    Account No: 112233445566
    Opening Balance: 5,000.00
    Closing Balance: 5,000.00
    """
    table = TableData(
        headers=("Date", "Description", "Debit", "Credit", "Balance"),
        rows=(),
    )
    dummy = tmp_path / "statement.pdf"
    dummy.write_bytes(b"content-fingerprint-payload")

    doc1 = CanonicalDocument(
        document_id="doc-import-1",
        text=doc_text,
        tables=(table,),
        metadata={"file_fingerprint": "abc123sha256"},
    )
    cap = BankStatementCapability()
    req1 = Request(
        request_id="req-1",
        requirement="bank_statements",
        inputs=(InputRef("inp-001", dummy, "statement.pdf", dummy.stat().st_size),),
    )
    res1 = cap.execute(req1, ExecutionContext("r1", "req-1", "t1", "s1"), prior_result=Result(data=doc1))
    stmt_id_1 = res1.data.statements[0].statement_id

    doc2 = CanonicalDocument(
        document_id="doc-import-2",
        text=doc_text,
        tables=(table,),
        metadata={"file_fingerprint": "abc123sha256"},
    )
    req2 = Request(
        request_id="req-2",
        requirement="bank_statements",
        inputs=(InputRef("inp-999", dummy, "statement.pdf", dummy.stat().st_size),),
    )
    res2 = cap.execute(req2, ExecutionContext("r2", "req-2", "t1", "s1"), prior_result=Result(data=doc2))
    stmt_id_2 = res2.data.statements[0].statement_id

    assert stmt_id_1 == stmt_id_2
    assert "inp-001" not in stmt_id_1
    assert "inp-999" not in stmt_id_2


def test_classify_row_preserves_transactions_with_balance_phrases_or_short_codes() -> None:
    """Transactions with valid date and debit/credit must never be dropped as opening/closing balance."""
    # 1. Closed account narration
    row1 = ["01/01/2026", "TRANSFER TO CLOSED A/C 1234", "500.00", "", "4500.00"]
    assert classify_row(row1, date_col_idx=0, amount_col_indices=[2, 3], balance_col_idx=4) == RowType.TRANSACTION
    assert classify_row(row1, date_col_idx=0) == RowType.TRANSACTION

    # 2. C/D abbreviation in merchant name
    row2 = ["01/01/2026", "POS STORE C/D 999", "150.00", "", "4350.00"]
    assert classify_row(row2, date_col_idx=0, amount_col_indices=[2, 3], balance_col_idx=4) == RowType.TRANSACTION
    assert classify_row(row2, date_col_idx=0) == RowType.TRANSACTION

    # 3. Fee for closing balance advice / certificate
    row3 = ["01/01/2026", "FEE FOR CLOSING BALANCE CERTIFICATE", "100.00", "", "4250.00"]
    assert classify_row(row3, date_col_idx=0, amount_col_indices=[2, 3], balance_col_idx=4) == RowType.TRANSACTION
    assert classify_row(row3, date_col_idx=0) == RowType.TRANSACTION

    # 4. B/F short code in refund narration
    row4 = ["01/01/2026", "REFUND B/F TRAVEL PORTAL", "", "350.00", "4600.00"]
    assert classify_row(row4, date_col_idx=0, amount_col_indices=[2, 3], balance_col_idx=4) == RowType.TRANSACTION
    assert classify_row(row4, date_col_idx=0) == RowType.TRANSACTION

    # 5. Genuine opening and closing balance rows without transaction amounts remain balance rows
    row_open = ["01/01/2026", "OPENING BALANCE", "", "", "5000.00"]
    assert classify_row(row_open, date_col_idx=0, amount_col_indices=[2, 3], balance_col_idx=4) == RowType.OPENING_BALANCE

    row_close = ["31/01/2026", "CLOSING BALANCE", "", "", "10000.00"]
    assert classify_row(row_close, date_col_idx=0, amount_col_indices=[2, 3], balance_col_idx=4) == RowType.CLOSING_BALANCE


def test_capability_does_not_drop_transaction_with_balance_phrase_in_narration() -> None:
    """BankStatementCapability must retain transactions whose descriptions mention balance terms."""
    from decimal import Decimal
    from pathlib import Path

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    headers = ("Date", "Description", "Debit", "Credit", "Balance")
    row_open = ("01/01/2026", "OPENING BALANCE", "", "", "5000.00")
    row_tx1 = ("02/01/2026", "TRANSFER TO CLOSED A/C 9999", "500.00", "", "4500.00")
    row_tx2 = ("03/01/2026", "POS STORE C/D", "200.00", "", "4300.00")
    row_close = ("31/01/2026", "CLOSING BALANCE", "", "", "4300.00")

    table = TableData(headers=headers, rows=(row_open, row_tx1, row_tx2, row_close))
    doc = CanonicalDocument(
        document_id="doc-closed-ac",
        text="Bank Statement\nAccount Number: 987654321012\nIFSC: HDFC0000123",
        tables=(table,),
    )
    req = Request(
        request_id="req-closed-ac",
        requirement="bank_statements",
        inputs=(InputRef("inp-1", Path("stmt.csv"), "stmt.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-closed-ac", "t1", "s1")
    cap = BankStatementCapability()
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt = res.data.statements[0]

    # Both transactions must be extracted and preserved in the ledger
    assert len(stmt.transactions) == 2
    assert stmt.transactions[0].description == "TRANSFER TO CLOSED A/C 9999"
    assert stmt.transactions[0].debit == Decimal("500.00")
    assert stmt.transactions[1].description == "POS STORE C/D"
    assert stmt.transactions[1].debit == Decimal("200.00")
    assert stmt.opening_balance == Decimal("5000.00")
    assert stmt.closing_balance == Decimal("4300.00")
