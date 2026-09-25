"""Tests for Bank Statement and Profile Detection."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, PageData, Request, Result, TableData
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.detector import detect_bank_statement as _orig_detect

_HDFC_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hdfc_statement.csv"
_FIXTURE_BANKS_DIR = Path(__file__).parent / "fixtures" / "banks"


def detect_bank_statement(
    document: CanonicalDocument,
    banks_dir: Path | None = None,
    profiles: Sequence[dict[str, Any]] | None = None,
):
    target_banks = banks_dir if banks_dir is not None else _FIXTURE_BANKS_DIR
    return _orig_detect(document, banks_dir=target_banks, profiles=profiles)


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

    cap = BankStatementCapability(banks_dir=_FIXTURE_BANKS_DIR)
    req = Request(
        request_id="req-test",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-test", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt = res.data.statements[0]
    assert stmt.ifsc == "ICIC0000001"


def test_detect_axis_bank_statement() -> None:
    doc_text = """
    AXIS BANK
    Account Statement
    Account Number: 912010012345678
    Cust ID: 123456789
    IFSC: UTIB0000123
    Statement Period: 01-01-2026 to 31-01-2026
    """
    table = TableData(
        rows=(
            ("Tran Date", "Particulars", "Chq No", "Debit", "Credit", "Balance"),
            ("01-01-2026", "Opening Balance", "", "", "", "50,000.00"),
            ("05-01-2026", "NEFT OUT", "123456", "1,500.00", "", "48,500.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-axis",
        text=doc_text,
        pages=(PageData(page_number=1, text=doc_text, tables=(table,)),),
    )
    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "axis"
    assert evidence.bank_name == "Axis Bank"
    assert evidence.account_identity is not None
    assert evidence.account_identity.ifsc == "UTIB0000123"


def test_detect_kotak_bank_statement() -> None:
    doc_text = """
    KOTAK MAHINDRA BANK
    Account Statement
    Account Number: 1234567890
    CRN: 12345678
    IFSC Code: KKBK0000123
    """
    table = TableData(
        rows=(
            ("Date", "Narration", "Chq / Ref No.", "Withdrawal (Dr)", "Deposit (Cr)", "Balance"),
            ("01-Jan-2026", "OPENING BALANCE", "", "", "", "10,000.00"),
            ("02-Jan-2026", "UPI/SALARY", "REF999", "", "25,000.00", "35,000.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-kotak",
        text=doc_text,
        pages=(PageData(page_number=1, text=doc_text, tables=(table,)),),
    )
    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "kotak"
    assert evidence.bank_name == "Kotak Mahindra Bank"


def test_detect_pnb_bank_statement() -> None:
    doc_text = """
    PUNJAB NATIONAL BANK
    Account Statement
    Account Number: 1234000100012345
    IFSC: PUNB0123400
    """
    table = TableData(
        rows=(
            ("Txn Date", "Transaction Details", "Cheque No.", "Debit", "Credit", "Balance"),
            ("01/01/2026", "OPENING BAL", "", "", "", "20,000.00"),
            ("03/01/2026", "ATM WDL", "9988", "2,000.00", "", "18,000.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-pnb",
        text=doc_text,
        pages=(PageData(page_number=1, text=doc_text, tables=(table,)),),
    )
    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "pnb"
    assert evidence.bank_name == "Punjab National Bank"


def test_detect_bob_bank_statement() -> None:
    doc_text = """
    BANK OF BARODA
    Statement of Account
    Account Number: 12340100012345
    IFSC Code: BARB0KOLKAT
    """
    table = TableData(
        rows=(
            ("Date", "Narration", "Chq/Ref No", "Withdrawal", "Deposit", "Balance"),
            ("01-01-2026", "B/F BALANCE", "", "", "", "15,000.00"),
            ("04-01-2026", "DIVIDEND CR", "DIV01", "", "500.00", "15,500.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-bob",
        text=doc_text,
        pages=(PageData(page_number=1, text=doc_text, tables=(table,)),),
    )
    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "bob"
    assert evidence.bank_name == "Bank of Baroda"


def test_detect_canara_bank_statement() -> None:
    doc_text = """
    CANARA BANK
    Account Statement
    Account Number: 1234101012345
    IFSC: CNRB0001234
    """
    table = TableData(
        rows=(
            ("Txn Date", "Particulars", "Chq No", "Debit", "Credit", "Balance"),
            ("01-Jan-2026", "BALANCE B/F", "", "", "", "30,000.00"),
            ("06-Jan-2026", "POS PURCHASE", "1212", "1,200.00", "", "28,800.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-canara",
        text=doc_text,
        pages=(PageData(page_number=1, text=doc_text, tables=(table,)),),
    )
    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "canara"
    assert evidence.bank_name == "Canara Bank"


def test_generate_statement_id_deterministic() -> None:
    from sarathi.shakti.bank_statements.models import create_account_identity, generate_statement_id

    ident = create_account_identity("State Bank of India", "30123456789")
    id1 = generate_statement_id("State Bank of India", ident, "doc_sbi_123.pdf")
    id2 = generate_statement_id("State Bank of India", ident, "doc_sbi_123.pdf")
    assert id1 == id2
    assert id1.startswith("stmt_state_bank_of_india_acc_")
    assert "123_pdf" in id1

    # Without doc_id
    id_nodoc = generate_statement_id("HDFC Bank", ident)
    assert id_nodoc.startswith("stmt_hdfc_bank_acc_")


def test_transaction_id_auto_generation_and_provenance() -> None:
    from datetime import date
    from decimal import Decimal

    from sarathi.shakti.bank_statements.models import Transaction

    tx = Transaction(
        statement_id="stmt_sbi_acc_1234",
        sequence_id=42,
        transaction_date=date(2026, 1, 1),
        description="Merged description line 1 line 2",
        raw_description="Merged description line 1",
        raw_reference="UPI/123/original",
        reference_number="UPI123original",
        bank_name="State Bank of India",
        debit=Decimal("150.00"),
        source_input_id="input_doc_1",
        page_number=2,
        row_index=5,
    )
    assert tx.statement_id == "stmt_sbi_acc_1234"
    assert tx.transaction_id == "tx_stmt_sbi_acc_1234_00042"
    assert tx.raw_description == "Merged description line 1"
    assert tx.raw_reference == "UPI/123/original"
    assert tx.source_input_id == "input_doc_1"
    assert tx.page_number == 2
    assert tx.row_index == 5
