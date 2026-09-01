"""Consolidator and Canonical Output Exporter for Bank Statements.

Produces:
1. Consolidated_Bank_Statement.parquet (Polars persistent machine analysis source)
2. Consolidated_Bank_Statement.xlsx (openpyxl human review export)

Wrapped into canonical ArtifactPayloads for atomic commitment via Nabhi.
"""

from __future__ import annotations

from decimal import Decimal
import io
from pathlib import Path
from typing import Sequence

import openpyxl
from openpyxl.styles import Font, PatternFill
import polars as pl

from sarathi.sankalpa import ArtifactIntent, ArtifactPayload
from sarathi.shakti.bank_statements.models import (
    BankStatement,
    BankStatementConsolidationResult,
    Transaction,
    ValidationStatus,
)


def consolidate_statements(statements: Sequence[BankStatement]) -> BankStatementConsolidationResult:
    """Consolidate multiple statements into a unified consolidation result."""
    total_debits = Decimal("0")
    total_credits = Decimal("0")
    total_txns = 0
    overall_status = ValidationStatus.VALID
    all_issues = []

    for stmt in statements:
        if stmt.status == ValidationStatus.INVALID:
            overall_status = ValidationStatus.INVALID
        elif stmt.status == ValidationStatus.WARNING and overall_status == ValidationStatus.VALID:
            overall_status = ValidationStatus.WARNING
        all_issues.extend(stmt.issues)

        for tx in stmt.transactions:
            total_txns += 1
            if tx.debit is not None:
                total_debits += tx.debit
            if tx.credit is not None:
                total_credits += tx.credit

    return BankStatementConsolidationResult(
        statements=tuple(statements),
        total_transactions=total_txns,
        total_debit=total_debits,
        total_credit=total_credits,
        status=overall_status,
        issues=tuple(all_issues),
    )


def build_parquet_artifact(consolidation: BankStatementConsolidationResult) -> ArtifactPayload:
    """Generate Consolidated_Bank_Statement.parquet payload using Polars."""
    rows = []
    for stmt in consolidation.statements:
        for tx in stmt.transactions:
            rows.append({
                "date": tx.transaction_date.isoformat(),
                "time": tx.transaction_time.isoformat() if tx.transaction_time else None,
                "description": tx.description,
                "reference_number": tx.reference_number,
                "cheque_number": tx.cheque_number,
                "debit": float(tx.debit) if tx.debit is not None else None,
                "credit": float(tx.credit) if tx.credit is not None else None,
                "running_balance": float(tx.running_balance) if tx.running_balance is not None else None,
                "bank_name": tx.bank_name,
                "account_number": tx.account_number,
                "account_holder_name": tx.account_holder_name,
                "currency": tx.currency,
                "status": tx.status.value,
            })

    if rows:
        df = pl.DataFrame(rows)
    else:
        df = pl.DataFrame({
            "date": pl.Series([], dtype=pl.Utf8),
            "time": pl.Series([], dtype=pl.Utf8),
            "description": pl.Series([], dtype=pl.Utf8),
            "reference_number": pl.Series([], dtype=pl.Utf8),
            "cheque_number": pl.Series([], dtype=pl.Utf8),
            "debit": pl.Series([], dtype=pl.Float64),
            "credit": pl.Series([], dtype=pl.Float64),
            "running_balance": pl.Series([], dtype=pl.Float64),
            "bank_name": pl.Series([], dtype=pl.Utf8),
            "account_number": pl.Series([], dtype=pl.Utf8),
            "account_holder_name": pl.Series([], dtype=pl.Utf8),
            "currency": pl.Series([], dtype=pl.Utf8),
            "status": pl.Series([], dtype=pl.Utf8),
        })

    buf = io.BytesIO()
    df.write_parquet(buf)
    content_bytes = buf.getvalue()

    intent = ArtifactIntent(
        name="Consolidated_Bank_Statement.parquet",
        role="consolidated_data",
        media_type="application/vnd.apache.parquet",
    )
    return ArtifactPayload(intent=intent, content=content_bytes)


def build_xlsx_artifact(consolidation: BankStatementConsolidationResult) -> ArtifactPayload:
    """Generate Consolidated_Bank_Statement.xlsx payload using openpyxl."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Consolidated Statements"

    headers = [
        "Date", "Time", "Description", "Reference No.", "Cheque No.",
        "Debit", "Credit", "Running Balance", "Bank", "Account Number", "Account Holder", "Status"
    ]
    ws.append(headers)

    # Header styling
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font

    for stmt in consolidation.statements:
        for tx in stmt.transactions:
            ws.append([
                tx.transaction_date.strftime("%d-%m-%Y"),
                tx.transaction_time.strftime("%H:%M:%S") if tx.transaction_time else "",
                tx.description,
                tx.reference_number or "",
                tx.cheque_number or "",
                str(tx.debit) if tx.debit is not None else "",
                str(tx.credit) if tx.credit is not None else "",
                str(tx.running_balance) if tx.running_balance is not None else "",
                tx.bank_name,
                tx.account_number or "",
                tx.account_holder_name or "",
                tx.status.value.upper(),
            ])

    buf = io.BytesIO()
    wb.save(buf)
    content_bytes = buf.getvalue()

    intent = ArtifactIntent(
        name="Consolidated_Bank_Statement.xlsx",
        role="consolidated_report",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return ArtifactPayload(intent=intent, content=content_bytes)
