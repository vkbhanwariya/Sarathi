"""Tests for Bank Statement Identification vs Non-Bank Content."""

from pathlib import Path
import pytest

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
    assert evidence.account_number == "30123456789"
    assert evidence.account_holder == "Mr. Rahul Sharma"
    assert evidence.confidence_score >= 0.8


def test_detect_negative_non_bank_invoice() -> None:
    invoice_text = """
    TAX INVOICE
    Bill of Supply
    Invoice Number: INV-2026-001
    Purchase Order: PO-9988
    Customer: ABC Corp
    Total Amount Due: 15,000.00
    """
    table = TableData(
        rows=(
            ("Item No", "Description", "Quantity", "Unit Price", "Total"),
            ("1", "Office Chairs", "5", "3000.00", "15000.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-inv-1",
        text=invoice_text,
        pages=(PageData(page_number=1, text=invoice_text, tables=(table,)),),
    )

    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is False
    assert evidence.matched_profile is None
    assert evidence.confidence_score <= 0.3


def test_detect_negative_loan_schedule() -> None:
    loan_text = """
    Loan Amortisation Schedule
    Repayment Schedule
    Loan Account: LN-778899
    EMI Amount: 12,500.00
    """
    table = TableData(
        rows=(
            ("Installment No", "Due Date", "Principal", "Interest", "EMI", "Outstanding Principal"),
            ("1", "10/01/2026", "10000.00", "2500.00", "12500.00", "490000.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-loan-1",
        text=loan_text,
        pages=(PageData(page_number=1, text=loan_text, tables=(table,)),),
    )

    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is False
