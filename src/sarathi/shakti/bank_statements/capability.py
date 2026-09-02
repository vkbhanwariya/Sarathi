"""Bank Statement Consolidation Executable Capability for Sarathi V2."""

from __future__ import annotations

from contextlib import nullcontext
from decimal import Decimal
import io
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
from sarathi.shakti.bank_statements.row_classifier import RowType, classify_row
from sarathi.shakti.bank_statements.consolidator import (
    build_parquet_artifact,
    build_xlsx_artifact,
    consolidate_statements,
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
from sarathi.shakti.bank_statements.normalizer import parse_date, parse_decimal_amount
from sarathi.shakti.bank_statements.plugin import CAPABILITY_DECLARATION
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
        elif isinstance(prior_result.data, (tuple, list)) and all(isinstance(d, CanonicalDocument) for d in prior_result.data):
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

        # If all documents have no text/tables but have pages, handoff to OCR
        if all(not d.text.strip() and not any(p.tables for p in d.pages) and not d.tables and d.pages for d in docs):
            return Result(data=prior_result.data, next_requirement="ocr", resume_self=True)

        statements: list[BankStatement] = []
        all_warnings: list[WarningRecord] = []
        all_provs: list[ProvenanceRecord] = list(prior_result.provenance)

        for doc in docs:
            det_scope = (
                self._darpana.time_scope(context=context, phase_name="bank_detection", component="shakti.bank_statements")
                if self._darpana else nullcontext()
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
            doc_prov = tuple(p for p in prior_result.provenance if p.source_input_id == doc.source_input_id) or prior_result.provenance

            statement = validate_statement_balances(
                BankStatement(
                    bank_name=detection.bank_name or "Unknown Bank",
                    bank_profile=detection.matched_profile or "generic",
                    account_identity=detection.account_identity,
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
        all_tables: list[tuple[int, TableData]] = [(p_idx + 1, t) for p_idx, p in enumerate(doc.pages) for t in p.tables]
        all_tables.extend((1, t) for t in doc.tables if not any(t == e[1] for e in all_tables))

        if not all_tables and doc.text:
            import csv
            try:
                reader = csv.reader(io.StringIO(doc.text))
                rows = [r for r in reader if any(cell.strip() for cell in r)]
                for r_idx, r in enumerate(rows):
                    r_str = " ".join(str(c).lower() for c in r)
                    if ("date" in r_str or "txn" in r_str) and any(k in r_str for k in ("debit", "credit", "balance", "amount")):
                        all_tables.append((1, TableData(name="text_table", headers=tuple(rows[r_idx]), rows=tuple(tuple(x) for x in rows[r_idx + 1:]))))
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
                m.canonical_field: m.column_index
                for m in self._mapper.map_headers(hdr_cells, profile_id=profile_id)
            }
            d_col, desc_col = mappings.get("date"), mappings.get("description")
            dr_col, cr_col = mappings.get("debit"), mappings.get("credit")
            amt_col, dir_col = mappings.get("amount"), mappings.get("direction")
            b_col = mappings.get("balance")
            ref_col, chq_col = mappings.get("reference_number"), mappings.get("cheque_number")

            if d_col is None or not (any(c is not None for c in (dr_col, cr_col, b_col)) or amt_col is not None):
                continue

            for row_idx, row in enumerate(data_rows, start=1):
                row_cells = [str(c) for c in row]
                match classify_row(row_cells, date_col_idx=d_col):
                    case RowType.OPENING_BALANCE:
                        open_bal = parse_decimal_amount(_get_cell(row_cells, b_col)) or open_bal
                    case RowType.CLOSING_BALANCE:
                        close_bal = parse_decimal_amount(_get_cell(row_cells, b_col)) or close_bal
                    case RowType.CONTINUATION:
                        if raw_txns:
                            cont_text = _get_cell(row_cells, desc_col) or " ".join(c.strip() for c in row_cells if c.strip())
                            if cont_text:
                                prev = raw_txns[-1]
                                updated_desc = f"{prev.description} {cont_text}".strip()
                                raw_txns[-1] = Transaction(
                                    transaction_date=prev.transaction_date,
                                    description=updated_desc,
                                    bank_name=prev.bank_name,
                                    transaction_time=prev.transaction_time,
                                    reference_number=prev.reference_number,
                                    cheque_number=prev.cheque_number,
                                    debit=prev.debit,
                                    credit=prev.credit,
                                    running_balance=prev.running_balance,
                                    account_identity=prev.account_identity,
                                    currency=prev.currency,
                                    status=prev.status,
                                    issues=prev.issues,
                                    provenance=prev.provenance,
                                    metadata=prev.metadata,
                                )
                    case RowType.TRANSACTION:
                        tx_date = parse_date(_get_cell(row_cells, d_col))
                        if tx_date is not None:
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
                                tx_status = ValidationStatus.WARNING
                                tx_iss = ValidationIssue(
                                    code="MISSING_AMOUNT",
                                    message=f"Row {row_idx}: Transaction amount direction could not be determined.",
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
                            raw_txns.append(
                                Transaction(
                                    transaction_date=tx_date,
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
                                )
                            )

        return raw_txns, open_bal, close_bal, issues


def _get_cell(cells: Sequence[str], idx: int | None) -> str | None:
    """Safely get a cell value by index, returning None if out of range or empty."""
    if idx is None or idx < 0 or idx >= len(cells):
        return None
    val = cells[idx].strip()
    return val if val else None
