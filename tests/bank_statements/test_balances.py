"""Tests for Bank Statement Balances, Invariants, and Reconciliation."""

import datetime
import io
from datetime import date
from decimal import Decimal

import polars as pl

from sarathi.shakti.bank_statements.consolidator import (
    build_parquet_artifact,
    consolidate_statements,
)
from sarathi.shakti.bank_statements.models import (
    BankStatement,
    Transaction,
    ValidationStatus,
    create_account_identity,
)
from sarathi.shakti.bank_statements.validator import validate_statement_balances


def test_valid_running_balance_continuity() -> None:
    ident = create_account_identity("State Bank of India", "30123456789")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Deposit",
        bank_name="State Bank of India",
        credit=Decimal("1000.00"),
        running_balance=Decimal("11000.00"),
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 2),
        description="Withdrawal",
        bank_name="State Bank of India",
        debit=Decimal("500.00"),
        running_balance=Decimal("10500.00"),
        account_identity=ident,
    )
    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("10500.00"),
        transactions=(tx1, tx2),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.VALID
    assert len(validated.issues) == 0


def test_running_balance_discontinuity_detected() -> None:
    ident = create_account_identity("State Bank of India", "30123456789")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Deposit",
        bank_name="State Bank of India",
        credit=Decimal("1000.00"),
        running_balance=Decimal("5000.00"),  # Expected 10000 + 1000 = 11000
        account_identity=ident,
    )
    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("5000.00"),
        transactions=(tx1,),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.WARNING
    assert any(i.code == "RUNNING_BALANCE_DISCONTINUITY" for i in validated.issues)


def test_statement_reconciliation_failure_detected() -> None:
    ident = create_account_identity("State Bank of India", "30123456789")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Deposit",
        bank_name="State Bank of India",
        credit=Decimal("1000.00"),
        running_balance=Decimal("11000.00"),
        account_identity=ident,
    )
    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("20000.00"),  # Expected 11000, mismatch!
        transactions=(tx1,),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.WARNING
    assert any(i.code == "RECONCILIATION_MISMATCH" for i in validated.issues)


def test_missing_opening_balance_inferred_from_closing_and_txns() -> None:
    ident = create_account_identity("HDFC Bank", "501001234567")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Salary",
        bank_name="HDFC Bank",
        credit=Decimal("50000.00"),
        running_balance=Decimal("75000.00"),
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 2),
        description="Rent",
        bank_name="HDFC Bank",
        debit=Decimal("15000.00"),
        running_balance=Decimal("60000.00"),
        account_identity=ident,
    )
    # opening_balance missing from scanned header card
    statement = BankStatement(
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        opening_balance=None,
        closing_balance=Decimal("60000.00"),
        transactions=(tx1, tx2),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.VALID
    assert validated.opening_balance == Decimal("25000.00")
    assert validated.closing_balance == Decimal("60000.00")
    assert len(validated.issues) == 0


def test_bidirectional_isolated_header_discontinuity_detection() -> None:
    ident = create_account_identity("ICICI Bank", "0011223344")
    # Row 1 and 2 are consistent with closing balance 15000
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Deposit",
        bank_name="ICICI Bank",
        credit=Decimal("5000.00"),
        running_balance=Decimal("15000.00"),
        account_identity=ident,
    )
    # Header opening balance was OCR misread as 5000 instead of 10000
    statement = BankStatement(
        bank_name="ICICI Bank",
        bank_profile="icici",
        account_identity=ident,
        opening_balance=Decimal("5000.00"),
        closing_balance=Decimal("15000.00"),
        transactions=(tx1,),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.WARNING
    disc_issue = next(i for i in validated.issues if i.code == "RUNNING_BALANCE_DISCONTINUITY")
    assert disc_issue.context is not None
    assert disc_issue.context.get("isolated_upstream_discontinuity") == "true"
    assert disc_issue.context.get("suspected_source") == "header_opening_balance_ocr"


def test_zero_opening_and_closing_balances_preserved() -> None:
    """Legitimate 0.00 opening and closing balances must not be discarded."""
    from pathlib import Path

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    cap = BankStatementCapability()
    table = TableData(
        name="txns",
        headers=("Date", "Narration", "Withdrawal", "Deposit", "Balance"),
        rows=(
            ("01/01/2026", "Opening Balance b/f", "", "", "0.00"),
            ("02/01/2026", "Direct Deposit", "", "5000.00", "5000.00"),
            ("03/01/2026", "Cash Withdrawal", "5000.00", "", "0.00"),
            ("31/01/2026", "Closing Balance c/f", "", "", "0.00"),
        ),
    )
    doc = CanonicalDocument(
        document_id="doc-zero-bal",
        source_input_id="inp-zero",
        text="State Bank of India Statement of Account Account Number: 12345678901",
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
    stmts = res.data.statements
    assert len(stmts) == 1
    stmt = stmts[0]
    assert stmt.opening_balance == Decimal("0.00")
    assert stmt.closing_balance == Decimal("0.00")


def test_debit_credit_inversion_detected_and_healed() -> None:
    """Proves validate_statement_balances detects swapped debit/credit columns and restores continuity."""
    ident = create_account_identity("State Bank of India", "30123456789")
    # Columns were inverted: Deposits entered in debit, withdrawals entered in credit
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Client Remittance (Inverted to Debit)",
        bank_name="State Bank of India",
        debit=Decimal("2000.00"),
        credit=None,
        running_balance=Decimal("12000.00"),
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 2),
        description="Office Expense (Inverted to Credit)",
        bank_name="State Bank of India",
        debit=None,
        credit=Decimal("1000.00"),
        running_balance=Decimal("11000.00"),
        account_identity=ident,
    )
    tx3 = Transaction(
        transaction_date=date(2026, 1, 3),
        description="Customer Invoice Payment (Inverted to Debit)",
        bank_name="State Bank of India",
        debit=Decimal("5000.00"),
        credit=None,
        running_balance=Decimal("16000.00"),
        account_identity=ident,
    )

    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("16000.00"),
        transactions=(tx1, tx2, tx3),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.WARNING
    assert any(i.code == "DEBIT_CREDIT_INVERSION_DETECTED" for i in validated.issues)
    assert not any(i.code == "RUNNING_BALANCE_DISCONTINUITY" for i in validated.issues)
    assert not any(i.code == "RECONCILIATION_MISMATCH" for i in validated.issues)

    # Verify that debits and credits were successfully swapped
    txns = validated.transactions
    assert txns[0].credit == Decimal("2000.00") and txns[0].debit is None
    assert txns[1].debit == Decimal("1000.00") and txns[1].credit is None
    assert txns[2].credit == Decimal("5000.00") and txns[2].debit is None


def test_empty_transactions_fails_closed_with_invalid_status() -> None:
    """Zero extracted transactions must result in INVALID status and ZERO_TRANSACTIONS_EXTRACTED issue."""
    ident = create_account_identity("State Bank of India", "30123456789")
    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("10000.00"),
        transactions=(),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.INVALID
    assert any(i.code == "ZERO_TRANSACTIONS_EXTRACTED" for i in validated.issues)


def test_parse_balance_amount_dr_cr_od() -> None:
    from sarathi.shakti.bank_statements.converter import parse_balance_amount

    assert parse_balance_amount("1,234.50 Dr") == Decimal("-1234.50")
    assert parse_balance_amount("1,234.50(Dr)") == Decimal("-1234.50")
    assert parse_balance_amount("500.00 OD") == Decimal("-500.00")
    assert parse_balance_amount("1,234.50 Cr") == Decimal("1234.50")
    assert parse_balance_amount("1,234.50") == Decimal("1234.50")
    assert parse_balance_amount("-1234.50") == Decimal("-1234.50")
    assert parse_balance_amount(None) is None
    assert parse_balance_amount("") is None


def test_metadata_pattern_extracts_negative_balance_with_minus_sign() -> None:
    """Opening Balance -100.00 and Closing Balance -200.00 must preserve minus signs."""
    import re

    import yaml

    from sarathi.shakti.bank_statements.converter import parse_balance_amount
    from sarathi.sutra import get_canonical_data_root

    common_yaml_path = get_canonical_data_root() / "banks" / "common.yaml"
    cfg = yaml.safe_load(common_yaml_path.read_text(encoding="utf-8"))
    patterns = cfg["metadata_patterns"]

    open_regex = re.compile(patterns["opening_balance"], re.IGNORECASE)
    close_regex = re.compile(patterns["closing_balance"], re.IGNORECASE)

    sample_text = """
    Opening Balance -100.00
    Closing Balance -200.00
    """
    m_open = open_regex.search(sample_text)
    assert m_open is not None, "Opening balance regex should match 'Opening Balance -100.00'"
    raw_open = m_open.group(1).strip()
    assert raw_open == "-100.00"
    assert parse_balance_amount(raw_open) == Decimal("-100.00")

    m_close = close_regex.search(sample_text)
    assert m_close is not None, "Closing balance regex should match 'Closing Balance -200.00'"
    raw_close = m_close.group(1).strip()
    assert raw_close == "-200.00"
    assert parse_balance_amount(raw_close) == Decimal("-200.00")


def test_multi_account_boundaries_not_shared() -> None:
    """In a multi-account document, Account B must not inherit Account A's boundary balances."""
    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, PageData, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    # Two tables with two different accounts and different boundary balances
    table_a = TableData(
        name="111122223333",
        headers=("Account No: 111122223333", "", "", "", "", ""),
        rows=(
            ("Date", "Description", "Debit", "Credit", "Balance"),
            ("01/01/2026", "OPENING BALANCE", "", "", "10000.00"),
            ("05/01/2026", "Deposit", "", "2000.00", "12000.00"),
            ("31/01/2026", "CLOSING BALANCE", "", "", "12000.00"),
        ),
    )
    table_b = TableData(
        name="444455556666",
        headers=("Account No: 444455556666", "", "", "", "", ""),
        rows=(
            ("Date", "Description", "Debit", "Credit", "Balance"),
            ("01/01/2026", "OPENING BALANCE", "", "", "50000.00"),
            ("10/01/2026", "Withdrawal", "2500.00", "", "47500.00"),
            ("31/01/2026", "CLOSING BALANCE", "", "", "47500.00"),
        ),
    )

    doc = CanonicalDocument(
        document_id="doc-multi-acc-1",
        source_input_id="input-multi-1",
        text="STATE BANK OF INDIA\nAccount Statement\nIFSC: SBIN0001234",
        pages=(
            PageData(page_number=1, text="Page 1 Account Statement", tables=(table_a,)),
            PageData(page_number=2, text="Page 2 Account Statement", tables=(table_b,)),
        ),
    )

    cap = BankStatementCapability()
    from pathlib import Path
    req = Request(
        request_id="req-1",
        requirement="bank_statements",
        inputs=(InputRef(input_id="input-multi-1", source_path=Path("multi.xlsx"), display_name="multi.xlsx", size_bytes=100),),
    )
    res = cap.execute(
        req,
        ExecutionContext("run-1", "req-1", "t-1", "s-1"),
        prior_result=Result(data=(doc,)),
    )

    statements = res.data.statements
    assert len(statements) == 2, f"Expected 2 statements for 2 accounts, got {len(statements)}"

    stmt_a = next(s for s in statements if s.account_identity.masked_account_number.endswith("3333"))
    stmt_b = next(s for s in statements if s.account_identity.masked_account_number.endswith("6666"))

    assert stmt_a.opening_balance == Decimal("10000.00"), f"Expected 10000.00, got {stmt_a.opening_balance}"
    assert stmt_a.closing_balance == Decimal("12000.00"), f"Expected 12000.00, got {stmt_a.closing_balance}"

    assert stmt_b.opening_balance == Decimal("50000.00"), f"Expected 50000.00, got {stmt_b.opening_balance}"
    assert stmt_b.closing_balance == Decimal("47500.00"), f"Expected 47500.00, got {stmt_b.closing_balance}"


def test_cross_statement_balance_discontinuity_and_period_gap_detection():
    """Verify cross-statement balance discontinuities and missing statement periods emit warnings."""
    ident = create_account_identity("SBI", "123456789012")
    # Statement 1: Jan 1 to Jan 31, closing 5000
    s1 = BankStatement(
        statement_id="s1",
        bank_name="SBI",
        bank_profile="sbi",
        account_identity=ident,
        statement_period_start=datetime.date(2025, 1, 1),
        statement_period_end=datetime.date(2025, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("5000.00"),
        transactions=(),
    )
    # Statement 2: Mar 15 to Mar 31, opening 6000 (gap in February, and balance jump 5000 -> 6000)
    s2 = BankStatement(
        statement_id="s2",
        bank_name="SBI",
        bank_profile="sbi",
        account_identity=ident,
        statement_period_start=datetime.date(2025, 3, 15),
        statement_period_end=datetime.date(2025, 3, 31),
        opening_balance=Decimal("6000.00"),
        closing_balance=Decimal("9000.00"),
        transactions=(),
    )

    res = consolidate_statements((s1, s2))
    issue_codes = {i.code for i in res.issues}
    assert "CROSS_STATEMENT_BALANCE_DISCONTINUITY" in issue_codes
    assert "MISSING_STATEMENT_PERIOD" in issue_codes


def test_reverse_order_same_day_transactions_no_false_discontinuity():
    """Verify that reverse-order transactions on the same date with multiple transactions do not produce false warnings."""
    tx1 = Transaction(
        transaction_date=datetime.date(2025, 1, 10),
        transaction_time=datetime.time(16, 0),
        description="Evening Tx",
        bank_name="SBI",
        debit=Decimal("100.00"),
        running_balance=Decimal("900.00"),
    )
    tx2 = Transaction(
        transaction_date=datetime.date(2025, 1, 10),
        transaction_time=datetime.time(10, 0),
        description="Morning Tx",
        bank_name="SBI",
        credit=Decimal("500.00"),
        running_balance=Decimal("1000.00"),
    )

    # In reverse-order statement: tx1 (evening) appears before tx2 (morning)
    stmt = BankStatement(
        bank_name="SBI",
        bank_profile="sbi",
        opening_balance=Decimal("500.00"),
        closing_balance=Decimal("900.00"),
        transactions=(tx1, tx2),
    )

    validated = validate_statement_balances(stmt)
    assert validated.status == ValidationStatus.VALID
    assert not any(i.code == "RUNNING_BALANCE_DISCONTINUITY" for i in validated.issues)


def test_parquet_eod_balance_is_end_of_day_not_intraday():
    """Verify Parquet export populates eod_balance with true end-of-day balance across all rows of that date."""
    ident = create_account_identity("SBI", "123456789012")
    tx1 = Transaction(
        transaction_date=datetime.date(2025, 1, 10),
        transaction_time=datetime.time(9, 0),
        description="Morning Tx",
        bank_name="SBI",
        credit=Decimal("500.00"),
        running_balance=Decimal("1500.00"),
        statement_id="s1",
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=datetime.date(2025, 1, 10),
        transaction_time=datetime.time(17, 0),
        description="Evening Tx",
        bank_name="SBI",
        debit=Decimal("200.00"),
        running_balance=Decimal("1300.00"),
        statement_id="s1",
        account_identity=ident,
    )

    stmt = BankStatement(
        statement_id="s1",
        bank_name="SBI",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1300.00"),
        transactions=(tx1, tx2),
    )

    consolidation = consolidate_statements((stmt,))
    payload = build_parquet_artifact(consolidation)
    df = pl.read_parquet(io.BytesIO(payload.content))

    assert "eod_balance" in df.columns
    # Both transactions on Jan 10 must have eod_balance = 1300.00 (the end-of-day balance, not 1500.00)
    assert df["eod_balance"][0] == Decimal("1300.00")
    assert df["eod_balance"][1] == Decimal("1300.00")


def test_eod_balance_weak_identities_and_reverse_order() -> None:
    """Verify EOD balances isolate weak/unverified identities and handle reverse-order statements."""
    # Case 1: Two different banks with weak/no account keys
    tx_b1 = Transaction(
        transaction_date=datetime.date(2025, 1, 10),
        description="Bank A Tx",
        bank_name="Bank Alpha",
        statement_id="stmt_alpha",
        running_balance=Decimal("100.00"),
    )
    tx_b2 = Transaction(
        transaction_date=datetime.date(2025, 1, 10),
        description="Bank B Tx",
        bank_name="Bank Beta",
        statement_id="stmt_beta",
        running_balance=Decimal("200.00"),
    )
    s1 = BankStatement(statement_id="stmt_alpha", bank_name="Bank Alpha", bank_profile="generic", transactions=(tx_b1,))
    s2 = BankStatement(statement_id="stmt_beta", bank_name="Bank Beta", bank_profile="generic", transactions=(tx_b2,))
    c_res = consolidate_statements((s1, s2))

    payload = build_parquet_artifact(c_res)
    df = pl.read_parquet(io.BytesIO(payload.content))
    b1_eod = df.filter(pl.col("bank_name") == "Bank Alpha")["eod_balance"][0]
    b2_eod = df.filter(pl.col("bank_name") == "Bank Beta")["eod_balance"][0]
    assert b1_eod == Decimal("100.00")
    assert b2_eod == Decimal("200.00")

    # Case 2: Reverse-order statement ending at 70 (row 1 is evening 70, row 2 is morning 90)
    tx_ev = Transaction(
        transaction_date=datetime.date(2025, 1, 15),
        transaction_time=datetime.time(18, 0),
        description="Evening Tx",
        bank_name="HDFC Bank",
        statement_id="stmt_rev",
        running_balance=Decimal("70.00"),
    )
    tx_mo = Transaction(
        transaction_date=datetime.date(2025, 1, 15),
        transaction_time=datetime.time(9, 0),
        description="Morning Tx",
        bank_name="HDFC Bank",
        statement_id="stmt_rev",
        running_balance=Decimal("90.00"),
    )
    # Statement presented in reverse order (evening first)
    s_rev = BankStatement(
        statement_id="stmt_rev",
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        transactions=(tx_ev, tx_mo),
        metadata={"is_reverse": True},
    )
    c_rev = consolidate_statements((s_rev,))
    payload_rev = build_parquet_artifact(c_rev)
    df_rev = pl.read_parquet(io.BytesIO(payload_rev.content))
    # EOD balance must be the chronologically last transaction: 70.00!
    assert df_rev["eod_balance"][0] == Decimal("70.00")
    assert df_rev["eod_balance"][1] == Decimal("70.00")


def test_overlapping_statements_do_not_generate_false_continuity_warning() -> None:
    """Overlapping or duplicate statements must not trigger CROSS_STATEMENT_BALANCE_DISCONTINUITY."""
    ident = create_account_identity("HDFC Bank", "50100987654321")
    tx1 = Transaction(
        transaction_date=datetime.date(2025, 1, 15),
        description="Salary",
        bank_name="HDFC Bank",
        credit=Decimal("500.00"),
        running_balance=Decimal("1000.00"),
        statement_id="s1",
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=datetime.date(2025, 1, 15),
        description="Salary",
        bank_name="HDFC Bank",
        credit=Decimal("500.00"),
        running_balance=Decimal("1000.00"),
        statement_id="s2",
        account_identity=ident,
    )

    s1 = BankStatement(
        statement_id="s1",
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        statement_period_start=datetime.date(2025, 1, 1),
        statement_period_end=datetime.date(2025, 1, 31),
        opening_balance=Decimal("500.00"),
        closing_balance=Decimal("1000.00"),
        transactions=(tx1,),
    )
    s2 = BankStatement(
        statement_id="s2",
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        statement_period_start=datetime.date(2025, 1, 1),
        statement_period_end=datetime.date(2025, 1, 31),
        opening_balance=Decimal("500.00"),
        closing_balance=Decimal("1000.00"),
        transactions=(tx2,),
    )

    res = consolidate_statements((s1, s2))
    assert not any(iss.code == "CROSS_STATEMENT_BALANCE_DISCONTINUITY" for iss in res.issues)


def test_missing_period_dates_balance_gap_warning() -> None:
    """Two statements with missing period start dates and a closing/opening gap must emit CROSS_STATEMENT_BALANCE_DISCONTINUITY."""
    ident = create_account_identity("State Bank of India", "123456789012")
    # Both statements lack statement_period_start and statement_period_end
    s1 = BankStatement(
        statement_id="stmt_part1",
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("50.00"),
        closing_balance=Decimal("100.00"),
        transactions=(
            Transaction(
                transaction_date=datetime.date(2025, 1, 5),
                description="Jan 5 Tx",
                bank_name="State Bank of India",
                credit=Decimal("50.00"),
                running_balance=Decimal("100.00"),
                statement_id="stmt_part1",
                account_identity=ident,
            ),
        ),
    )
    s2 = BankStatement(
        statement_id="stmt_part2",
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("200.00"),  # Jump from 100 to 200!
        closing_balance=Decimal("250.00"),
        transactions=(
            Transaction(
                transaction_date=datetime.date(2025, 1, 20),
                description="Jan 20 Tx",
                bank_name="State Bank of India",
                credit=Decimal("50.00"),
                running_balance=Decimal("250.00"),
                statement_id="stmt_part2",
                account_identity=ident,
            ),
        ),
    )

    res = consolidate_statements((s1, s2))
    assert any(
        iss.code == "CROSS_STATEMENT_BALANCE_DISCONTINUITY"
        for iss in res.issues
    ), "Missing period dates must not suppress CROSS_STATEMENT_BALANCE_DISCONTINUITY warning"


def test_eod_balance_noon_transaction_in_later_file_does_not_overwrite_evening() -> None:
    """A noon transaction in a later file must not overwrite an 18:00 transaction from an earlier file."""
    ident = create_account_identity("HDFC Bank", "50100112233445")
    # File 0: evening transaction at 18:00 (closing balance 500)
    tx_file0 = Transaction(
        transaction_date=datetime.date(2025, 1, 15),
        transaction_time=datetime.time(18, 0),
        description="Evening Tx File 0",
        bank_name="HDFC Bank",
        source_input_id="file_0.csv",
        statement_id="stmt_f0",
        running_balance=Decimal("500.00"),
        account_identity=ident,
    )
    # File 1: noon transaction at 12:00 (running balance 400)
    tx_file1 = Transaction(
        transaction_date=datetime.date(2025, 1, 15),
        transaction_time=datetime.time(12, 0),
        description="Noon Tx File 1",
        bank_name="HDFC Bank",
        source_input_id="file_1.csv",
        statement_id="stmt_f1",
        running_balance=Decimal("400.00"),
        account_identity=ident,
    )

    s0 = BankStatement(
        statement_id="stmt_f0",
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        transactions=(tx_file0,),
        metadata={"source_input_id": "file_0.csv"},
    )
    s1 = BankStatement(
        statement_id="stmt_f1",
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        transactions=(tx_file1,),
        metadata={"source_input_id": "file_1.csv"},
    )

    res = consolidate_statements((s0, s1))
    payload = build_parquet_artifact(res)
    df = pl.read_parquet(io.BytesIO(payload.content))

    # True EOD balance on Jan 15 must be 500.00 (from 18:00), not overwritten by 400.00 (12:00)
    for eod in df["eod_balance"]:
        assert eod == Decimal("500.00")


def test_eod_balance_reverse_statement_spanning_two_pages() -> None:
    """A reverse-order statement spanning two pages must export the chronologically latest balance (page 1) not page 2."""
    ident = create_account_identity("ICICI Bank", "123401500999")
    # Page 1: evening transaction at top of document (closing balance 70)
    tx_p1 = Transaction(
        transaction_date=datetime.date(2025, 1, 15),
        description="Evening Tx Page 1",
        bank_name="ICICI Bank",
        statement_id="stmt_icici",
        page_number=1,
        row_index=1,
        running_balance=Decimal("70.00"),
        account_identity=ident,
    )
    # Page 2: morning transaction on later page (running balance 90)
    tx_p2 = Transaction(
        transaction_date=datetime.date(2025, 1, 15),
        description="Morning Tx Page 2",
        bank_name="ICICI Bank",
        statement_id="stmt_icici",
        page_number=2,
        row_index=1,
        running_balance=Decimal("90.00"),
        account_identity=ident,
    )

    stmt = BankStatement(
        statement_id="stmt_icici",
        bank_name="ICICI Bank",
        bank_profile="icici",
        account_identity=ident,
        transactions=(tx_p1, tx_p2),
        metadata={"is_reverse": True},
    )

    res = consolidate_statements((stmt,))
    payload = build_parquet_artifact(res)
    df = pl.read_parquet(io.BytesIO(payload.content))

    # EOD balance must be 70.00, not 90.00
    assert df["eod_balance"][0] == Decimal("70.00")
    assert df["eod_balance"][1] == Decimal("70.00")


def test_unknown_bank_separate_statements_eod_isolation() -> None:
    """Two separate statements from an unknown bank must maintain isolated EOD balances in Parquet."""
    ident1 = create_account_identity("Unknown Bank", "998877665544")
    ident2 = create_account_identity("Unknown Bank", "998877665544")

    tx1 = Transaction(
        transaction_date=datetime.date(2025, 1, 10),
        description="Stmt 1 Tx",
        bank_name="Unknown Bank",
        statement_id="stmt_unk_1",
        running_balance=Decimal("100.00"),
        account_identity=ident1,
    )
    tx2 = Transaction(
        transaction_date=datetime.date(2025, 1, 10),
        description="Stmt 2 Tx",
        bank_name="Unknown Bank",
        statement_id="stmt_unk_2",
        running_balance=Decimal("200.00"),
        account_identity=ident2,
    )

    s1 = BankStatement(statement_id="stmt_unk_1", bank_name="Unknown Bank", bank_profile="generic", account_identity=ident1, transactions=(tx1,))
    s2 = BankStatement(statement_id="stmt_unk_2", bank_name="Unknown Bank", bank_profile="generic", account_identity=ident2, transactions=(tx2,))

    res = consolidate_statements((s1, s2))
    payload = build_parquet_artifact(res)
    df = pl.read_parquet(io.BytesIO(payload.content))

    row_s1 = df.filter(pl.col("statement_id") == "stmt_unk_1")
    row_s2 = df.filter(pl.col("statement_id") == "stmt_unk_2")

    assert row_s1["eod_balance"][0] == Decimal("100.00")
    assert row_s2["eod_balance"][0] == Decimal("200.00")
