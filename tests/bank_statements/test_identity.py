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
    assert evidence.bank_name == "State Bank of India"
    assert evidence.account_identity is not None
    assert evidence.account_identity.masked_account_number == "XXXXXXX6789"
    assert evidence.account_identity.account_fingerprint is not None
    assert evidence.ifsc == "SBIN0001234"


def test_detect_unknown_bank_statement_without_bank_signals() -> None:
    doc_text = """
    Account Statement
    Account Name: Mr. Unknown Person
    Account Number: 998877665544
    Statement Period: 01/01/2026 to 31/01/2026
    """
    table = TableData(
        rows=(
            ("Date", "Particulars", "Debit", "Credit", "Balance"),
            ("01 Jan 2026", "OPENING BALANCE", "", "", "10,000.00"),
            ("05 Jan 2026", "TRANSFER", "500.00", "", "9,500.00"),
        )
    )
    doc = CanonicalDocument(
        document_id="doc-unknown-1",
        text=doc_text,
        pages=(PageData(page_number=1, text=doc_text, tables=(table,)),),
    )

    evidence = detect_bank_statement(doc)
    assert evidence.is_bank_statement is True
    assert evidence.matched_profile == "generic"
    assert evidence.bank_name == "Unknown Bank"
    assert any("Unknown Bank" in r for r in evidence.reasons)


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


def test_cross_bank_different_ifsc_not_deduplicated() -> None:
    """Two statements with Generic Bank and same account number but different IFSC must NOT be deduplicated."""
    from datetime import date
    from decimal import Decimal

    from sarathi.shakti.bank_statements.consolidator import consolidate_statements
    from sarathi.shakti.bank_statements.models import (
        BankStatement,
        Transaction,
        create_account_identity,
    )

    ident_sbi = create_account_identity("Generic Bank", "123456789", ifsc="SBIN0001234")
    ident_hdfc = create_account_identity("Generic Bank", "123456789", ifsc="HDFC0001234")

    assert ident_sbi.account_fingerprint != ident_hdfc.account_fingerprint, "Fingerprints must differ across distinct bank IFSCs"

    tx_sbi = Transaction(
        transaction_date=date(2026, 1, 5),
        description="Transfer to Vendor",
        bank_name="Generic Bank",
        debit=Decimal("500.00"),
        account_identity=ident_sbi,
        statement_id="stmt_sbi",
    )
    tx_hdfc = Transaction(
        transaction_date=date(2026, 1, 5),
        description="Transfer to Vendor",
        bank_name="Generic Bank",
        debit=Decimal("500.00"),
        account_identity=ident_hdfc,
        statement_id="stmt_hdfc",
    )

    stmt_sbi = BankStatement(
        bank_name="Generic Bank",
        bank_profile="generic",
        account_identity=ident_sbi,
        statement_id="stmt_sbi",
        ifsc="SBIN0001234",
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("500.00"),
        transactions=(tx_sbi,),
    )
    stmt_hdfc = BankStatement(
        bank_name="Generic Bank",
        bank_profile="generic",
        account_identity=ident_hdfc,
        statement_id="stmt_hdfc",
        ifsc="HDFC0001234",
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("500.00"),
        transactions=(tx_hdfc,),
    )

    result = consolidate_statements([stmt_sbi, stmt_hdfc])
    assert result.total_transactions == 2, f"Expected 2 transactions, got {result.total_transactions} (erroneously deduplicated across banks!)"
    assert len(result.transactions) == 2


def test_file_fingerprint_full_content_and_rename(tmp_path) -> None:
    """File fingerprinting must be content-based (rename-invariant) and detect 32-64KB differences."""
    from sarathi.mukha.intake import _compute_file_fingerprint

    # 1. Rename invariance
    content = b"Exact identical statement content across renames." * 50
    f1 = tmp_path / "original_statement.pdf"
    f2 = tmp_path / "renamed_copy.pdf"
    f1.write_bytes(content)
    f2.write_bytes(content)

    fp1 = _compute_file_fingerprint(f1, len(content))
    fp2 = _compute_file_fingerprint(f2, len(content))
    assert fp1 == fp2, "Fingerprint must not change when file is renamed"

    # 2. 48 KB file difference in the tail/middle (bytes 32K..48K)
    base_48k = bytearray(b"A" * 48000)
    diff_48k = bytearray(b"A" * 48000)
    diff_48k[35000:36000] = b"B" * 1000  # Differ strictly beyond 32KB

    f_48k_1 = tmp_path / "statement_a.pdf"
    f_48k_2 = tmp_path / "statement_b.pdf"
    f_48k_1.write_bytes(base_48k)
    f_48k_2.write_bytes(diff_48k)

    fp_48k_1 = _compute_file_fingerprint(f_48k_1, len(base_48k))
    fp_48k_2 = _compute_file_fingerprint(f_48k_2, len(diff_48k))
    assert fp_48k_1 != fp_48k_2, "Fingerprint must detect differences in 32K-64K files"


def test_document_fingerprint_sixth_row_difference() -> None:
    """Document fingerprinting must detect differences in the 6th row of a table."""
    from sarathi.shakti.bank_statements.capability import compute_document_fingerprint

    rows_base = [
        ("01/01/2026", "Txn 1", "100.00"),
        ("02/01/2026", "Txn 2", "200.00"),
        ("03/01/2026", "Txn 3", "300.00"),
        ("04/01/2026", "Txn 4", "400.00"),
        ("05/01/2026", "Txn 5", "500.00"),
        ("06/01/2026", "Txn 6", "600.00"),
    ]
    rows_modified = list(rows_base)
    rows_modified[5] = ("06/01/2026", "Txn 6 CHANGED", "999.00")

    doc1 = CanonicalDocument(
        document_id="d1",
        text="Statement with rows",
        tables=(TableData(name="t1", headers=("Date", "Desc", "Amt"), rows=tuple(rows_base)),),
    )
    doc2 = CanonicalDocument(
        document_id="d2",
        text="Statement with rows",
        tables=(TableData(name="t1", headers=("Date", "Desc", "Amt"), rows=tuple(rows_modified)),),
    )

    fp1 = compute_document_fingerprint(doc1)
    fp2 = compute_document_fingerprint(doc2)
    assert fp1 != fp2, "Document fingerprint must change when 6th transaction row changes"


def test_same_account_different_ifsc_shares_account_key() -> None:
    """Same account at same bank must have identical account_key whether IFSC is present or absent."""
    from sarathi.shakti.bank_statements.models import create_account_identity

    ident_with_ifsc = create_account_identity("State Bank of India", "30123456789", ifsc="SBIN0001234")
    ident_without_ifsc = create_account_identity("State Bank of India", "30123456789", ifsc=None)
    ident_diff_branch = create_account_identity("State Bank of India", "30123456789", ifsc="SBIN0009999")

    assert ident_with_ifsc.account_key == ident_without_ifsc.account_key, (
        f"account_key must not diverge when IFSC is omitted: {ident_with_ifsc.account_key} vs {ident_without_ifsc.account_key}"
    )
    assert ident_with_ifsc.account_key == ident_diff_branch.account_key, (
        f"account_key must not diverge across branches: {ident_with_ifsc.account_key} vs {ident_diff_branch.account_key}"
    )
    assert ident_with_ifsc.account_fingerprint == ident_without_ifsc.account_fingerprint
    assert ident_with_ifsc.identity_strength == "STRONG"


def test_account_number_delimiter_normalization() -> None:
    """Hyphens and whitespace in account numbers must normalize to the same account_key."""
    from sarathi.shakti.bank_statements.models import create_account_identity

    id1 = create_account_identity("HDFC Bank", "1234-5678-9012")
    id2 = create_account_identity("HDFC Bank", "1234 5678 9012")
    id3 = create_account_identity("HDFC Bank", "123456789012")

    assert id1.account_key == id2.account_key == id3.account_key, "Delimiters must be normalized in account_key"
    assert id1.masked_account_number == "XXXXXXXX9012"
    assert id2.masked_account_number == "XXXXXXXX9012"
    assert id3.masked_account_number == "XXXXXXXX9012"


def test_same_holder_two_accounts_same_bank_never_merged() -> None:
    """Two statements with same holder at same bank but no account number must NEVER be merged."""
    from datetime import date
    from decimal import Decimal

    from sarathi.shakti.bank_statements.consolidator import consolidate_statements
    from sarathi.shakti.bank_statements.models import BankStatement, Transaction, create_account_identity

    ident1 = create_account_identity("State Bank of India", None, account_holder="Mr. Rahul Sharma")
    ident2 = create_account_identity("State Bank of India", None, account_holder="Mr. Rahul Sharma")

    tx1 = Transaction(
        transaction_date=date(2026, 1, 5),
        description="Cash Deposit",
        bank_name="State Bank of India",
        credit=Decimal("5000.00"),
        account_identity=ident1,
        statement_id="stmt_1",
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 5),
        description="Cash Deposit",
        bank_name="State Bank of India",
        credit=Decimal("5000.00"),
        account_identity=ident2,
        statement_id="stmt_2",
    )

    stmt1 = BankStatement(
        statement_id="stmt_1",
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident1,
        account_holder="Mr. Rahul Sharma",
        transactions=(tx1,),
    )
    stmt2 = BankStatement(
        statement_id="stmt_2",
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident2,
        account_holder="Mr. Rahul Sharma",
        transactions=(tx2,),
    )

    from sarathi.shakti.bank_statements.consolidator import _account_group_key

    # Statements must not be grouped together solely on account_holder
    key1 = _account_group_key(stmt1)
    key2 = _account_group_key(stmt2)
    assert key1 != key2, f"Statements must not be grouped solely on holder name: got {key1} and {key2}"

    result = consolidate_statements([stmt1, stmt2])
    assert len(result.transactions) == 2
