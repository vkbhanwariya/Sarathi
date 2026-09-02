"""Tests for Bank Statement and Profile Detection."""

from sarathi.sankalpa import CanonicalDocument, PageData, TableData
from sarathi.shakti.bank_statements.detector import detect_bank_statement


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
