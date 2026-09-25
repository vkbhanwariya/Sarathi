"""Comprehensive Unit & Integration Tests for Axis Bank CSV Statements.

Validates:
1. Axis Bank profile identification, keyword detection, and table locating.
2. Legend table rejection (2-column footer table ignored).
3. Account holder and account number extraction from CSV header metadata.
4. Two-tier ID architecture (Input Location: 92401..._S1_R11; Sequential ID: TXN-0001).
5. Indian number format and subtotal formulas in Consolidated_Transactions.xlsx.
6. 2-sheet List_of_Accounts.xlsx directory (Accounts + Processing_Summary).
7. 32-column Consolidated_Bank_Statement.parquet forensic export with transaction_mode.
8. Balance reconciliation: Credits - Debits == Final Running Balance.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import polars as pl
import pytest

from sarathi.sankalpa import ExecutionContext, InputRef, Request, Result
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.native_extraction.readers.delimited import read_csv_or_text

_AXIS_FILE = Path("Input/Axis/924010050658231-27-08-2024to14-05-2026.csv")


@pytest.mark.skipif(not _AXIS_FILE.exists(), reason="Input/Axis CSV statement not present")
def test_axis_bank_statement_detection_and_extraction() -> None:
    data = _AXIS_FILE.read_bytes()
    doc, _, _ = read_csv_or_text(data, _AXIS_FILE.name)

    det = detect_bank_statement(doc)
    assert det.is_bank_statement is True
    assert det.bank_name == "Axis Bank Limited"
    assert det.matched_profile == "axis_csv_fmt1"
    assert det.account_identity is not None
    assert det.account_identity.account_holder == "SANDEEP BHATT"
    assert det.account_identity.masked_account_number.endswith("8231")

    cap = BankStatementCapability()
    in_ref = InputRef(
        input_id="in-axis-01",
        source_path=_AXIS_FILE,
        display_name=_AXIS_FILE.name,
        size_bytes=len(data),
    )
    req = Request(request_id="req-axis-01", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-axis-01", request_id="req-axis-01", trace_id="tr-1", span_id="sp-1")
    res = cap.execute(req, ctx, Result(data=doc))

    consolidation = res.data
    assert consolidation.total_transactions == 25
    assert len(consolidation.statements) == 1

    stmt = consolidation.statements[0]
    assert stmt.bank_name == "Axis Bank Limited"
    assert stmt.account_identity is not None
    assert stmt.account_identity.account_holder == "SANDEEP BHATT"
    assert stmt.account_identity.masked_account_number.endswith("8231")
    assert len(stmt.transactions) == 25
    assert len(stmt.issues) == 0

    # Financial reconciliation check
    assert consolidation.total_credit == Decimal("71212.49")
    assert consolidation.total_debit == Decimal("70139.00")
    net_diff = consolidation.total_credit - consolidation.total_debit
    assert net_diff == stmt.transactions[-1].running_balance


@pytest.mark.skipif(not _AXIS_FILE.exists(), reason="Input/Axis CSV statement not present")
def test_axis_two_tier_id_system_and_modes() -> None:
    data = _AXIS_FILE.read_bytes()
    doc, _, _ = read_csv_or_text(data, _AXIS_FILE.name)

    cap = BankStatementCapability()
    in_ref = InputRef(
        input_id="in-axis-02",
        source_path=_AXIS_FILE,
        display_name=_AXIS_FILE.name,
        size_bytes=len(data),
    )
    req = Request(request_id="req-axis-02", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-axis-02", request_id="req-axis-02", trace_id="tr-2", span_id="sp-2")
    res = cap.execute(req, ctx, Result(data=doc))

    for tx in res.data.transactions:
        # 1. Sequential Transaction ID pattern: TXN-XXXX
        assert tx.transaction_id.startswith("TXN-")
        assert len(tx.transaction_id) == 8

        # 2. Input Location pattern: <stem>_SX_RXX
        assert tx.input_location is not None
        assert tx.input_location.startswith(_AXIS_FILE.stem)
        assert "_R" in tx.input_location

        # 3. Valid date parsed
        assert isinstance(tx.transaction_date, date)

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


@pytest.mark.skipif(not _AXIS_FILE.exists(), reason="Input/Axis CSV statement not present")
def test_axis_deliverables_and_formatting() -> None:
    data = _AXIS_FILE.read_bytes()
    doc, _, _ = read_csv_or_text(data, _AXIS_FILE.name)

    cap = BankStatementCapability()
    in_ref = InputRef(
        input_id="in-axis-03",
        source_path=_AXIS_FILE,
        display_name=_AXIS_FILE.name,
        size_bytes=len(data),
    )
    req = Request(request_id="req-axis-03", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-axis-03", request_id="req-axis-03", trace_id="tr-3", span_id="sp-3")
    res = cap.execute(req, ctx, Result(data=doc))
    assert len(res.artifact_payloads) == 3

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
    assert len(acc_rows) == 2  # Header + 1 account
    assert acc_rows[1][1] == "SANDEEP BHATT"
    assert "8231" in acc_rows[1][2]
    assert acc_rows[1][3] == "Axis Bank Limited"
    assert "_R02" in acc_rows[1][4]
    assert "_R26" in acc_rows[1][4]
    assert acc_rows[1][5] == "TXN-0001 to TXN-0025"

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
    assert sum_rows[1][1] == _AXIS_FILE.stem
    assert "8231" in sum_rows[1][2]
    assert sum_rows[1][3] == "Axis Bank Limited"
    assert sum_rows[1][4] == "axis_csv_fmt1"
    assert sum_rows[1][5] > 0.0
    assert sum_rows[1][6] == 25  # Total rows scanned
    assert sum_rows[1][7] == 25  # Successful transactions
    assert sum_rows[1][8] == 0   # Duplicates removed
    assert sum_rows[1][9] == 0   # Failed/skipped rows
    assert sum_rows[1][10] == "VALID"
    assert sum_rows[1][11] == 0  # Warnings count
    assert sum_rows[1][12] == "ALL_CLEAR"

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

    d_cell = ws_txn.cell(row=2, column=3)
    assert d_cell.number_format == "DD-MM-YYYY"

    total_row = len(res.data.transactions) + 2
    assert ws_txn.cell(row=total_row, column=4).value == "Total"
    assert ws_txn.cell(row=total_row, column=7).value == f"=SUBTOTAL(9, G2:G{total_row-1})"
    assert ws_txn.cell(row=total_row, column=8).value == f"=SUBTOTAL(9, H2:H{total_row-1})"

    # 3. Consolidated_Bank_Statement.parquet
    pq_payload = next(a for a in res.artifact_payloads if a.intent.name == "Consolidated_Bank_Statement.parquet")
    df = pl.read_parquet(io.BytesIO(pq_payload.content))
    assert len(df) == 25
    assert "transaction_hash" in df.columns
    assert "transaction_mode" in df.columns
    assert "input_location" in df.columns
    assert "running_balance" in df.columns


def test_axis_profile_file_format_metadata() -> None:
    from sarathi.shakti.bank_statements.mapper import load_bank_profile_yaml

    prof = load_bank_profile_yaml(Path("src/sarathi/data/banks/axis_csv_fmt1.yaml"))
    assert prof["profile_id"] == "axis_csv_fmt1"
    assert prof["bank_name"] == "Axis Bank Limited"
    assert "file_format" in prof
    ff = prof["file_format"]
    assert ff["declared_extension"] == ".csv"
    assert "csv" in ff["actual_hidden_format"].lower()
    assert ff["mime_type"] == "text/csv"
