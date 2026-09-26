"""Consolidator and Canonical Output Exporter for Bank Statements.

Produces:
1. Consolidated_Bank_Statement.parquet (Polars persistent machine analysis source preserving exact Decimal precision)
2. Consolidated_Bank_Statement.xlsx (openpyxl human review export with masked account and fingerprint)

Wrapped into canonical ArtifactPayloads for atomic commitment via Nabhi.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any, Final

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

INDIAN_CURRENCY_FORMAT: Final[str] = r"[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00;\"-\""


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

    # If account_key or account_fingerprint exists with STRONG or MEDIUM confidence, group safely.
    key = ident.account_key or ident.account_fingerprint
    strength = getattr(ident, "identity_strength", "STRONG")
    if key and strength in ("STRONG", "MEDIUM"):
        return ("account_key", bank_key, key)

    # NEVER group distinct statements across files solely by holder name.
    # Statements without an authoritative account key remain statement-scoped.
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
    cross_dups_by_stmt: dict[str, int] = {}

    for key, group_stmts in account_groups.items():
        group_valid_txns: list[Transaction] = [
            replace(
                tx,
                statement_id=stmt.statement_id or tx.statement_id or f"stmt_{s_idx}",
                metadata={
                    **tx.metadata,
                    "statement_id": stmt.statement_id or tx.statement_id or f"stmt_{s_idx}",
                    "_orig_tx_id": id(tx),
                },
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
                    if dup.statement_id:
                        cross_dups_by_stmt[dup.statement_id] = cross_dups_by_stmt.get(dup.statement_id, 0) + 1
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

    def _earliest_tx_date(stmt: BankStatement) -> datetime.date:
        dates = [tx.transaction_date for tx in stmt.transactions if tx.transaction_date is not None]
        return min(dates) if dates else datetime.date.min

    sorted_statements = sorted(statements, key=_earliest_tx_date)

    # Resolve source file order across statements to preserve natural input presentation
    file_order: dict[str, int] = {}
    for stmt in sorted_statements:
        fid = None
        for p in stmt.provenance:
            if p.source_input_id:
                fid = p.source_input_id
                break
        if not fid and stmt.metadata and stmt.metadata.get("source_input_id"):
            fid = str(stmt.metadata["source_input_id"])
        if not fid:
            for tx in stmt.transactions:
                if tx.source_input_id:
                    fid = tx.source_input_id
                    break
                if tx.input_location and "_" in tx.input_location:
                    fid = tx.input_location.rsplit("_", 2)[0]
                    break
        if not fid:
            if stmt.account_identity and stmt.account_identity.account_fingerprint:
                fid = f"acc_{stmt.account_identity.account_fingerprint}"
            else:
                fid = stmt.statement_id or ""
        if fid and fid not in file_order:
            file_order[fid] = len(file_order)

    def _resolve_tx_file_key(tx: Transaction) -> str:
        if tx.source_input_id:
            return tx.source_input_id
        if tx.input_location and "_" in tx.input_location:
            return tx.input_location.rsplit("_", 2)[0]
        for p in tx.provenance:
            if p.source_input_id:
                return p.source_input_id
        if tx.account_identity and tx.account_identity.account_fingerprint:
            return f"acc_{tx.account_identity.account_fingerprint}"
        return tx.statement_id or ""

    def _tx_sort_key(tx: Transaction) -> tuple:
        f_key = _resolve_tx_file_key(tx)
        f_idx = file_order.get(f_key, 0)
        s_idx = tx.page_number if (tx.page_number is not None and tx.page_number > 0) else 1
        return (
            f_idx,
            s_idx,
            tx.transaction_date,
            tx.transaction_time or datetime.time.min,
            getattr(tx, "row_index", None) or getattr(tx, "sequence_id", 0) or 0,
        )

    # Sort hierarchy:
    # 1. First file -> 1st worksheet (old to new), 2nd worksheet (old to new)...
    # 2. Second file -> 1st worksheet (old to new), 2nd worksheet (old to new)...
    # 3. Third file...
    sorted_raw_txns = sorted(deduped_valid_txns, key=_tx_sort_key)

    # Continuous, unique transaction IDs: TXN-0001, TXN-0002, ...
    renumbered_txns: list[Transaction] = []
    valid_by_orig_id: dict[int, Transaction] = {}
    for idx, tx in enumerate(sorted_raw_txns, start=1):
        clean_meta = {k: v for k, v in tx.metadata.items() if k != "_orig_tx_id"}
        renumbered_tx = replace(
            tx,
            transaction_id=f"TXN-{idx:04d}",
            sequence_id=idx,
            metadata=clean_meta,
        )
        renumbered_txns.append(renumbered_tx)
        orig_id = tx.metadata.get("_orig_tx_id")
        if orig_id:
            valid_by_orig_id[orig_id] = renumbered_tx

    sorted_valid_txns = tuple(renumbered_txns)

    reordered_statements: list[BankStatement] = []
    overall_status = ValidationStatus.VALID

    seen_issues: set[tuple[str, str]] = set()
    deduped_issues: list[ValidationIssue] = []

    for iss in all_issues:
        key = (iss.code, iss.message)
        if key not in seen_issues:
            seen_issues.add(key)
            deduped_issues.append(iss)
            if iss.severity in ("error", "fatal"):
                overall_status = ValidationStatus.INVALID
            elif iss.severity == "warning" and overall_status == ValidationStatus.VALID:
                overall_status = ValidationStatus.WARNING

    for stmt in sorted_statements:
        if stmt.status == ValidationStatus.INVALID:
            overall_status = ValidationStatus.INVALID
        elif stmt.status == ValidationStatus.WARNING and overall_status == ValidationStatus.VALID:
            overall_status = ValidationStatus.WARNING
        for iss in stmt.issues:
            key = (iss.code, iss.message)
            if key not in seen_issues:
                seen_issues.add(key)
                deduped_issues.append(iss)
                if iss.severity in ("error", "fatal"):
                    overall_status = ValidationStatus.INVALID
                elif iss.severity == "warning" and overall_status == ValidationStatus.VALID:
                    overall_status = ValidationStatus.WARNING

        # Update valid transactions with their renumbered counterparts while retaining invalid ones
        stmt_updated_txs = []
        for tx in stmt.transactions:
            if id(tx) in valid_by_orig_id:
                stmt_updated_txs.append(valid_by_orig_id[id(tx)])
            else:
                stmt_updated_txs.append(tx)

        sorted_stmt_txs = tuple(sorted(stmt_updated_txs, key=_tx_sort_key))
        c_dups = cross_dups_by_stmt.get(stmt.statement_id or "", 0)
        stmt_meta = dict(stmt.metadata)
        if c_dups > 0:
            stmt_meta["cross_statement_duplicates"] = c_dups
        reordered_statements.append(replace(stmt, transactions=sorted_stmt_txs, metadata=stmt_meta))

    for tx in sorted_valid_txns:
        if tx.status == ValidationStatus.INVALID:
            overall_status = ValidationStatus.INVALID
        elif tx.status == ValidationStatus.WARNING and overall_status == ValidationStatus.VALID:
            overall_status = ValidationStatus.WARNING
        for iss in tx.issues:
            key = (iss.code, iss.message)
            if key not in seen_issues:
                seen_issues.add(key)
                deduped_issues.append(iss)
                if iss.severity in ("error", "fatal"):
                    overall_status = ValidationStatus.INVALID
                elif iss.severity == "warning" and overall_status == ValidationStatus.VALID:
                    overall_status = ValidationStatus.WARNING

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
        mix_issue = ValidationIssue(
            code="MIXED_CURRENCIES",
            message=(
                f"Consolidated statements contain mixed currencies ({', '.join(sorted(totals_by_curr.keys()))}). "
                "Scalar total_debit and total_credit are omitted; consult totals_by_currency."
            ),
            severity="info",
            context={"currencies": sorted(totals_by_curr.keys())},
        )
        if (mix_issue.code, mix_issue.message) not in seen_issues:
            seen_issues.add((mix_issue.code, mix_issue.message))
            deduped_issues.append(mix_issue)
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
        issues=tuple(deduped_issues),
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
    tx_hashes: list[str] = []
    input_locs: list[str | None] = []
    tx_modes: list[str | None] = []
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
    eod_bals: list[Decimal | None] = []
    bal_as_ons: list[Decimal | None] = []
    stmt_gen_ats: list[str | None] = []
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

    stmt_map = {s.statement_id: s for s in consolidation.statements if s.statement_id}
    stmt_fp_map = {
        s.account_identity.account_fingerprint: s
        for s in consolidation.statements
        if s.account_identity and s.account_identity.account_fingerprint
    }

    for tx in consolidation.transactions:
        ident = tx.account_identity
        stmt = stmt_map.get(tx.statement_id) or (
            stmt_fp_map.get(ident.account_fingerprint) if ident else None
        )
        masked_acc = ident.masked_account_number if ident else None
        fingerprint = ident.account_fingerprint if ident else None
        holder = ident.account_holder if ident else None

        raw_hash_data = f"{fingerprint or ''}:{tx.transaction_date.isoformat()}:{tx.debit or tx.credit}:{tx.reference_number or ''}:{getattr(tx, 'sequence_id', 0)}"
        tx_hash = hashlib.sha256(raw_hash_data.encode()).hexdigest()[:16]
        tx_hashes.append(tx_hash)

        input_locs.append(getattr(tx, "input_location", None))
        tx_modes.append(getattr(tx, "transaction_mode", None) or "OTHER")

        bal_as_ons.append(stmt.balance_as_on if stmt else None)
        stmt_gen_at = stmt.metadata.get("statement_generated_at") if (stmt and stmt.metadata) else None
        stmt_gen_ats.append(str(stmt_gen_at) if stmt_gen_at else None)

        eod_bal = None
        if stmt and stmt.closing_balance is not None and tx.transaction_date == stmt.statement_period_end:
            eod_bal = stmt.closing_balance
        elif tx.running_balance is not None:
            eod_bal = tx.running_balance
        eod_bals.append(eod_bal)

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

    all_decimals = [d for d in (debits + credits + balances + eod_bals + bal_as_ons) if d is not None]
    max_scale = 2
    for d in all_decimals:
        exp = d.as_tuple().exponent
        if isinstance(exp, int) and exp < 0:
            max_scale = max(max_scale, abs(exp))
    max_scale = min(max_scale, 18)

    df = pl.DataFrame(
        {
            "transaction_id": pl.Series("transaction_id", tx_ids, dtype=pl.String),
            "transaction_hash": pl.Series("transaction_hash", tx_hashes, dtype=pl.String),
            "input_location": pl.Series("input_location", input_locs, dtype=pl.String),
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
            "eod_balance": pl.Series("eod_balance", eod_bals, dtype=pl.Decimal(38, max_scale)),
            "balance_as_on": pl.Series("balance_as_on", bal_as_ons, dtype=pl.Decimal(38, max_scale)),
            "statement_generated_at": pl.Series("statement_generated_at", stmt_gen_ats, dtype=pl.String),
            "transaction_mode": pl.Series("transaction_mode", tx_modes, dtype=pl.String),
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


def build_accounts_xlsx_artifact(consolidation: BankStatementConsolidationResult) -> ArtifactPayload:
    """Generate List_of_Accounts.xlsx master directory payload."""
    wb = openpyxl.Workbook()
    try:
        ws = wb.active
        ws.title = "Accounts"

        headers = [
            "S.No.",
            "Name of the Account Holder",
            "Account No.",
            "Bank Name",
            "Input Location Range",
            "Transaction ID Range",
        ]
        ws.append(headers)

        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        ws.row_dimensions[1].height = 24

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center", horizontal="center" if col_idx not in (2, 4) else "left")

        # Pre-index transactions by statement_id
        tx_by_statement: dict[str, list[Transaction]] = {}
        for tx in consolidation.transactions:
            if tx.statement_id:
                tx_by_statement.setdefault(tx.statement_id, []).append(tx)

        # Group statements by unique account identity for Sheet 1 (Master Account Directory: 1 row per unique account)
        account_groups: dict[str, list[BankStatement]] = {}
        for stmt in consolidation.statements:
            ident = stmt.account_identity
            acc_k = (
                ident.account_key
                if (ident and ident.account_key)
                else (ident.account_fingerprint if ident else "")
            )
            if not acc_k:
                acc_k = (
                    ident.masked_account_number.strip().upper()
                    if (ident and ident.masked_account_number)
                    else f"stmt_{stmt.statement_id or id(stmt)}"
                )
            account_groups.setdefault(acc_k, []).append(stmt)

        for a_idx, (acc_k, stmts) in enumerate(account_groups.items(), start=1):
            row_idx = a_idx + 1

            holder = next(
                (
                    s.account_holder or (s.account_identity.account_holder if s.account_identity else "")
                    for s in stmts
                    if (s.account_holder or (s.account_identity and s.account_identity.account_holder))
                ),
                "-",
            )
            acc_no = next(
                (
                    s.account_identity.masked_account_number
                    for s in stmts
                    if s.account_identity and s.account_identity.masked_account_number
                ),
                "-",
            )
            bank = next((s.bank_name for s in stmts if s.bank_name), "-")

            stmt_ids_for_account = {s.statement_id for s in stmts if s.statement_id}
            acc_txns: list[Transaction] = []
            for t in consolidation.transactions:
                t_acc_k = (
                    t.account_identity.account_key
                    if (t.account_identity and t.account_identity.account_key)
                    else (t.account_identity.account_fingerprint if t.account_identity else "")
                )
                if (t_acc_k and t_acc_k == acc_k) or (t.statement_id and t.statement_id in stmt_ids_for_account):
                    acc_txns.append(t)
            if not acc_txns:
                for s in stmts:
                    acc_txns.extend(s.transactions)

            locs = [t.input_location for t in acc_txns if getattr(t, "input_location", None)]
            loc_range = f"{sorted(locs)[0]} to {sorted(locs)[-1]}" if locs else "-"

            ids = [t.transaction_id for t in acc_txns if t.transaction_id]
            id_range = f"{sorted(ids)[0]} to {sorted(ids)[-1]}" if ids else "-"

            c1 = ws.cell(row=row_idx, column=1, value=a_idx)
            c1.alignment = Alignment(horizontal="center")
            c2 = ws.cell(row=row_idx, column=2, value=holder)
            c2.data_type = "s"
            c3 = ws.cell(row=row_idx, column=3, value=acc_no)
            c3.data_type = "s"
            c4 = ws.cell(row=row_idx, column=4, value=bank)
            c4.data_type = "s"
            c5 = ws.cell(row=row_idx, column=5, value=loc_range)
            c5.data_type = "s"
            c5.alignment = Alignment(horizontal="center")
            c6 = ws.cell(row=row_idx, column=6, value=id_range)
            c6.data_type = "s"
            c6.alignment = Alignment(horizontal="center")

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        _auto_fit_columns(ws)

        # Sheet 2: Processing Summary
        ws_sum = wb.create_sheet(title="Processing_Summary")
        sum_headers = [
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
        ]
        ws_sum.append(sum_headers)
        ws_sum.row_dimensions[1].height = 24

        for col_idx in range(1, len(sum_headers) + 1):
            cell = ws_sum.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(
                vertical="center",
                horizontal="center" if col_idx not in (2, 4, 13) else "left",
            )

        for s_idx, stmt in enumerate(consolidation.statements, start=1):
            row_idx = s_idx + 1
            ident = stmt.account_identity
            acc_no = ident.masked_account_number if (ident and ident.masked_account_number) else "-"
            bank = stmt.bank_name
            profile = stmt.bank_profile or "-"

            stmt_txns = (
                tx_by_statement.get(stmt.statement_id, [])
                if stmt.statement_id
                else []
            )
            if not stmt_txns:
                if len(consolidation.statements) == 1:
                    stmt_txns = list(consolidation.transactions)
                else:
                    stmt_txns = list(stmt.transactions)

            succ_txns = len(stmt_txns)
            dup_txns = stmt.metadata.get("duplicate_transactions", 0) + stmt.metadata.get(
                "cross_statement_duplicates", 0
            )
            total_scanned = stmt.metadata.get("total_scanned_rows")
            if total_scanned is None:
                total_scanned = succ_txns + dup_txns
            failed_skipped = max(0, total_scanned - succ_txns - dup_txns)

            match_score = stmt.metadata.get("header_match_score", 0.0)
            src_file = stmt.metadata.get("source_file_stem") or (
                stmt.provenance[0].source_input_id if stmt.provenance else "Statement"
            )

            warn_count = len(stmt.issues)
            if stmt.issues:
                warn_details = "; ".join(f"{iss.code}: {iss.message}" for iss in stmt.issues)
            else:
                warn_details = "ALL_CLEAR"

            # 1. S.No.
            c1 = ws_sum.cell(row=row_idx, column=1, value=s_idx)
            c1.alignment = Alignment(horizontal="center")

            # 2. Source File
            c2 = ws_sum.cell(row=row_idx, column=2, value=str(src_file))
            c2.data_type = "s"

            # 3. Account No.
            c3 = ws_sum.cell(row=row_idx, column=3, value=acc_no)
            c3.data_type = "s"
            c3.alignment = Alignment(horizontal="center")

            # 4. Bank Name
            c4 = ws_sum.cell(row=row_idx, column=4, value=bank)
            c4.data_type = "s"

            # 5. Profile Used
            c5 = ws_sum.cell(row=row_idx, column=5, value=profile)
            c5.data_type = "s"
            c5.alignment = Alignment(horizontal="center")

            # 6. Header Match Score
            c6 = ws_sum.cell(row=row_idx, column=6, value=float(match_score))
            c6.number_format = "0.00"
            c6.alignment = Alignment(horizontal="center")

            # 7. Total Rows Scanned
            c7 = ws_sum.cell(row=row_idx, column=7, value=int(total_scanned))
            c7.number_format = "#,##0"
            c7.alignment = Alignment(horizontal="center")

            # 8. Successful Transactions
            c8 = ws_sum.cell(row=row_idx, column=8, value=int(succ_txns))
            c8.number_format = "#,##0"
            c8.alignment = Alignment(horizontal="center")

            # 9. Duplicates Removed
            c9 = ws_sum.cell(row=row_idx, column=9, value=int(dup_txns))
            c9.number_format = "#,##0"
            c9.alignment = Alignment(horizontal="center")

            # 10. Failed / Skipped Rows
            c10 = ws_sum.cell(row=row_idx, column=10, value=int(failed_skipped))
            c10.number_format = "#,##0"
            c10.alignment = Alignment(horizontal="center")

            # 11. Status
            c11 = ws_sum.cell(row=row_idx, column=11, value=stmt.status.value.upper())
            c11.data_type = "s"
            c11.alignment = Alignment(horizontal="center")

            # 12. Warnings Count
            c12 = ws_sum.cell(row=row_idx, column=12, value=int(warn_count))
            c12.number_format = "0"
            c12.alignment = Alignment(horizontal="center")

            # 13. Warning / Audit Details
            c13 = ws_sum.cell(row=row_idx, column=13, value=warn_details)
            c13.data_type = "s"

        if len(consolidation.statements) > 0:
            tot_row = len(consolidation.statements) + 2
            lbl = ws_sum.cell(row=tot_row, column=4, value="Total")
            lbl.font = Font(bold=True)
            lbl.alignment = Alignment(horizontal="right")

            for c_idx, col_letter in [(7, "G"), (8, "H"), (9, "I"), (10, "J"), (12, "L")]:
                c_tot = ws_sum.cell(row=tot_row, column=c_idx, value=f"=SUM({col_letter}2:{col_letter}{tot_row-1})")
                c_tot.font = Font(bold=True)
                c_tot.number_format = "#,##0"
                c_tot.alignment = Alignment(horizontal="center")

        ws_sum.freeze_panes = "A2"
        ws_sum.auto_filter.ref = ws_sum.dimensions
        _auto_fit_columns(ws_sum)

        # Set active sheet back to Accounts
        wb.active = ws

        buf = io.BytesIO()
        wb.save(buf)
        content_bytes = buf.getvalue()
    finally:
        wb.close()

    intent = ArtifactIntent(
        name="List_of_Accounts.xlsx",
        role="accounts_directory",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return ArtifactPayload(intent=intent, content=content_bytes)


def build_transactions_xlsx_artifact(consolidation: BankStatementConsolidationResult) -> ArtifactPayload:
    """Generate Consolidated_Transactions.xlsx (clean 9-column passbook ledger with Indian number formatting)."""
    wb = openpyxl.Workbook()
    try:
        ws = wb.active
        ws.title = "Transactions"

        headers = [
            "Transaction ID",
            "Input Location",
            "Date",
            "Description",
            "Ref / UTR No.",
            "Cheque No.",
            "Debit",
            "Credit",
            "Balance",
        ]
        ws.append(headers)

        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        ws.row_dimensions[1].height = 24

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center", horizontal="center" if col_idx not in (4, 5) else "left")

        for row_idx, tx in enumerate(consolidation.transactions, start=2):
            tx_id = tx.transaction_id or f"TXN-{row_idx-1:04d}"
            input_loc = getattr(tx, "input_location", None) or ""

            # 1. Transaction ID
            c1 = ws.cell(row=row_idx, column=1, value=tx_id)
            c1.data_type = "s"
            c1.alignment = Alignment(horizontal="center")

            # 2. Input Location
            c2 = ws.cell(row=row_idx, column=2, value=input_loc)
            c2.data_type = "s"
            c2.alignment = Alignment(horizontal="center")

            # 3. Date (native Excel date object)
            c3 = ws.cell(row=row_idx, column=3, value=tx.transaction_date)
            c3.number_format = "DD-MM-YYYY"
            c3.alignment = Alignment(horizontal="center")

            # 4. Description
            c4 = ws.cell(row=row_idx, column=4, value=tx.description)
            c4.data_type = "s"

            # 5. Ref / UTR No.
            c5 = ws.cell(row=row_idx, column=5, value=tx.reference_number or "")
            c5.data_type = "s"

            # 6. Cheque No.
            c6 = ws.cell(row=row_idx, column=6, value=tx.cheque_number or "")
            c6.data_type = "s"

            # 7. Debit
            c7 = ws.cell(row=row_idx, column=7)
            if tx.debit is not None:
                c7.value = float(tx.debit)
                c7.number_format = INDIAN_CURRENCY_FORMAT
            else:
                c7.value = None

            # 8. Credit
            c8 = ws.cell(row=row_idx, column=8)
            if tx.credit is not None:
                c8.value = float(tx.credit)
                c8.number_format = INDIAN_CURRENCY_FORMAT
            else:
                c8.value = None

            # 9. Balance
            c9 = ws.cell(row=row_idx, column=9)
            if tx.running_balance is not None:
                c9.value = float(tx.running_balance)
                c9.number_format = INDIAN_CURRENCY_FORMAT
            else:
                c9.value = None

        total_row = len(consolidation.transactions) + 2
        if len(consolidation.transactions) > 0:
            if len(consolidation.totals_by_currency) > 1:
                c_tot_label = ws.cell(row=total_row, column=4, value="Totals (Mixed Currencies - See Parquet)")
                c_tot_label.font = Font(bold=True)
                c_tot_label.alignment = Alignment(horizontal="right")
            else:
                c_tot_label = ws.cell(row=total_row, column=4, value="Total")
                c_tot_label.font = Font(bold=True)
                c_tot_label.alignment = Alignment(horizontal="right")

                c_tot_deb = ws.cell(row=total_row, column=7, value=f"=SUBTOTAL(9, G2:G{total_row-1})")
                c_tot_deb.number_format = INDIAN_CURRENCY_FORMAT
                c_tot_deb.font = Font(bold=True)

                c_tot_crd = ws.cell(row=total_row, column=8, value=f"=SUBTOTAL(9, H2:H{total_row-1})")
                c_tot_crd.number_format = INDIAN_CURRENCY_FORMAT
                c_tot_crd.font = Font(bold=True)

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:I{total_row-1 if len(consolidation.transactions) > 0 else 1}"
        _auto_fit_columns(ws)

        buf = io.BytesIO()
        wb.save(buf)
        content_bytes = buf.getvalue()
    finally:
        wb.close()

    intent = ArtifactIntent(
        name="Consolidated_Transactions.xlsx",
        role="consolidated_transactions",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
