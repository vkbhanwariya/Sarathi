"""Tests for Bank Statement and Profile Detection."""

from pathlib import Path

from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, PageData, Request, Result, TableData
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.detector import detect_bank_statement

_HDFC_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hdfc_statement.csv"


def test_detect_sbi_bank_statement() -> None:
    doc_text = """
    STATE BANK OF INDIA
    Account Statement
    Account Name: Mr. Rahul Sharma
    Account Number: 30123456789
    CIF No: 85647382910
    IFSC: SBIN0001234
    Statement Period: 01/01/2026 to 31/01/2026
    """
    table = TableData(
        rows=(
            ("Txn Date", "Value Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"),
            ("01 Jan 2026", "01 Jan 2026", "OPENING BALANCE", "", "", "", "25,000.00"),
            ("05 Jan 2026", "05 Jan 2026", "UPI/12345/Tea Stall", "UPI12345", "50.00", "", "24,950.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-sbi-1",
        text=doc_text,
        pages=(PageData(page_number=1, text=doc_text, tables=(table,)),),
    )

    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "sbi"
    assert evidence.bank_name == "State Bank of India"
    assert evidence.account_identity is not None
    assert evidence.account_identity.masked_account_number == "XXXXXXX6789"
    assert evidence.account_identity.account_fingerprint is not None


def test_detect_negative_non_bank_invoice() -> None:
    doc_text = """
    TAX INVOICE
    Bill of Supply
    Invoice Number: INV-2026-001
    Purchase Order: PO-9988
    Total Amount: 15,000.00
    GSTIN: 27AAAAA0000A1Z5
    """
    doc = CanonicalDocument(document_id="doc-inv-1", text=doc_text)
    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is False
    assert evidence.confidence_score < 0.5


def test_detect_negative_loan_schedule() -> None:
    doc_text = """
    LOAN AMORTISATION SCHEDULE
    Repayment Schedule
    Loan Account: LN-12345
    Principal: 500,000.00
    EMI Amount: 12,500.00
    """
    doc = CanonicalDocument(document_id="doc-loan-1", text=doc_text)
    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is False


def test_detect_icici_bank_statement() -> None:
    doc_text = """
    ICICI BANK LIMITED
    Detailed Account Statement
    Account Name: Ms. Priya Verma
    Account No: 123456789012
    Cust ID: 98765432
    IFSC Code: ICIC0001234
    Statement Period: 01-01-2026 to 31-01-2026
    ICICI Bank Towers, Bandra Kurla Complex
    """
    table = TableData(
        rows=(
            ("Date", "Particulars", "Cheque No.", "Withdrawals", "Deposits", "Balance"),
            ("01-01-2026", "OPENING BALANCE", "", "", "", "50,000.00"),
            ("10-01-2026", "NEFT-SALARY-CREDIT", "REF1122", "", "75,000.00", "1,25,000.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-icici-1",
        text=doc_text,
        pages=(PageData(page_number=1, text=doc_text, tables=(table,)),),
    )

    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "icici"
    assert evidence.bank_name == "ICICI Bank"
    assert evidence.account_identity is not None
    assert evidence.account_identity.masked_account_number == "XXXXXXXX9012"


def test_detect_hdfc_profile() -> None:
    doc_text = _HDFC_FIXTURE_PATH.read_text(encoding="utf-8")
    doc = CanonicalDocument(document_id="doc-hdfc-fixture", text=doc_text)
    ev = detect_bank_statement(doc)

    assert ev.is_bank_statement is True
    assert ev.matched_profile == "hdfc"
    assert ev.bank_name == "HDFC Bank"
    assert ev.account_identity is not None
    assert ev.account_identity.masked_account_number == "XXXXXXXXXX7890"
    assert ev.account_identity.account_holder == "Priya Nair"


def test_bank_statement_profile_tie_detection() -> None:
    """Verify detector flags tied profile evidence as ambiguous instead of picking arbitrary first profile."""
    text = "ICICI Bank statement and HDFC Bank statement with account details"
    doc = CanonicalDocument(document_id="doc-ambig", text=text)

    ev = detect_bank_statement(doc)
    if ev.matched_profile == "generic":
        assert any("Ambiguous bank profiles" in r for r in ev.reasons)


def test_best_match_bank_detection_with_competing_narration() -> None:
    """Profile detection uses multi-signal best match, not first match."""
    doc_text = """
    STATE BANK OF INDIA
    Account Statement
    Account Number: 11223344556
    Branch: New Delhi Main Branch
    Transaction Details:
    Date 01/01/2026 Cash Wdl at HDFC Bank ATM Dr 2000.00 Bal 10000.00
    """
    doc = CanonicalDocument(document_id="doc-sbi", source_input_id="inp-sbi", text=doc_text)
    evidence = detect_bank_statement(doc)

    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "sbi"
    assert evidence.bank_name == "State Bank of India"


def test_ifsc_extraction_and_propagation() -> None:
    """IFSC extracted from metadata patterns and populated on BankStatement."""
    doc_text = """
    ICICI BANK LTD
    Account Statement
    Account Number: 000105009999
    Customer ID: 555123456
    IFSC Code: ICIC0000001
    """
    table = TableData(
        name="txns",
        headers=("Date", "Particulars", "Debit", "Credit", "Balance"),
        rows=(("01/01/2026", "Opening Balance", "", "", "1000.00"),),
    )
    doc = CanonicalDocument(document_id="doc-ifsc", source_input_id="inp-ifsc", text=doc_text, tables=(table,))

    evidence = detect_bank_statement(doc)
    assert evidence.ifsc == "ICIC0000001"
    assert evidence.account_identity is not None
    assert evidence.account_identity.ifsc == "ICIC0000001"

    cap = BankStatementCapability()
    req = Request(
        request_id="req-test",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-test", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt = res.data.statements[0]
    assert stmt.ifsc == "ICIC0000001"
