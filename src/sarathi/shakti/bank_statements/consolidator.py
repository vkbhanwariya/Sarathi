"""Consolidator and Canonical Output Exporter for Bank Statements.

Produces:
1. Consolidated_Bank_Statement.parquet (Polars persistent machine analysis source preserving exact Decimal precision)
2. Consolidated_Bank_Statement.xlsx (openpyxl human review export with masked account and fingerprint)

Wrapped into canonical ArtifactPayloads for atomic commitment via Nabhi.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal
from typing import Sequence

import openpyxl
import polars as pl
from openpyxl.styles import Font, PatternFill

from sarathi.sankalpa import ArtifactIntent, ArtifactPayload
from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.models import (
    BankStatement,
    BankStatementConsolidationResult,
    DuplicateDecision,
    Transaction,
    ValidationIssue,
    ValidationStatus,
)


def _account_group_key(stmt: BankStatement) -> tuple:
    ident = stmt.account_identity
    if ident and ident.account_fingerprint:
        return ("fingerprint", stmt.bank_name.lower().strip(), ident.account_fingerprint)
    if ident and ident.masked_account_number:
        return ("masked", stmt.bank_name.lower().strip(), ident.masked_account_number)
    if ident and ident.account_holder:
        return ("holder", stmt.bank_name.lower().strip(), ident.account_holder.lower().strip())
    return ("statement", stmt.bank_name.lower().strip(), stmt.statement_id or str(id(stmt)))


def consolidate_statements(statements: Sequence[BankStatement]) -> BankStatementConsolidationResult:
    """Consolidate multiple statements into a unified consolidation result in stable chronological order."""
    import datetime

    # Group statements by account identity so cross-statement deduplication
    # only operates within the same account and never conflates distinct accounts.
    account_groups: dict[tuple, list[BankStatement]] = {}
    for stmt in statements:
        key = _account_group_key(stmt)
        account_groups.setdefault(key, []).append(stmt)

    all_issues: list[ValidationIssue] = []
    deduped_valid_txns: list[Transaction] = []

    for key, group_stmts in account_groups.items():
        group_valid_txns: list[Transaction] = [
            tx for stmt in group_stmts for tx in stmt.transactions if tx.status != ValidationStatus.INVALID
        ]
        if len(group_stmts) > 1 and group_valid_txns:
            dedup_res = deduplicate_transactions(group_valid_txns)
            deduped_valid_txns.extend(dedup_res.unique_transactions)
            for orig, dup, decision, reason in dedup_res.duplicates:
                if decision == DuplicateDecision.PROVEN_DUPLICATE:
                    msg = f"Duplicate transaction eliminated across statements: {reason}"
                    sev = "info"
                else:
                    msg = f"Probable duplicate transaction retained across statements: {reason}"
                    sev = "warning"
                all_issues.append(
                    ValidationIssue(
                        code="CROSS_STATEMENT_DUPLICATE",
                        message=msg,
                        severity=sev,
                        context={
                            "decision": decision.value,
                            "description": dup.description,
                            "date": dup.transaction_date.isoformat(),
                            "amount": str(dup.debit if dup.debit is not None else dup.credit),
                        },
                    )
                )
        else:
            deduped_valid_txns.extend(group_valid_txns)

    # Veda rule: transaction_date -> transaction_time when available -> original source row order (sequence_id)
    sorted_valid_txns = tuple(
        sorted(
            deduped_valid_txns,
            key=lambda tx: (
                tx.transaction_date,
                tx.transaction_time or datetime.time.min,
                getattr(tx, "sequence_id", 0) or 0,
            ),
        )
    )

    def _earliest_tx_date(stmt: BankStatement) -> datetime.date:
        dates = [tx.transaction_date for tx in stmt.transactions if tx.transaction_date is not None]
        return min(dates) if dates else datetime.date.min

    sorted_statements = sorted(statements, key=_earliest_tx_date)
    reordered_statements: list[BankStatement] = []

    overall_status = ValidationStatus.VALID

    for stmt in sorted_statements:
        if stmt.status == ValidationStatus.INVALID:
            overall_status = ValidationStatus.INVALID
        elif stmt.status == ValidationStatus.WARNING and overall_status == ValidationStatus.VALID:
            overall_status = ValidationStatus.WARNING
        all_issues.extend(stmt.issues)

        # Sort transactions within each statement in canonical chronological order
        sorted_txs = tuple(
            sorted(
                stmt.transactions,
                key=lambda tx: (
                    tx.transaction_date,
                    tx.transaction_time or datetime.time.min,
                    getattr(tx, "sequence_id", 0) or 0,
                ),
            )
        )
        reordered_statements.append(
            BankStatement(
                bank_name=stmt.bank_name,
                bank_profile=stmt.bank_profile,
                account_identity=stmt.account_identity,
                statement_period_start=stmt.statement_period_start,
                statement_period_end=stmt.statement_period_end,
                opening_balance=stmt.opening_balance,
                closing_balance=stmt.closing_balance,
                currency=stmt.currency,
                transactions=sorted_txs,
                status=stmt.status,
                issues=stmt.issues,
                provenance=stmt.provenance,
                metadata=stmt.metadata,
                statement_id=stmt.statement_id,
                account_holder=stmt.account_holder,
                account_type=stmt.account_type,
                branch=stmt.branch,
                ifsc=stmt.ifsc,
                balance_as_on=stmt.balance_as_on,
            )
        )

    # Calculate summary metrics strictly from canonical valid deduplicated transactions
    total_txns = len(sorted_valid_txns)
    total_debits = sum((tx.debit for tx in sorted_valid_txns if tx.debit is not None), Decimal("0"))
    total_credits = sum((tx.credit for tx in sorted_valid_txns if tx.credit is not None), Decimal("0"))

    return BankStatementConsolidationResult(
        statements=tuple(reordered_statements),
        total_transactions=total_txns,
        total_debit=total_debits,
        total_credit=total_credits,
        status=overall_status,
        issues=tuple(all_issues),
        transactions=sorted_valid_txns,
    )


def build_parquet_artifact(consolidation: BankStatementConsolidationResult) -> ArtifactPayload:
    """Generate Consolidated_Bank_Statement.parquet payload preserving exact Decimal precision."""
    dates: list[str] = []
    times: list[str | None] = []
    posting_dates: list[str | None] = []
    value_dates: list[str | None] = []
    descriptions: list[str] = []
    ref_nums: list[str | None] = []
    chq_nums: list[str | None] = []
    debits: list[Decimal | None] = []
    credits: list[Decimal | None] = []
    balances: list[Decimal | None] = []
    bank_names: list[str] = []
    masked_accs: list[str | None] = []
    fingerprints: list[str | None] = []
    acc_holders: list[str | None] = []
    currencies: list[str] = []
    statuses: list[str] = []
    issues_col: list[str | None] = []
    metadata_col: list[str | None] = []

    for tx in consolidation.transactions:
        ident = tx.account_identity
        masked_acc = ident.masked_account_number if ident else None
        fingerprint = ident.account_fingerprint if ident else None
        holder = ident.account_holder if ident else None

        dates.append(tx.transaction_date.isoformat())
        times.append(tx.transaction_time.isoformat() if tx.transaction_time else None)
        posting_dates.append(tx.posting_date.isoformat() if tx.posting_date else None)
        value_dates.append(tx.value_date.isoformat() if tx.value_date else None)
        descriptions.append(tx.description)
        ref_nums.append(tx.reference_number)
        chq_nums.append(tx.cheque_number)
        debits.append(tx.debit)
        credits.append(tx.credit)
        balances.append(tx.running_balance)
        bank_names.append(tx.bank_name)
        masked_accs.append(masked_acc)
        fingerprints.append(fingerprint)
        acc_holders.append(holder)
        currencies.append(tx.currency)
        statuses.append(tx.status.value)
        issues_col.append(
            json.dumps([{"code": i.code, "message": i.message, "severity": i.severity} for i in tx.issues])
            if tx.issues
            else None
        )
        metadata_col.append(json.dumps(dict(tx.metadata)) if tx.metadata else None)

    all_decimals = [d for d in (debits + credits + balances) if d is not None]
    max_scale = 2
    for d in all_decimals:
        exp = d.as_tuple().exponent
        if isinstance(exp, int) and exp < 0:
            max_scale = max(max_scale, abs(exp))
    max_scale = min(max_scale, 18)

    df = pl.DataFrame(
        {
            "date": pl.Series("date", dates, dtype=pl.Utf8),
            "time": pl.Series("time", times, dtype=pl.Utf8),
            "posting_date": pl.Series("posting_date", posting_dates, dtype=pl.Utf8),
            "value_date": pl.Series("value_date", value_dates, dtype=pl.Utf8),
            "description": pl.Series("description", descriptions, dtype=pl.Utf8),
            "reference_number": pl.Series("reference_number", ref_nums, dtype=pl.Utf8),
            "cheque_number": pl.Series("cheque_number", chq_nums, dtype=pl.Utf8),
            "debit": pl.Series("debit", debits, dtype=pl.Decimal(38, max_scale)),
            "credit": pl.Series("credit", credits, dtype=pl.Decimal(38, max_scale)),
            "running_balance": pl.Series("running_balance", balances, dtype=pl.Decimal(38, max_scale)),
            "bank_name": pl.Series("bank_name", bank_names, dtype=pl.Utf8),
            "masked_account_number": pl.Series("masked_account_number", masked_accs, dtype=pl.Utf8),
            "account_fingerprint": pl.Series("account_fingerprint", fingerprints, dtype=pl.Utf8),
            "account_holder": pl.Series("account_holder", acc_holders, dtype=pl.Utf8),
            "currency": pl.Series("currency", currencies, dtype=pl.Utf8),
            "status": pl.Series("status", statuses, dtype=pl.Utf8),
            "issues": pl.Series("issues", issues_col, dtype=pl.Utf8),
            "metadata": pl.Series("metadata", metadata_col, dtype=pl.Utf8),
        }
    )

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
    """Generate Consolidated_Bank_Statement.xlsx payload with masked account and fingerprint."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Consolidated Statements"

    headers = [
        "Date",
        "Time",
        "Description",
        "Reference No.",
        "Cheque No.",
        "Debit",
        "Credit",
        "Running Balance",
        "Bank",
        "Masked Account",
        "Account Fingerprint",
        "Account Holder",
        "Status",
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font

    for row_idx, tx in enumerate(consolidation.transactions, start=2):
        ident = tx.account_identity
        masked_acc = ident.masked_account_number if ident else ""
        fingerprint = ident.account_fingerprint if ident else ""
        holder = ident.account_holder if ident else ""

        row_vals = [
            tx.transaction_date.strftime("%d-%m-%Y"),
            tx.transaction_time.strftime("%H:%M:%S") if tx.transaction_time else "",
            tx.description,
            tx.reference_number or "",
            tx.cheque_number or "",
            str(tx.debit) if tx.debit is not None else "",
            str(tx.credit) if tx.credit is not None else "",
            str(tx.running_balance) if tx.running_balance is not None else "",
            tx.bank_name,
            masked_acc,
            fingerprint,
            holder,
            tx.status.value.upper(),
        ]
        for col_idx, val in enumerate(row_vals, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.value = val
            cell.data_type = "s"

    buf = io.BytesIO()
    wb.save(buf)
    content_bytes = buf.getvalue()

    intent = ArtifactIntent(
        name="Consolidated_Bank_Statement.xlsx",
        role="consolidated_report",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return ArtifactPayload(intent=intent, content=content_bytes)
