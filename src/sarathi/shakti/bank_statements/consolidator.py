"""Consolidator and Canonical Output Exporter for Bank Statements.

Produces:
1. Consolidated_Bank_Statement.parquet (Polars persistent machine analysis source preserving exact Decimal precision)
2. Consolidated_Bank_Statement.xlsx (openpyxl human review export with masked account and fingerprint)

Wrapped into canonical ArtifactPayloads for atomic commitment via Nabhi.
"""

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

import openpyxl
import polars as pl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

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
    if not ident:
        return ("statement", stmt.bank_name.lower().strip(), stmt.statement_id or str(id(stmt)))

    # Determine bank identity key:
    # If IFSC is available, its 4-letter prefix provides definitive institutional identity.
    ifsc_val = (ident.ifsc or stmt.ifsc or "").strip().upper()
    ifsc_prefix = ifsc_val[:4] if len(ifsc_val) >= 4 and ifsc_val[:4].isalnum() else None

    is_generic_bank = (
        stmt.bank_name.strip().lower() in ("generic bank", "generic", "bank", "unknown bank", "unknown")
        or (stmt.bank_profile and stmt.bank_profile.strip().lower() in ("generic", "common"))
    )

    # When bank name is generic and no authoritative IFSC prefix exists, bank identity is unverified.
    # We must NEVER group distinct statements together across files for deduplication.
    if is_generic_bank and not ifsc_prefix:
        return ("statement", stmt.bank_name.lower().strip(), stmt.statement_id or str(id(stmt)))

    bank_key = ifsc_prefix if ifsc_prefix else stmt.bank_name.lower().strip()

    # If account_fingerprint exists, it is either:
    # 1. Derived from a full unmasked account number (+ IFSC bank prefix if available), OR
    # 2. Derived from a masked account number + account holder (+ IFSC bank prefix).
    # In both cases, statements sharing this fingerprint safely belong to the same account.
    if ident.account_fingerprint:
        return ("fingerprint", bank_key, ident.account_fingerprint)

    # If account_fingerprint is None, the statement has an already-masked number without account holder.
    # We must not conflate distinct people having accounts with the same trailing 4 digits.
    holder = ident.account_holder.lower().strip() if ident.account_holder else None
    if holder:
        return ("holder", bank_key, holder)

    return ("statement", bank_key, stmt.statement_id or str(id(stmt)))


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
            replace(
                tx,
                statement_id=stmt.statement_id or tx.statement_id or f"stmt_{s_idx}",
                metadata={**tx.metadata, "statement_id": stmt.statement_id or tx.statement_id or f"stmt_{s_idx}"},
            )
            for s_idx, stmt in enumerate(group_stmts)
            for tx in stmt.transactions
            if tx.status != ValidationStatus.INVALID
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
    totals_by_curr: dict[str, tuple[Decimal, Decimal]] = {}
    for tx in sorted_valid_txns:
        curr = tx.currency or "INR"
        d, c = totals_by_curr.get(curr, (Decimal("0"), Decimal("0")))
        tx_d = tx.debit or Decimal("0")
        tx_c = tx.credit or Decimal("0")
        totals_by_curr[curr] = (d + tx_d, c + tx_c)

    for stmt in reordered_statements:
        curr = stmt.currency or "INR"
        if curr not in totals_by_curr:
            totals_by_curr[curr] = (Decimal("0"), Decimal("0"))

    # When mixed currencies are present, summing them directly produces misleading combined numbers.
    # Expose scalar total_debit and total_credit as None and provide per-currency totals.
    if len(totals_by_curr) > 1:
        total_debits: Decimal | None = None
        total_credits: Decimal | None = None
        all_issues.append(
            ValidationIssue(
                code="MIXED_CURRENCIES",
                message=(
                    f"Consolidated statements contain mixed currencies ({', '.join(sorted(totals_by_curr.keys()))}). "
                    "Scalar total_debit and total_credit are omitted; consult totals_by_currency."
                ),
                severity="info",
                context={"currencies": sorted(totals_by_curr.keys())},
            )
        )
    elif len(totals_by_curr) == 1:
        _, (total_debits, total_credits) = next(iter(totals_by_curr.items()))
    else:
        total_debits = Decimal("0")
        total_credits = Decimal("0")

    return BankStatementConsolidationResult(
        statements=tuple(reordered_statements),
        total_transactions=total_txns,
        total_debit=total_debits,
        total_credit=total_credits,
        status=overall_status,
        issues=tuple(all_issues),
        transactions=sorted_valid_txns,
        totals_by_currency=totals_by_curr,
    )


def _auto_fit_columns(sheet: openpyxl.worksheet.worksheet.Worksheet) -> None:
    """Auto-fit column widths with sensible bounds."""
    for col in sheet.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        sheet.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 60)


def build_parquet_artifact(consolidation: BankStatementConsolidationResult) -> ArtifactPayload:
    """Generate Consolidated_Bank_Statement.parquet payload preserving exact Decimal precision and full provenance."""
    tx_ids: list[str | None] = []
    stmt_ids: list[str | None] = []
    seq_ids: list[int] = []
    dates: list[str] = []
    times: list[str | None] = []
    posting_dates: list[str | None] = []
    value_dates: list[str | None] = []
    descriptions: list[str] = []
    raw_descs: list[str | None] = []
    ref_nums: list[str | None] = []
    raw_refs: list[str | None] = []
    chq_nums: list[str | None] = []
    debits: list[Decimal | None] = []
    credits: list[Decimal | None] = []
    balances: list[Decimal | None] = []
    bank_names: list[str] = []
    masked_accs: list[str | None] = []
    fingerprints: list[str | None] = []
    acc_holders: list[str | None] = []
    currencies: list[str] = []
    source_inputs: list[str | None] = []
    page_nums: list[int | None] = []
    row_idxs: list[int | None] = []
    statuses: list[str] = []
    issues_col: list[str | None] = []
    metadata_col: list[str | None] = []

    for tx in consolidation.transactions:
        ident = tx.account_identity
        masked_acc = ident.masked_account_number if ident else None
        fingerprint = ident.account_fingerprint if ident else None
        holder = ident.account_holder if ident else None

        tx_ids.append(tx.transaction_id)
        stmt_ids.append(tx.statement_id)
        seq_ids.append(getattr(tx, "sequence_id", 0) or 0)
        dates.append(tx.transaction_date.isoformat())
        times.append(tx.transaction_time.isoformat() if tx.transaction_time else None)
        posting_dates.append(tx.posting_date.isoformat() if tx.posting_date else None)
        value_dates.append(tx.value_date.isoformat() if tx.value_date else None)
        descriptions.append(tx.description)
        raw_descs.append(tx.raw_description)
        ref_nums.append(tx.reference_number)
        raw_refs.append(tx.raw_reference)
        chq_nums.append(tx.cheque_number)
        debits.append(tx.debit)
        credits.append(tx.credit)
        balances.append(tx.running_balance)
        bank_names.append(tx.bank_name)
        masked_accs.append(masked_acc)
        fingerprints.append(fingerprint)
        acc_holders.append(holder)
        currencies.append(tx.currency)
        source_inputs.append(tx.source_input_id or (tx.provenance[0].source_input_id if tx.provenance else None))
        page_nums.append(
            tx.page_number
            if tx.page_number is not None
            else (tx.provenance[0].page_number if tx.provenance else None)
        )
        row_idxs.append(
            tx.row_index
            if tx.row_index is not None
            else (
                tx.provenance[0].evidence.get("row_index")
                if (tx.provenance and tx.provenance[0].evidence)
                else None
            )
        )
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
            "transaction_id": pl.Series("transaction_id", tx_ids, dtype=pl.String),
            "statement_id": pl.Series("statement_id", stmt_ids, dtype=pl.String),
            "sequence_id": pl.Series("sequence_id", seq_ids, dtype=pl.Int64),
            "date": pl.Series("date", dates, dtype=pl.String),
            "time": pl.Series("time", times, dtype=pl.String),
            "posting_date": pl.Series("posting_date", posting_dates, dtype=pl.String),
            "value_date": pl.Series("value_date", value_dates, dtype=pl.String),
            "description": pl.Series("description", descriptions, dtype=pl.String),
            "raw_description": pl.Series("raw_description", raw_descs, dtype=pl.String),
            "reference_number": pl.Series("reference_number", ref_nums, dtype=pl.String),
            "raw_reference": pl.Series("raw_reference", raw_refs, dtype=pl.String),
            "cheque_number": pl.Series("cheque_number", chq_nums, dtype=pl.String),
            "debit": pl.Series("debit", debits, dtype=pl.Decimal(38, max_scale)),
            "credit": pl.Series("credit", credits, dtype=pl.Decimal(38, max_scale)),
            "running_balance": pl.Series("running_balance", balances, dtype=pl.Decimal(38, max_scale)),
            "bank_name": pl.Series("bank_name", bank_names, dtype=pl.String),
            "masked_account_number": pl.Series("masked_account_number", masked_accs, dtype=pl.String),
            "account_fingerprint": pl.Series("account_fingerprint", fingerprints, dtype=pl.String),
            "account_holder": pl.Series("account_holder", acc_holders, dtype=pl.String),
            "currency": pl.Series("currency", currencies, dtype=pl.String),
            "source_input_id": pl.Series("source_input_id", source_inputs, dtype=pl.String),
            "page_number": pl.Series("page_number", page_nums, dtype=pl.Int64),
            "row_index": pl.Series("row_index", row_idxs, dtype=pl.Int64),
            "status": pl.Series("status", statuses, dtype=pl.String),
            "issues": pl.Series("issues", issues_col, dtype=pl.String),
            "metadata": pl.Series("metadata", metadata_col, dtype=pl.String),
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
    """Generate multi-sheet Consolidated_Bank_Statement.xlsx payload with native numbers and audit ledger."""
    wb = openpyxl.Workbook()
    try:
        # Sheet 1: Transactions
        ws = wb.active
        ws.title = "Transactions"

        headers = [
            "Date",
            "Time",
            "Description",
            "Reference No.",
            "Cheque No.",
            "Debit",
            "Credit",
            "Running Balance",
            "Currency",
            "Bank",
            "Masked Account",
            "Account Fingerprint",
            "Account Holder",
            "Status",
            "Transaction ID",
            "Statement ID",
            "Value Date",
            "Posting Date",
            "Source File",
            "Page",
            "Row",
        ]
        ws.append(headers)

        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        ws.row_dimensions[1].height = 24

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center", horizontal="center" if col_idx not in (3, 4) else "left")

        currency_format = "#,##0.00;[Red]-#,##0.00"

        for row_idx, tx in enumerate(consolidation.transactions, start=2):
            ident = tx.account_identity
            masked_acc = ident.masked_account_number if ident else ""
            fingerprint = ident.account_fingerprint if ident else ""
            holder = ident.account_holder if ident else ""
            source_file = tx.source_input_id or (tx.provenance[0].source_input_id if tx.provenance else "")
            page_num = (
                tx.page_number
                if tx.page_number is not None
                else (tx.provenance[0].page_number if tx.provenance else "")
            )
            row_num = (
                tx.row_index
                if tx.row_index is not None
                else (
                    tx.provenance[0].evidence.get("row_index")
                    if (tx.provenance and tx.provenance[0].evidence)
                    else ""
                )
            )

            # 1. Date (native Excel date object)
            c1 = ws.cell(row=row_idx, column=1, value=tx.transaction_date)
            c1.number_format = "YYYY-MM-DD"
            c1.alignment = Alignment(horizontal="center")

            # 2. Time
            c2 = ws.cell(
                row=row_idx,
                column=2,
                value=tx.transaction_time.strftime("%H:%M:%S") if tx.transaction_time else "",
            )
            c2.alignment = Alignment(horizontal="center")

            # 3. Description (protected against formula injection)
            c3 = ws.cell(row=row_idx, column=3, value=tx.description)
            c3.data_type = "s"

            # 4. Reference No.
            c4 = ws.cell(row=row_idx, column=4, value=tx.reference_number or "")
            c4.data_type = "s"

            # 5. Cheque No.
            c5 = ws.cell(row=row_idx, column=5, value=tx.cheque_number or "")
            c5.data_type = "s"

            # 6. Debit (native numeric float for formula support)
            c6 = ws.cell(row=row_idx, column=6)
            if tx.debit is not None:
                c6.value = float(tx.debit)
                c6.number_format = currency_format
            else:
                c6.value = None

            # 7. Credit
            c7 = ws.cell(row=row_idx, column=7)
            if tx.credit is not None:
                c7.value = float(tx.credit)
                c7.number_format = currency_format
            else:
                c7.value = None

            # 8. Running Balance
            c8 = ws.cell(row=row_idx, column=8)
            if tx.running_balance is not None:
                c8.value = float(tx.running_balance)
                c8.number_format = currency_format
            else:
                c8.value = None

            # 9. Currency
            ws.cell(row=row_idx, column=9, value=tx.currency or "INR").data_type = "s"

            # 10. Bank
            ws.cell(row=row_idx, column=10, value=tx.bank_name).data_type = "s"

            # 11. Masked Account
            ws.cell(row=row_idx, column=11, value=masked_acc).data_type = "s"

            # 12. Account Fingerprint
            ws.cell(row=row_idx, column=12, value=fingerprint).data_type = "s"

            # 13. Account Holder
            ws.cell(row=row_idx, column=13, value=holder).data_type = "s"

            # 14. Status
            c14 = ws.cell(row=row_idx, column=14, value=tx.status.value.upper())
            c14.data_type = "s"
            c14.alignment = Alignment(horizontal="center")

            # 15. Transaction ID
            ws.cell(row=row_idx, column=15, value=tx.transaction_id or "").data_type = "s"

            # 16. Statement ID
            ws.cell(row=row_idx, column=16, value=tx.statement_id or "").data_type = "s"

            # 17. Value Date (native Excel date object)
            c17 = ws.cell(row=row_idx, column=17)
            if tx.value_date is not None:
                c17.value = tx.value_date
                c17.number_format = "YYYY-MM-DD"
                c17.alignment = Alignment(horizontal="center")
            else:
                c17.value = None

            # 18. Posting Date (native Excel date object)
            c18 = ws.cell(row=row_idx, column=18)
            if tx.posting_date is not None:
                c18.value = tx.posting_date
                c18.number_format = "YYYY-MM-DD"
                c18.alignment = Alignment(horizontal="center")
            else:
                c18.value = None

            # 19. Source File
            ws.cell(row=row_idx, column=19, value=str(source_file)).data_type = "s"

            # 20. Page
            c20 = ws.cell(row=row_idx, column=20, value=page_num if page_num != "" else None)
            if page_num != "":
                c20.number_format = "0"

            # 21. Row
            c21 = ws.cell(row=row_idx, column=21, value=row_num if row_num != "" else None)
            if row_num != "":
                c21.number_format = "0"

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        _auto_fit_columns(ws)

        # Sheet 2: Statements (Reconciliation Ledger)
        ws_stmt = wb.create_sheet(title="Statements")
        stmt_headers = [
            "Statement ID",
            "Bank",
            "Masked Account",
            "Account Holder",
            "Currency",
            "Period Start",
            "Period End",
            "Opening Balance",
            "Total Debits",
            "Total Credits",
            "Closing Balance",
            "Calculated Balance",
            "Reconciliation Diff",
            "Transactions",
            "Status",
        ]
        ws_stmt.append(stmt_headers)
        ws_stmt.row_dimensions[1].height = 24
        stmt_fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")

        for col_idx in range(1, len(stmt_headers) + 1):
            cell = ws_stmt.cell(row=1, column=col_idx)
            cell.fill = stmt_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center", horizontal="center" if col_idx not in (1, 2, 4) else "left")

        for s_idx, stmt in enumerate(consolidation.statements, start=2):
            s_debit = sum((t.debit for t in stmt.transactions if t.debit is not None), Decimal("0"))
            s_credit = sum((t.credit for t in stmt.transactions if t.credit is not None), Decimal("0"))
            calc_bal = (
                (stmt.opening_balance + s_credit - s_debit)
                if stmt.opening_balance is not None
                else None
            )
            recon_diff = (
                (stmt.closing_balance - calc_bal)
                if (stmt.closing_balance is not None and calc_bal is not None)
                else None
            )

            ws_stmt.cell(row=s_idx, column=1, value=stmt.statement_id or "").data_type = "s"
            ws_stmt.cell(row=s_idx, column=2, value=stmt.bank_name).data_type = "s"
            ws_stmt.cell(
                row=s_idx,
                column=3,
                value=stmt.account_identity.masked_account_number if stmt.account_identity else "",
            ).data_type = "s"
            ws_stmt.cell(
                row=s_idx,
                column=4,
                value=stmt.account_holder
                or (stmt.account_identity.account_holder if stmt.account_identity else ""),
            ).data_type = "s"
            ws_stmt.cell(row=s_idx, column=5, value=stmt.currency or "INR").data_type = "s"

            # Period Start (native Excel date)
            c_pstart = ws_stmt.cell(row=s_idx, column=6)
            if stmt.statement_period_start:
                c_pstart.value = stmt.statement_period_start
                c_pstart.number_format = "YYYY-MM-DD"
                c_pstart.alignment = Alignment(horizontal="center")
            else:
                c_pstart.value = None

            # Period End (native Excel date)
            c_pend = ws_stmt.cell(row=s_idx, column=7)
            if stmt.statement_period_end:
                c_pend.value = stmt.statement_period_end
                c_pend.number_format = "YYYY-MM-DD"
                c_pend.alignment = Alignment(horizontal="center")
            else:
                c_pend.value = None

            # Opening Balance
            c_open = ws_stmt.cell(row=s_idx, column=8)
            if stmt.opening_balance is not None:
                c_open.value = float(stmt.opening_balance)
                c_open.number_format = currency_format

            # Total Debits
            c_sdeb = ws_stmt.cell(row=s_idx, column=9, value=float(s_debit))
            c_sdeb.number_format = currency_format

            # Total Credits
            c_scrd = ws_stmt.cell(row=s_idx, column=10, value=float(s_credit))
            c_scrd.number_format = currency_format

            # Closing Balance
            c_close = ws_stmt.cell(row=s_idx, column=11)
            if stmt.closing_balance is not None:
                c_close.value = float(stmt.closing_balance)
                c_close.number_format = currency_format

            # Calculated Balance
            c_calc = ws_stmt.cell(row=s_idx, column=12)
            if calc_bal is not None:
                c_calc.value = float(calc_bal)
                c_calc.number_format = currency_format

            # Reconciliation Diff
            c_diff = ws_stmt.cell(row=s_idx, column=13)
            if recon_diff is not None:
                c_diff.value = float(recon_diff)
                c_diff.number_format = currency_format

            # Transactions count
            c_cnt = ws_stmt.cell(row=s_idx, column=14, value=len(stmt.transactions))
            c_cnt.number_format = "0"
            c_cnt.alignment = Alignment(horizontal="center")

            # Status
            c_stat = ws_stmt.cell(row=s_idx, column=15, value=stmt.status.value.upper())
            c_stat.data_type = "s"
            c_stat.alignment = Alignment(horizontal="center")

        ws_stmt.freeze_panes = "A2"
        ws_stmt.auto_filter.ref = ws_stmt.dimensions
        _auto_fit_columns(ws_stmt)

        # Sheet 3: Exceptions
        ws_exc = wb.create_sheet(title="Exceptions")
        exc_headers = ["Scope", "Entity ID", "Bank", "Severity", "Code", "Message", "Context"]
        ws_exc.append(exc_headers)
        ws_exc.row_dimensions[1].height = 24
        exc_fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")

        for col_idx in range(1, len(exc_headers) + 1):
            cell = ws_exc.cell(row=1, column=col_idx)
            cell.fill = exc_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center", horizontal="center" if col_idx in (1, 4, 5) else "left")

        exc_rows: list[list[Any]] = []
        for issue in consolidation.issues:
            exc_rows.append([
                "Consolidation",
                "ALL_STATEMENTS",
                "-",
                issue.severity.upper(),
                issue.code,
                issue.message,
                json.dumps(dict(issue.context)) if issue.context else "",
            ])
        for stmt in consolidation.statements:
            for issue in stmt.issues:
                exc_rows.append([
                    "Statement",
                    stmt.statement_id or "UNKNOWN",
                    stmt.bank_name,
                    issue.severity.upper(),
                    issue.code,
                    issue.message,
                    json.dumps(dict(issue.context)) if issue.context else "",
                ])
        for tx in consolidation.transactions:
            for issue in tx.issues:
                exc_rows.append([
                    "Transaction",
                    tx.transaction_id or f"tx_{getattr(tx, 'sequence_id', 0)}",
                    tx.bank_name,
                    issue.severity.upper(),
                    issue.code,
                    issue.message,
                    json.dumps(dict(issue.context)) if issue.context else "",
                ])

        if not exc_rows:
            exc_rows.append([
                "System",
                "All Statements",
                "-",
                "INFO",
                "ALL_CLEAR",
                "Zero reconciliation anomalies or validation exceptions detected across consolidated statements.",
                "",
            ])

        for e_idx, e_vals in enumerate(exc_rows, start=2):
            for c_idx, val in enumerate(e_vals, start=1):
                cell = ws_exc.cell(row=e_idx, column=c_idx, value=val)
                cell.data_type = "s"

        ws_exc.freeze_panes = "A2"
        ws_exc.auto_filter.ref = ws_exc.dimensions
        _auto_fit_columns(ws_exc)

        # Set active sheet back to Transactions
        wb.active = ws

        buf = io.BytesIO()
        wb.save(buf)
        content_bytes = buf.getvalue()
    finally:
        wb.close()

    intent = ArtifactIntent(
        name="Consolidated_Bank_Statement.xlsx",
        role="consolidated_report",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return ArtifactPayload(intent=intent, content=content_bytes)
