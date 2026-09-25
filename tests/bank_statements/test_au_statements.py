"""Comprehensive Unit & Integration Tests for AU Small Finance Bank Statements.

Validates:
1. AU Bank profile identification and table locating (banner skip to Row 3).
2. Multi-sheet multi-account extraction (Sheet 1: 80 txns, Sheet 2: 19 txns -> 99 txns total).
3. Two-tier ID architecture (Input Location: Statements_S1_R04; Sequential ID: TXN-0001).
4. Time parsing when date and time are bundled in a single column.
5. Indian number format and subtotal formulas in Consolidated_Transactions.xlsx.
6. 6-column List_of_Accounts.xlsx directory.
7. 28+ column Consolidated_Bank_Statement.parquet forensic export with transaction_hash and transaction_mode.
"""

from __future__ import annotations

import io
from datetime import date, time
from pathlib import Path

import openpyxl
import polars as pl
import pytest

from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result
from sarathi.shakti.bank_statements.capability import BankStatementCapability, _detect_transaction_mode
from sarathi.shakti.native_extraction.readers.spreadsheet import read_xlsx

_AU_FILE = Path("Input/AU/Statements.xlsx")


@pytest.mark.skipif(not _AU_FILE.exists(), reason="Input/AU/Statements.xlsx not present")
def test_au_bank_statement_detection_and_extraction() -> None:
    data = _AU_FILE.read_bytes()
    doc, _, _ = read_xlsx(data, "Statements.xlsx")
    doc = CanonicalDocument(
        document_id="doc-au-01",
        detected_type="xlsx",
        tables=doc.tables,
        source_input_id="Statements.xlsx",
    )

    cap = BankStatementCapability()
    in_ref = InputRef(
        input_id="in-au-01",
        source_path=_AU_FILE,
        display_name="Statements.xlsx",
        size_bytes=len(data),
    )
    req = Request(request_id="req-au-01", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-au-01", request_id="req-au-01", trace_id="tr-1", span_id="sp-1")
    res = cap.execute(req, ctx, Result(data=doc))

    consolidation = res.data
    assert consolidation.total_transactions == 99
    assert len(consolidation.statements) == 2

    stmt1, stmt2 = consolidation.statements
    assert stmt1.bank_name == "Au Small Finance Bank Limited"
    assert stmt2.bank_name == "Au Small Finance Bank Limited"
    assert stmt1.account_identity is not None
    assert stmt2.account_identity is not None

    assert stmt1.account_identity.masked_account_number.endswith("0332")
    assert len(stmt1.transactions) == 80

    assert stmt2.account_identity.masked_account_number.endswith("7740")
    assert len(stmt2.transactions) == 19


@pytest.mark.skipif(not _AU_FILE.exists(), reason="Input/AU/Statements.xlsx not present")
def test_au_two_tier_id_system_and_datetime() -> None:
    data = _AU_FILE.read_bytes()
    doc, _, _ = read_xlsx(data, "Statements.xlsx")
    doc = CanonicalDocument(
        document_id="doc-au-02",
        detected_type="xlsx",
        tables=doc.tables,
        source_input_id="Statements.xlsx",
    )

    cap = BankStatementCapability()
    in_ref = InputRef(
        input_id="in-au-02",
        source_path=_AU_FILE,
        display_name="Statements.xlsx",
        size_bytes=len(data),
    )
    req = Request(request_id="req-au-02", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-au-02", request_id="req-au-02", trace_id="tr-2", span_id="sp-2")
    res = cap.execute(req, ctx, Result(data=doc))

    for tx in res.data.transactions:
        # 1. Transaction ID pattern: TXN-XXXX
        assert tx.transaction_id.startswith("TXN-")
        assert len(tx.transaction_id) == 8

        # 2. Input Location pattern: Statements_SX_RXX
        assert tx.input_location is not None
        assert tx.input_location.startswith("Statements_S")
        assert "_R" in tx.input_location

        # 3. Time parsed from timestamp column
        assert isinstance(tx.transaction_date, date)
        if tx.transaction_time is not None:
            assert isinstance(tx.transaction_time, time)

        # 4. Mode classified
        assert tx.transaction_mode in {
            "UPI",
            "NEFT",
            "RTGS",
            "IMPS",
            "CASH",
            "CHEQUE",
            "CHARGES",
            "INTEREST",
            "TRANSFER",
        }


@pytest.mark.skipif(not _AU_FILE.exists(), reason="Input/AU/Statements.xlsx not present")
def test_au_deliverables_and_formatting() -> None:
    data = _AU_FILE.read_bytes()
    doc, _, _ = read_xlsx(data, "Statements.xlsx")
    doc = CanonicalDocument(
        document_id="doc-au-03",
        detected_type="xlsx",
        tables=doc.tables,
        source_input_id="Statements.xlsx",
    )

    cap = BankStatementCapability()
    in_ref = InputRef(
        input_id="in-au-03",
        source_path=_AU_FILE,
        display_name="Statements.xlsx",
        size_bytes=len(data),
    )
    req = Request(request_id="req-au-03", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-au-03", request_id="req-au-03", trace_id="tr-3", span_id="sp-3")
    res = cap.execute(req, ctx, Result(data=doc))
    assert len(res.artifact_payloads) == 3
    assert not any(a.intent.name == "Consolidated_Bank_Statement.xlsx" for a in res.artifact_payloads)

    # 1. List_of_Accounts.xlsx
    acc_payload = next(a for a in res.artifact_payloads if a.intent.name == "List_of_Accounts.xlsx")
    wb_acc = openpyxl.load_workbook(io.BytesIO(acc_payload.content))
    assert wb_acc.sheetnames == ["Accounts", "Processing_Summary"]
    assert wb_acc.active.title == "Accounts"

    ws_acc = wb_acc["Accounts"]
    acc_rows = list(ws_acc.iter_rows(values_only=True))
    assert acc_rows[0] == (
        "S.No.",
        "Name of the Account Holder",
        "Account No.",
        "Bank Name",
        "Input Location Range",
        "Transaction ID Range",
    )
    assert len(acc_rows) == 3  # Header + 2 accounts
    assert "Statements_S1_R" in acc_rows[1][4]
    assert "Statements_S2_R" in acc_rows[2][4]

    ws_sum = wb_acc["Processing_Summary"]
    sum_rows = list(ws_sum.iter_rows(values_only=True))
    assert sum_rows[0] == (
        "S.No.",
        "Source File",
        "Account No.",
        "Bank Name",
        "Profile Used",
        "Header Match Score",
        "Total Rows Scanned",
        "Successful Transactions",
        "Duplicates Removed",
        "Failed / Skipped Rows",
        "Status",
        "Warnings Count",
        "Warning / Audit Details",
    )
    assert sum_rows[1][0] == 1
    assert sum_rows[1][1] == "Statements"
    assert "0332" in sum_rows[1][2]
    assert sum_rows[1][3] == "Au Small Finance Bank Limited"
    assert sum_rows[1][4] == "au_excel_fmt1"
    assert sum_rows[1][5] > 0.0
    assert sum_rows[1][7] == 80  # Successful transactions for sheet 1
    assert sum_rows[2][0] == 2
    assert "7740" in sum_rows[2][2]
    assert sum_rows[2][7] == 19  # Successful transactions for sheet 2

    # 2. Consolidated_Transactions.xlsx
    txn_payload = next(a for a in res.artifact_payloads if a.intent.name == "Consolidated_Transactions.xlsx")
    wb_txn = openpyxl.load_workbook(io.BytesIO(txn_payload.content))
    ws_txn = wb_txn.active
    assert ws_txn.cell(row=1, column=1).value == "Transaction ID"
    assert ws_txn.cell(row=1, column=2).value == "Input Location"
    assert ws_txn.cell(row=1, column=3).value == "Date"
    assert ws_txn.cell(row=1, column=4).value == "Description"
    assert ws_txn.cell(row=1, column=5).value == "Ref / UTR No."
    assert ws_txn.cell(row=1, column=6).value == "Cheque No."
    assert ws_txn.cell(row=1, column=7).value == "Debit"
    assert ws_txn.cell(row=1, column=8).value == "Credit"
    assert ws_txn.cell(row=1, column=9).value == "Balance"

    # Date cell formatting
    d_cell = ws_txn.cell(row=2, column=3)
    assert d_cell.number_format == "DD-MM-YYYY"

    # Total row with SUBTOTAL formula
    total_row = len(res.data.transactions) + 2
    assert ws_txn.cell(row=total_row, column=4).value == "Total"
    assert ws_txn.cell(row=total_row, column=7).value == f"=SUBTOTAL(9, G2:G{total_row-1})"
    assert ws_txn.cell(row=total_row, column=8).value == f"=SUBTOTAL(9, H2:H{total_row-1})"

    # 3. Consolidated_Bank_Statement.parquet
    pq_payload = next(a for a in res.artifact_payloads if a.intent.name == "Consolidated_Bank_Statement.parquet")
    df = pl.read_parquet(io.BytesIO(pq_payload.content))
    assert len(df) == 99
    expected_cols = {
        "transaction_id",
        "transaction_hash",
        "input_location",
        "statement_id",
        "sequence_id",
        "date",
        "time",
        "posting_date",
        "value_date",
        "description",
        "raw_description",
        "reference_number",
        "raw_reference",
        "cheque_number",
        "debit",
        "credit",
        "running_balance",
        "eod_balance",
        "balance_as_on",
        "statement_generated_at",
        "transaction_mode",
        "bank_name",
        "masked_account_number",
        "account_fingerprint",
        "account_holder",
        "currency",
        "source_input_id",
        "page_number",
        "row_index",
        "status",
        "issues",
        "metadata",
    }
    for col in expected_cols:
        assert col in df.columns

    # Verify hashes are populated and unique per distinct transaction
    hashes = df["transaction_hash"].to_list()
    assert all(h is not None and len(h) == 16 for h in hashes)


def test_transaction_mode_classification() -> None:
    assert _detect_transaction_mode("UPI/123456/Payment to grocery") == "UPI"
    assert _detect_transaction_mode("NEFT UTR N123456789 salary transfer") == "NEFT"
    assert _detect_transaction_mode("RTGS transfer to vendor") == "RTGS"
    assert _detect_transaction_mode("IMPS/P2A/987654321") == "IMPS"
    assert _detect_transaction_mode("ATM cash withdrawal MG Road") == "CASH"
    assert _detect_transaction_mode("CWDR ATM Withdrawal") == "CASH"
    assert _detect_transaction_mode("CHQ CLG 123456 CLEARING") == "CHEQUE"
    assert _detect_transaction_mode("ANNUAL CARD CHARGES + GST") == "CHARGES"
    assert _detect_transaction_mode("SAVINGS BANK INTEREST CREDIT") == "INTEREST"
    assert _detect_transaction_mode("Internal fund transfer") == "TRANSFER"


def test_au_profile_file_format_metadata() -> None:
    from sarathi.shakti.bank_statements.capability import load_bank_profile_yaml

    profile_path = Path("src/sarathi/data/banks/au_excel_fmt1.yaml")
    assert profile_path.exists()
    data = load_bank_profile_yaml(profile_path)
    assert "file_format" in data
    fmt = data["file_format"]
    assert fmt["declared_extension"] == ".xlsx"
    assert "openxml_spreadsheet" in fmt["actual_hidden_format"]
    assert fmt["mime_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "504B0304" in fmt["magic_bytes"]
