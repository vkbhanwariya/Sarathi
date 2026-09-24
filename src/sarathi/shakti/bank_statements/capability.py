"""Bank Statement Consolidation Executable Capability for Sarathi."""

from __future__ import annotations

import re
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ProvenanceRecord,
    Request,
    Result,
    TableData,
    WarningRecord,
)
from sarathi.sankalpa.document import normalize_canonical_documents
from sarathi.shakti.bank_statements.converter import (
    parse_date,
    parse_decimal_amount,
    parse_time,
)
from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.detector import detect_bank_statement, load_bank_profiles
from sarathi.shakti.bank_statements.mapper import HeaderMapper, extract_sample_data_rows
from sarathi.shakti.bank_statements.models import (
    AccountIdentity,
    BankStatement,
    Transaction,
    ValidationIssue,
    ValidationStatus,
)
from sarathi.shakti.bank_statements.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.bank_statements.row_classifier import RowType, classify_row
from sarathi.shakti.bank_statements.table_locator import (
    TableType,
    classify_table,
    get_table_header_and_data_rows,
    reconstruct_table_from_spans,
    reconstruct_table_from_text,
)
from sarathi.shakti.bank_statements.utr_repair import repair_utr
from sarathi.shakti.bank_statements.validator import validate_statement_balances
from sarathi.sutra import get_canonical_data_root

_CANONICAL_BANKS_DIR = get_canonical_data_root() / "banks"

_EXPLICIT_DR_INDICATORS = frozenset({"dr", "dr.", "debit", "withdrawal", "w/d", "out", "paid out", "d"})
_EXPLICIT_CR_INDICATORS = frozenset({"cr", "cr.", "credit", "deposit", "dep", "in", "paid in", "c"})
_BLANK_DATE_MARKERS = frozenset({"", "-", "--", "''", '"', "do", "ditto", "same"})


class BankStatementCapability:
    """Executable capability for bank statement consolidation."""

    def __init__(self, darpana: Darpana | None = None, banks_dir: Path | None = None) -> None:
        self.declaration = CAPABILITY_DECLARATION
        self._darpana = darpana
        self._banks_dir = banks_dir.resolve() if banks_dir is not None else _CANONICAL_BANKS_DIR
        self._mapper = HeaderMapper(banks_dir=self._banks_dir)
        self._profiles = {p.get("profile_id"): p for p in load_bank_profiles(self._banks_dir)}

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute bank statement parsing and consolidation on the extracted documents."""
        if prior_result is None or prior_result.data is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="BankStatementCapability requires a prior Result containing a CanonicalDocument or tuple of documents.",
            )

        normalized_docs = normalize_canonical_documents(prior_result.data)
        if normalized_docs is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="BankStatementCapability requires a prior Result containing a CanonicalDocument or tuple of documents.",
            )
        docs = list(normalized_docs)

        if not docs:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="No CanonicalDocument provided to BankStatementCapability.",
            )

        # If any document has no text and no tables, handoff to OCR
        if any(
            not d.text.strip() and not d.tables and not any(p.text.strip() or p.tables for p in d.pages) for d in docs
        ):
            return Result(data=prior_result.data, next_requirement="ocr", resume_self=True)

        statements: list[BankStatement] = []
        all_warnings: list[WarningRecord] = (
            list(prior_result.warnings) if prior_result and prior_result.warnings else []
        )
        all_provs: list[ProvenanceRecord] = list(prior_result.provenance)

        progress_cb = None
        if request.custom_options and callable(request.custom_options.get("progress_callback")):
            progress_cb = request.custom_options["progress_callback"]

        for doc in docs:
            if progress_cb is not None:
                tot_pages = len(doc.pages) if doc.pages else 1
                progress_cb(
                    file_display_name=doc.document_id,
                    page_number=1,
                    total_pages=tot_pages,
                    worker_id="1",
                    stage="Bank Statement Normalization",
                    device_type="CPU",
                    input_id=doc.document_id,
                )

            det_scope = (
                self._darpana.time_scope(
                    context=context, phase_name="bank_detection", component="shakti.bank_statements"
                )
                if self._darpana
                else nullcontext()
            )
            with det_scope:
                detection = detect_bank_statement(
                    doc,
                    banks_dir=self._banks_dir,
                    profiles=list(self._profiles.values()),
                )

            if not detection.is_bank_statement:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message="Document is not identified as a supported bank statement.",
                )

            doc_metadata: dict[str, Any] = {}
            raw_txns, open_bal, close_bal, doc_issues = self._extract_table_data(
                doc,
                request,
                detection.matched_profile,
                detection.bank_name or "Unknown Bank",
                detection.account_identity,
                metadata=doc_metadata,
            )

            dedup_res = deduplicate_transactions(raw_txns)
            doc_prov = (
                tuple(p for p in prior_result.provenance if p.source_input_id == doc.source_input_id)
                or prior_result.provenance
            )

            resolved_prof = doc_metadata.get("resolved_profile")
            final_profile = resolved_prof or detection.matched_profile or "generic"
            final_bank_name = (
                self._profiles.get(final_profile, {}).get("bank_name")
                if (final_profile and final_profile in self._profiles)
                else (detection.bank_name or "Unknown Bank")
            )

            statement = validate_statement_balances(
                BankStatement(
                    bank_name=final_bank_name,
                    bank_profile=final_profile,
                    account_identity=detection.account_identity,
                    ifsc=detection.ifsc or (detection.account_identity.ifsc if detection.account_identity else None),
                    account_holder=detection.account_identity.account_holder if detection.account_identity else None,
                    account_type=detection.account_identity.account_type if detection.account_identity else None,
                    opening_balance=open_bal,
                    closing_balance=close_bal,
                    transactions=dedup_res.unique_transactions,
                    issues=tuple(doc_issues),
                    provenance=doc_prov,
                    metadata=doc_metadata,
                )
            )
            statements.append(statement)

        from sarathi.shakti.bank_statements.consolidator import (
            build_parquet_artifact,
            build_xlsx_artifact,
            consolidate_statements,
        )

        consolidation = consolidate_statements(statements)
        all_warnings.extend(
            WarningRecord(code=i.code, message=i.message, stage="validation") for i in consolidation.issues
        )

        input_outcomes: dict[str, str] = {}
        for s, doc in zip(statements, docs, strict=False):
            all_warnings.extend(WarningRecord(code=i.code, message=i.message, stage="validation") for i in s.issues)
            outcome = "SUCCESS" if (len(s.transactions) > 0 and s.status != ValidationStatus.INVALID) else "FAILED"
            for p in s.provenance:
                if p.source_input_id:
                    input_outcomes[p.source_input_id] = outcome
            if doc.source_input_id:
                input_outcomes[doc.source_input_id] = outcome
        for doc in docs:
            if doc.source_input_id and doc.source_input_id not in input_outcomes:
                input_outcomes[doc.source_input_id] = "FAILED"

        res_metadata = {
            "input_outcomes": input_outcomes,
            "contributing_input_ids": tuple(input_outcomes.keys()),
        }

        return Result(
            data=consolidation,
            artifact_payloads=(build_parquet_artifact(consolidation), build_xlsx_artifact(consolidation)),
            provenance=tuple(all_provs),
            warnings=tuple(all_warnings),
            metadata=res_metadata,
        )

    def _extract_table_data(
        self,
        doc: CanonicalDocument,
        req: Request,
        profile_id: str | None,
        bank_name: str,
        account_identity: AccountIdentity | None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[list[Transaction], Decimal | None, Decimal | None, list[ValidationIssue]]:
        all_tables: list[tuple[int, TableData]] = [
            (p_idx + 1, t) for p_idx, p in enumerate(doc.pages) for t in p.tables
        ]
        all_tables.extend((1, t) for t in doc.tables if not any(t == e[1] for e in all_tables))

        if not all_tables:
            # 1. Attempt geometric table reconstruction from bounding box spans (scanned OCR)
            for p_idx, p in enumerate(doc.pages):
                if p.spans:
                    recon_t = reconstruct_table_from_spans(p.spans)
                    if recon_t is not None and recon_t.rows:
                        all_tables.append((p_idx + 1, recon_t))

            # 2. Attempt delimiter / tabular column reconstruction from document text
            if not all_tables and doc.text:
                recon_t = reconstruct_table_from_text(doc.text)
                if recon_t is not None and recon_t.rows:
                    all_tables.append((1, recon_t))

        raw_txns: list[Transaction] = []
        issues: list[ValidationIssue] = []
        open_bal: Decimal | None = None
        close_bal: Decimal | None = None
        current_sequence_id = 0
        eod_balances: list[dict[str, Any]] = []
        summary_rows: list[dict[str, Any]] = []

        active_profile = self._profiles.get(profile_id or "", {})
        has_signed_semantics = bool(active_profile.get("signed_amounts", False))

        for page_num, table in all_tables:
            if not table.rows and not table.headers:
                continue

            if classify_table(table) != TableType.TRANSACTION_TABLE:
                continue

            extracted_table = get_table_header_and_data_rows(table)
            if extracted_table is None:
                continue

            hdr_cells, data_rows = extracted_table
            sample_rows = extract_sample_data_rows(data_rows)

            resolved_prof, best_mappings, _ = self._mapper.resolve_best_profile(
                hdr_cells, candidate_profile=profile_id, sample_rows=sample_rows
            )
            if resolved_prof and resolved_prof != profile_id:
                active_profile = self._profiles.get(resolved_prof, {})
                has_signed_semantics = bool(active_profile.get("signed_amounts", False))
                if metadata is not None:
                    metadata["resolved_profile"] = resolved_prof

            mappings = {m.canonical_field: m.column_index for m in best_mappings}
            d_col, desc_col = mappings.get("date"), mappings.get("description")
            val_date_col, time_col = mappings.get("value_date"), mappings.get("time")
            dr_col, cr_col = mappings.get("debit"), mappings.get("credit")
            amt_col, dir_col = mappings.get("amount"), mappings.get("direction")
            b_col = mappings.get("balance")
            ref_col, chq_col = mappings.get("reference_number"), mappings.get("cheque_number")

            if d_col is None or not (any(c is not None for c in (dr_col, cr_col, b_col)) or amt_col is not None):
                continue

            amt_indices = [c for c in (dr_col, cr_col, amt_col, b_col) if c is not None]
            table_txns: list[Transaction] = []

            for row_idx, row in enumerate(data_rows, start=1):
                row_cells = [str(c) if c is not None else "" for c in row]
                match classify_row(row_cells, date_col_idx=d_col, amount_col_indices=amt_indices):
                    case RowType.OPENING_BALANCE:
                        parsed_open = parse_decimal_amount(_get_raw_cell(row, b_col))
                        if parsed_open is not None and open_bal is None:
                            open_bal = parsed_open
                    case RowType.CLOSING_BALANCE:
                        parsed_close = parse_decimal_amount(_get_raw_cell(row, b_col))
                        if parsed_close is not None:
                            close_bal = parsed_close
                    case RowType.EOD_BALANCE:
                        eod_date = parse_date(_get_raw_cell(row, d_col))
                        eod_bal = parse_decimal_amount(_get_raw_cell(row, b_col))
                        if eod_bal is None:
                            eod_bal = parse_decimal_amount(_get_raw_cell(row, amt_col))
                        eod_entry = {
                            "date": eod_date.isoformat() if eod_date else None,
                            "balance": str(eod_bal) if eod_bal is not None else None,
                            "raw": " ".join(c.strip() for c in row_cells if c.strip()),
                            "page": page_num,
                            "row": row_idx,
                        }
                        eod_balances.append(eod_entry)
                    case RowType.SUMMARY:
                        summary_entry = {
                            "raw": " ".join(c.strip() for c in row_cells if c.strip()),
                            "page": page_num,
                            "row": row_idx,
                            "cells": tuple(c.strip() for c in row_cells),
                        }
                        summary_rows.append(summary_entry)
                    case RowType.CONTINUATION:
                        if table_txns:
                            cont_text = _get_cell(row_cells, desc_col) or " ".join(
                                c.strip() for c in row_cells if c.strip()
                            )
                            if cont_text:
                                prev = table_txns[-1]
                                updated_desc = f"{prev.description} {cont_text}".strip()
                                table_txns[-1] = replace(prev, description=updated_desc)
                                if raw_txns:
                                    raw_txns[-1] = table_txns[-1]
                        else:
                            iss = ValidationIssue(
                                code="ORPHAN_CONTINUATION_ROW",
                                message=f"Row {row_idx}: Continuation row in table has no preceding transaction in the same table to attach to.",
                                severity="warning",
                                context={"row_index": row_idx, "page_number": page_num},
                            )
                            issues.append(iss)
                    case RowType.TRANSACTION:
                        raw_date_val = _get_raw_cell(row, d_col)
                        tx_date = parse_date(raw_date_val)
                        is_blank_date = raw_date_val is None or (
                            isinstance(raw_date_val, str)
                            and (not raw_date_val.strip() or raw_date_val.strip().lower() in _BLANK_DATE_MARKERS)
                        )
                        # Inherit date from previous transaction ONLY if date cell is blank/continuation and within the same table
                        if tx_date is None and is_blank_date and table_txns:
                            tx_date = table_txns[-1].transaction_date

                        if tx_date is None:
                            # If date cell was not blank, it was an invalid date format; otherwise missing date
                            date_display = str(raw_date_val) if raw_date_val is not None else ""
                            err_code = "MISSING_TRANSACTION_DATE" if is_blank_date else "INVALID_TRANSACTION_DATE"
                            err_msg = (
                                f"Row {row_idx}: Transaction row lacks a valid date and has no predecessor in table to inherit from."
                                if is_blank_date
                                else f"Row {row_idx}: Transaction row contains invalid date '{date_display}' and cannot be parsed."
                            )
                            iss = ValidationIssue(
                                code=err_code,
                                message=err_msg,
                                severity="error",
                                context={"row_index": row_idx, "page_number": page_num},
                            )
                            issues.append(iss)
                            continue

                        tx_time = parse_time(_get_raw_cell(row, time_col)) if time_col is not None else None
                        tx_val_date = parse_date(_get_raw_cell(row, val_date_col)) if val_date_col is not None else None

                        tx_debit = parse_decimal_amount(_get_raw_cell(row, dr_col))
                        if tx_debit is not None:
                            tx_debit = abs(tx_debit)
                        tx_credit = parse_decimal_amount(_get_raw_cell(row, cr_col))
                        if tx_credit is not None:
                            tx_credit = abs(tx_credit)
                        tx_bal = parse_decimal_amount(_get_raw_cell(row, b_col))

                        # Handle single amount column with strict explicit direction or signed semantics
                        if tx_debit is None and tx_credit is None and amt_col is not None:
                            parsed_amt = parse_decimal_amount(_get_raw_cell(row, amt_col))
                            raw_dir = _get_cell(row_cells, dir_col)
                            norm_dir = raw_dir.lower().strip() if raw_dir else ""

                            if norm_dir in _EXPLICIT_DR_INDICATORS:
                                tx_debit = abs(parsed_amt) if parsed_amt is not None else None
                                tx_credit = None
                            elif norm_dir in _EXPLICIT_CR_INDICATORS:
                                tx_credit = abs(parsed_amt) if parsed_amt is not None else None
                                tx_debit = None
                            elif has_signed_semantics and parsed_amt is not None:
                                if parsed_amt < Decimal("0"):
                                    tx_debit = abs(parsed_amt)
                                    tx_credit = None
                                elif parsed_amt > Decimal("0"):
                                    tx_credit = parsed_amt
                                    tx_debit = None
                            else:
                                # Direction absent or ambiguous: do NOT guess financial direction
                                tx_debit = None
                                tx_credit = None

                        tx_status = ValidationStatus.VALID
                        tx_issues: list[ValidationIssue] = []
                        if tx_debit is None and tx_credit is None:
                            tx_status = ValidationStatus.INVALID
                            tx_iss = ValidationIssue(
                                code="MISSING_AMOUNT",
                                message=f"Row {row_idx}: Transaction amount direction could not be determined.",
                                severity="error",
                                context={"row_index": row_idx},
                            )
                            tx_issues.append(tx_iss)
                            issues.append(tx_iss)

                        prov = ProvenanceRecord(
                            source_input_id=doc.source_input_id,
                            capability_id="bank_statements",
                            stage="bank_extraction",
                            page_number=page_num,
                            evidence={"row_index": row_idx},
                        )
                        current_sequence_id += 1
                        ref_val = _get_cell(row_cells, ref_col)
                        if ref_val:
                            repaired_utr, det_type, was_repaired = repair_utr(ref_val)
                            if was_repaired or det_type:
                                ref_val = repaired_utr

                        new_tx = Transaction(
                            transaction_date=tx_date,
                            transaction_time=tx_time,
                            value_date=tx_val_date,
                            description=_get_cell(row_cells, desc_col) or "",
                            bank_name=bank_name,
                            reference_number=ref_val,
                            cheque_number=_get_cell(row_cells, chq_col),
                            debit=tx_debit,
                            credit=tx_credit,
                            running_balance=tx_bal,
                            account_identity=account_identity,
                            status=tx_status,
                            issues=tuple(tx_issues),
                            provenance=(prov,),
                            sequence_id=current_sequence_id,
                        )
                        raw_txns.append(new_tx)
                        table_txns.append(new_tx)

        if metadata is not None:
            if eod_balances:
                metadata["eod_balances"] = tuple(eod_balances)
            if summary_rows:
                metadata["summary_rows"] = tuple(summary_rows)

        patterns = active_profile.get("metadata_patterns", {})
        if patterns:
            search_target = doc.text + " " + " ".join(p.text for p in doc.pages if p.text)
            if open_bal is None and "opening_balance" in patterns:
                m_open = re.search(patterns["opening_balance"], search_target, re.IGNORECASE)
                if m_open:
                    parsed_open = parse_decimal_amount(m_open.group(1))
                    if parsed_open is not None:
                        open_bal = parsed_open

            if close_bal is None and "closing_balance" in patterns:
                m_close = re.search(patterns["closing_balance"], search_target, re.IGNORECASE)
                if m_close:
                    parsed_close = parse_decimal_amount(m_close.group(1))
                    if parsed_close is not None:
                        close_bal = parsed_close

        return raw_txns, open_bal, close_bal, issues


def _get_raw_cell(row: Sequence[Any], idx: int | None) -> Any:
    """Safely get raw cell value by index without forcing to string."""
    if idx is None or idx < 0 or idx >= len(row):
        return None
    val = row[idx]
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        return s if s else None
    return val


def _get_cell(cells: Sequence[str], idx: int | None) -> str | None:
    """Safely get a cell value by index, returning None if out of range or empty."""
    if idx is None or idx < 0 or idx >= len(cells):
        return None
    val = cells[idx].strip()
    return val if val else None
