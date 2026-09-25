"""Tests for Bank Statement and Profile Detection."""

from pathlib import Path

from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, PageData, Request, Result, TableData
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.detector import detect_bank_statement


def test_detect_generic_bank_statement() -> None:
    doc_text = """
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
    assert evidence.matched_profile == "generic"
    assert evidence.bank_name == "Generic Bank"
    assert evidence.account_identity is not None
    assert evidence.account_identity.masked_account_number == "XXXXXXX6789"
    assert evidence.account_identity.account_fingerprint is not None
    assert evidence.ifsc == "SBIN0001234"


def test_detect_with_specific_profile() -> None:
    sbi_profile = {
        "profile_id": "sbi_pdf_fmt1",
        "bank_name": "State Bank of India",
        "container_format": "pdf",
        "identification_keywords": ["STATE BANK OF INDIA", "Account Statement"],
        "metadata_patterns": {
            "account_number": r"Account\s*Number:\s*(\d+)",
            "ifsc": r"IFSC:\s*([A-Z0-9]+)",
        },
    }
    doc_text = """
    STATE BANK OF INDIA
    Account Statement
    Account Name: Mr. Rahul Sharma
    Account Number: 30123456789
    IFSC: SBIN0001234
    """
    table = TableData(
        rows=(
            ("Txn Date", "Value Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"),
            ("01 Jan 2026", "01 Jan 2026", "OPENING BALANCE", "", "", "", "25,000.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-sbi-pdf",
        detected_type="pdf",
        text=doc_text,
        pages=(PageData(page_number=1, text=doc_text, tables=(table,)),),
    )

    evidence = detect_bank_statement(doc, profiles=[sbi_profile])
    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "sbi_pdf_fmt1"
    assert evidence.bank_name == "State Bank of India"
    assert evidence.account_identity is not None
    assert evidence.account_identity.masked_account_number == "XXXXXXX6789"
    assert evidence.account_identity.ifsc == "SBIN0001234"


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


def test_bank_statement_profile_tie_detection() -> None:
    """Verify detector flags tied profile evidence as ambiguous instead of picking arbitrary first profile."""
    prof_a = {
        "profile_id": "bank_a_pdf_fmt1",
        "bank_name": "Bank Alpha",
        "container_format": "pdf",
        "identification_keywords": ["Alpha Bank Statement"],
    }
    prof_b = {
        "profile_id": "bank_b_pdf_fmt1",
        "bank_name": "Bank Beta",
        "container_format": "pdf",
        "identification_keywords": ["Beta Bank Statement"],
    }
    text = "Alpha Bank Statement and Beta Bank Statement with account details"
    doc = CanonicalDocument(document_id="doc-ambig", detected_type="pdf", text=text)

    ev = detect_bank_statement(doc, profiles=[prof_a, prof_b])
    if ev.matched_profile == "generic":
        assert any("Ambiguous bank profiles" in r for r in ev.reasons)


def test_best_match_bank_detection_with_competing_narration() -> None:
    """Profile detection uses multi-signal best match, not first match."""
    sbi_profile = {
        "profile_id": "sbi_pdf_fmt1",
        "bank_name": "State Bank of India",
        "identification_keywords": ["STATE BANK OF INDIA"],
        "metadata_patterns": {
            "account_number": r"Account\s*Number:\s*(\d+)",
        },
    }
    hdfc_profile = {
        "profile_id": "hdfc_pdf_fmt1",
        "bank_name": "HDFC Bank",
        "identification_keywords": ["HDFC Bank"],
    }
    doc_text = """
    STATE BANK OF INDIA
    Account Statement
    Account Number: 11223344556
    Branch: New Delhi Main Branch
    Transaction Details:
    Date 01/01/2026 Cash Wdl at HDFC Bank ATM Dr 2000.00 Bal 10000.00
    """
    doc = CanonicalDocument(document_id="doc-sbi", source_input_id="inp-sbi", text=doc_text)
    evidence = detect_bank_statement(doc, profiles=[sbi_profile, hdfc_profile])

    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "sbi_pdf_fmt1"
    assert evidence.bank_name == "State Bank of India"


def test_ifsc_extraction_and_propagation() -> None:
    """IFSC extracted from metadata patterns and populated on BankStatement."""
    doc_text = """
    ACCOUNT STATEMENT
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
