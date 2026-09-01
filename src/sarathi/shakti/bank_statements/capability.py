"""Bank Statement Consolidation Capability for Sarathi V2."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from decimal import Decimal
import io
from pathlib import Path
from typing import Any, Sequence

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
from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.bank_statements.mapper import HeaderMapper
from sarathi.shakti.bank_statements.models import (
    BankStatement,
    Transaction,
)
from sarathi.shakti.bank_statements.normalizer import parse_date, parse_decimal_amount
from sarathi.shakti.bank_statements.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.bank_statements.row_classifier import RowType, classify_row
from sarathi.shakti.bank_statements.validator import validate_statement_balances
from sarathi.shakti.native_extraction import NativeExtractionCapability


def _get_cell(row: Sequence[str], idx: int | None) -> str | None:
    """Safe cell getter from row sequence."""
    return row[idx].strip() if idx is not None and idx < len(row) else None


class BankStatementCapability:
    """Executable capability for bank statement consolidation."""

    def __init__(self, darpana: Darpana | None = None, banks_dir: Path | None = None) -> None:
        self.declaration = CAPABILITY_DECLARATION
        self._darpana = darpana
        self._banks_dir = banks_dir or Path("E:/Sarathi/data/banks")
        self._native_extractor = NativeExtractionCapability()
        self._mapper = HeaderMapper(banks_dir=self._banks_dir)

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute bank statement parsing and consolidation."""
        doc, base_prov = self._get_or_extract_document(request, context, prior_result)

        # Request OCR continuation if empty
        if not doc.text.strip() and not any(p.tables for p in doc.pages) and doc.pages:
            return Result(data=doc, next_requirement="ocr")

        # Detect bank statement presence & profile
        det_scope = (
            self._darpana.time_scope(context=context, phase_name="bank_detection", component="shakti.bank_statements")
            if self._darpana else nullcontext()
        )
        with det_scope:
            detection = detect_bank_statement(doc, banks_dir=self._banks_dir)

        if not detection.is_bank_statement:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Document is not identified as a bank statement (reasons: {'; '.join(detection.reasons)}).",
            )

        # Extract transactions and balances across all tables
        raw_txns, open_bal, close_bal = self._extract_table_data(doc, request, detection.matched_profile, detection.bank_name or "Unknown Bank", detection.account_number, detection.account_holder)

        # Deduplicate, validate, and consolidate
        dedup_res = deduplicate_transactions(raw_txns)
        statement = validate_statement_balances(
            BankStatement(
                bank_name=detection.bank_name or "Unknown Bank",
                bank_profile=detection.matched_profile or "generic",
                account_number=detection.account_number,
                account_holder=detection.account_holder,
                opening_balance=open_bal,
                closing_balance=close_bal,
                transactions=dedup_res.unique_transactions,
                provenance=base_prov,
            )
        )

        consolidation = consolidate_statements([statement])
        return Result(
            data=consolidation,
            artifact_payloads=(build_parquet_artifact(consolidation), build_xlsx_artifact(consolidation)),
            provenance=base_prov,
            warnings=tuple(WarningRecord(code=i.code, message=i.message, stage="validation") for i in consolidation.issues),
        )

    def _get_or_extract_document(self, req: Request, ctx: ExecutionContext, prior: Result | None) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...]]:
        if prior and isinstance(prior.data, CanonicalDocument):
            return prior.data, prior.provenance
        native_res = self._native_extractor.execute(req, ctx)
        if not isinstance(native_res.data, CanonicalDocument):
            raise DoshError(code=FailureCode.EXECUTION_FAILED, message="Native extraction failed to produce a CanonicalDocument.")
        return native_res.data, native_res.provenance

    def _extract_table_data(
        self,
        doc: CanonicalDocument,
        req: Request,
        profile_id: str | None,
        bank_name: str,
        acc_num: str | None,
        acc_holder: str | None,
    ) -> tuple[list[Transaction], Decimal | None, Decimal | None]:
        all_tables: list[tuple[int, TableData]] = [(p_idx + 1, t) for p_idx, p in enumerate(doc.pages) for t in p.tables]
        all_tables.extend((1, t) for t in doc.tables if not any(t == e[1] for e in all_tables))

        if not all_tables and doc.text:
            import csv
            try:
                reader = csv.reader(io.StringIO(doc.text))
                rows = [r for r in reader if any(cell.strip() for cell in r)]
                for r_idx, r in enumerate(rows):
                    r_str = " ".join(str(c).lower() for c in r)
                    if ("date" in r_str or "txn" in r_str) and any(k in r_str for k in ("debit", "credit", "balance")):
                        all_tables.append((1, TableData(name="text_table", headers=tuple(rows[r_idx]), rows=tuple(tuple(x) for x in rows[r_idx:]))))
                        break
            except Exception:
                pass

        raw_txns: list[Transaction] = []
        open_bal: Decimal | None = None
        close_bal: Decimal | None = None

        for page_num, table in all_tables:
            if not table.rows:
                continue

            # Find header index
            hdr_idx = next(
                (r_i for r_i, r in enumerate(table.rows) if ("date" in (s := " ".join(str(c).lower() for c in r)) or "txn" in s) and any(k in s for k in ("debit", "credit", "balance"))),
                None
            )
            if hdr_idx is None:
                continue

            mappings = {m.canonical_field: m.column_index for m in self._mapper.map_headers(table.rows[hdr_idx], profile_id=profile_id)}
            d_col, desc_col = mappings.get("date"), mappings.get("description")
            dr_col, cr_col, b_col = mappings.get("debit"), mappings.get("credit"), mappings.get("balance")
            ref_col, chq_col = mappings.get("reference_number"), mappings.get("cheque_number")

            if d_col is None or not any(c is not None for c in (dr_col, cr_col, b_col)):
                continue

            for row_idx, row in enumerate(table.rows[hdr_idx + 1:], start=hdr_idx + 1):
                row_cells = [str(c) for c in row]
                match classify_row(row_cells, date_col_idx=d_col):
                    case RowType.OPENING_BALANCE:
                        open_bal = parse_decimal_amount(_get_cell(row_cells, b_col)) or open_bal
                    case RowType.CLOSING_BALANCE:
                        close_bal = parse_decimal_amount(_get_cell(row_cells, b_col)) or close_bal
                    case RowType.TRANSACTION:
                        tx_date = parse_date(_get_cell(row_cells, d_col))
                        if tx_date is not None:
                            prov = ProvenanceRecord(
                                source_input_id=req.inputs[0].input_id if req.inputs else None,
                                capability_id="bank_statements",
                                stage="bank_extraction",
                                page_number=page_num,
                                evidence={"row_index": row_idx + 1, "raw_row": row_cells},
                            )
                            raw_txns.append(
                                Transaction(
                                    transaction_date=tx_date,
                                    description=_get_cell(row_cells, desc_col) or "",
                                    bank_name=bank_name,
                                    reference_number=_get_cell(row_cells, ref_col),
                                    cheque_number=_get_cell(row_cells, chq_col),
                                    debit=parse_decimal_amount(_get_cell(row_cells, dr_col)),
                                    credit=parse_decimal_amount(_get_cell(row_cells, cr_col)),
                                    running_balance=parse_decimal_amount(_get_cell(row_cells, b_col)),
                                    account_number=acc_num,
                                    account_holder_name=acc_holder,
                                    provenance=(prov,),
                                )
                            )

        return raw_txns, open_bal, close_bal
