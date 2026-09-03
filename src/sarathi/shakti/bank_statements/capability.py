"""Bank Statement Consolidation Executable Capability for Sarathi V2."""

from __future__ import annotations

import io
from contextlib import nullcontext
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Sequence

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
from sarathi.shakti.bank_statements.consolidator import (
    build_parquet_artifact,
    build_xlsx_artifact,
    consolidate_statements,
)
from sarathi.shakti.bank_statements.converter import (
    parse_date,
    parse_decimal_amount,
    parse_time,
)
from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.detector import detect_bank_statement, load_bank_profiles
from sarathi.shakti.bank_statements.mapper import HeaderMapper
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
)
from sarathi.shakti.bank_statements.validator import validate_statement_balances

_CANONICAL_BANKS_DIR = Path(__file__).resolve().parents[4] / "data" / "banks"

_EXPLICIT_DR_INDICATORS = frozenset({"dr", "dr.", "debit", "withdrawal", "w/d", "out", "paid out"})
_EXPLICIT_CR_INDICATORS = frozenset({"cr", "cr.", "credit", "deposit", "dep", "in", "paid in"})


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

        docs: list[CanonicalDocument]
        if isinstance(prior_result.data, CanonicalDocument):
            docs = [prior_result.data]
        elif isinstance(prior_result.data, (tuple, list)) and all(
            isinstance(d, CanonicalDocument) for d in prior_result.data
        ):
            docs = list(prior_result.data)
        else:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="BankStatementCapability requires a prior Result containing a CanonicalDocument or tuple of documents.",
            )

        if not docs:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="No CanonicalDocument provided to BankStatementCapability.",
            )

        # If any document has no text and no tables, handoff to OCR
        if any(not d.text.strip() and not d.tables and not any(p.text.strip() or p.tables for p in d.pages) for d in docs):
            return Result(data=prior_result.data, next_requirement="ocr", resume_self=True)

        statements: list[BankStatement] = []
        all_warnings: list[WarningRecord] = list(prior_result.warnings) if prior_result and prior_result.warnings else []
        all_provs: list[ProvenanceRecord] = list(prior_result.provenance)

        for doc in docs:
            det_scope = (
                self._darpana.time_scope(
                    context=context, phase_name="bank_detection", component="shakti.bank_statements"
                )
                if self._darpana
                else nullcontext()
            )
            with det_scope:
                detection = detect_bank_statement(doc, banks_dir=self._banks_dir)

            if not detection.is_bank_statement:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message="Document is not identified as a supported bank statement.",
                )

            raw_txns, open_bal, close_bal, doc_issues = self._extract_table_data(
                doc,
                request,
                detection.matched_profile,
                detection.bank_name or "Unknown Bank",
                detection.account_identity,
            )

            dedup_res = deduplicate_transactions(raw_txns)
            doc_prov = (
                tuple(p for p in prior_result.provenance if p.source_input_id == doc.source_input_id)
                or prior_result.provenance
            )

            statement = validate_statement_balances(
                BankStatement(
                    bank_name=detection.bank_name or "Unknown Bank",
                    bank_profile=detection.matched_profile or "generic",
                    account_identity=detection.account_identity,
                    ifsc=detection.ifsc or (detection.account_identity.ifsc if detection.account_identity else None),
                    account_holder=detection.account_identity.account_holder if detection.account_identity else None,
                    account_type=detection.account_identity.account_type if detection.account_identity else None,
                    opening_balance=open_bal,
                    closing_balance=close_bal,
                    transactions=dedup_res.unique_transactions,
                    issues=tuple(doc_issues),
                    provenance=doc_prov,
                )
            )
            statements.append(statement)

        consolidation = consolidate_statements(statements)
        all_warnings.extend(
            WarningRecord(code=i.code, message=i.message, stage="validation") for i in consolidation.issues
        )

        return Result(
            data=consolidation,
            artifact_payloads=(build_parquet_artifact(consolidation), build_xlsx_artifact(consolidation)),
            provenance=tuple(all_provs),
            warnings=tuple(all_warnings),
        )

    def _extract_table_data(
        self,
        doc: CanonicalDocument,
        req: Request,
        profile_id: str | None,
        bank_name: str,
        account_identity: AccountIdentity | None,
    ) -> tuple[list[Transaction], Decimal | None, Decimal | None, list[ValidationIssue]]:
        all_tables: list[tuple[int, TableData]] = [
            (p_idx + 1, t) for p_idx, p in enumerate(doc.pages) for t in p.tables
        ]
        all_tables.extend((1, t) for t in doc.tables if not any(t == e[1] for e in all_tables))

        if not all_tables and doc.text:
            import csv

            try:
                reader = csv.reader(io.StringIO(doc.text))
                rows = [r for r in reader if any(cell.strip() for cell in r)]
                for r_idx, r in enumerate(rows):
                    r_str = " ".join(str(c).lower() for c in r)
                    if ("date" in r_str or "txn" in r_str) and any(
                        k in r_str for k in ("debit", "credit", "balance", "amount")
                    ):
                        all_tables.append(
                            (
                                1,
                                TableData(
                                    name="text_table",
                                    headers=tuple(rows[r_idx]),
                                    rows=tuple(tuple(x) for x in rows[r_idx + 1 :]),
                                ),
                            )
                        )
                        break
            except (csv.Error, ValueError):
                pass

        raw_txns: list[Transaction] = []
        issues: list[ValidationIssue] = []
        open_bal: Decimal | None = None
        close_bal: Decimal | None = None

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

            mappings = {
                m.canonical_field: m.column_index for m in self._mapper.map_headers(hdr_cells, profile_id=profile_id)
            }
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
                row_cells = [str(c) for c in row]
                match classify_row(row_cells, date_col_idx=d_col, amount_col_indices=amt_indices):
                    case RowType.OPENING_BALANCE:
                        parsed_open = parse_decimal_amount(_get_cell(row_cells, b_col))
                        if parsed_open is not None:
                            open_bal = parsed_open
                    case RowType.CLOSING_BALANCE:
                        parsed_close = parse_decimal_amount(_get_cell(row_cells, b_col))
                        if parsed_close is not None:
                            close_bal = parsed_close
                    case RowType.CONTINUATION:
                        target_list = table_txns if table_txns else raw_txns
                        if target_list:
                            cont_text = _get_cell(row_cells, desc_col) or " ".join(
                                c.strip() for c in row_cells if c.strip()
                            )
                            if cont_text:
                                prev = target_list[-1]
                                updated_desc = f"{prev.description} {cont_text}".strip()
                                target_list[-1] = replace(prev, description=updated_desc)
                                if target_list is table_txns and raw_txns:
                                    raw_txns[-1] = target_list[-1]
                    case RowType.TRANSACTION:
                        tx_date = parse_date(_get_cell(row_cells, d_col))
                        # Inherit date from previous transaction ONLY within the same table
                        if tx_date is None and table_txns:
                            tx_date = table_txns[-1].transaction_date

                        if tx_date is None:
                            # Financial row has no date and cannot inherit: record explicit issue
                            iss = ValidationIssue(
                                code="MISSING_TRANSACTION_DATE",
                                message=f"Row {row_idx}: Transaction row lacks a valid date and has no predecessor in table to inherit from.",
                                severity="error",
                                context={"row_index": row_idx, "page_number": page_num},
                            )
                            issues.append(iss)
                            continue

                        tx_time = parse_time(_get_cell(row_cells, time_col)) if time_col is not None else None
                        tx_val_date = parse_date(_get_cell(row_cells, val_date_col)) if val_date_col is not None else None

                        tx_debit = parse_decimal_amount(_get_cell(row_cells, dr_col))
                        tx_credit = parse_decimal_amount(_get_cell(row_cells, cr_col))
                        tx_bal = parse_decimal_amount(_get_cell(row_cells, b_col))

                        # Handle single amount column with strict explicit direction or signed semantics
                        if tx_debit is None and tx_credit is None and amt_col is not None:
                            parsed_amt = parse_decimal_amount(_get_cell(row_cells, amt_col))
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
                        new_tx = Transaction(
                            transaction_date=tx_date,
                            transaction_time=tx_time,
                            value_date=tx_val_date,
                            description=_get_cell(row_cells, desc_col) or "",
                            bank_name=bank_name,
                            reference_number=_get_cell(row_cells, ref_col),
                            cheque_number=_get_cell(row_cells, chq_col),
                            debit=tx_debit,
                            credit=tx_credit,
                            running_balance=tx_bal,
                            account_identity=account_identity,
                            status=tx_status,
                            issues=tuple(tx_issues),
                            provenance=(prov,),
                            sequence_id=row_idx,
                        )
                        raw_txns.append(new_tx)
                        table_txns.append(new_tx)

        return raw_txns, open_bal, close_bal, issues


def _get_cell(cells: Sequence[str], idx: int | None) -> str | None:
    """Safely get a cell value by index, returning None if out of range or empty."""
    if idx is None or idx < 0 or idx >= len(cells):
        return None
    val = cells[idx].strip()
    return val if val else None
