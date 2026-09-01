"""Bank Statement Consolidation Capability for Sarathi V2."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from decimal import Decimal
import io
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
    BankStatementConsolidationResult,
    Transaction,
    ValidationIssue,
    ValidationStatus,
)
from sarathi.shakti.bank_statements.normalizer import parse_date, parse_decimal_amount, parse_time
from sarathi.shakti.bank_statements.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.bank_statements.row_classifier import RowType, classify_row
from sarathi.shakti.bank_statements.table_locator import TableType, classify_table
from sarathi.shakti.bank_statements.validator import validate_statement_balances
from sarathi.shakti.native_extraction import NativeExtractionCapability


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
        """Execute bank statement parsing and consolidation on the request inputs.

        Flow:
        1. If prior_result carries a CanonicalDocument, use it; otherwise run native extraction.
        2. Detect bank statement presence & profile. If scanned/empty, request OCR continuation.
        3. Localize transaction tables and map headers.
        4. Classify rows, parse Decimal amounts and dates.
        5. Validate balance continuity and reconcile.
        6. Deduplicate and consolidate into Parquet and XLSX artifacts.
        """
        # 1. Obtain extracted CanonicalDocument
        doc: CanonicalDocument
        base_provenance: tuple[ProvenanceRecord, ...] = ()
        if prior_result is not None and isinstance(prior_result.data, CanonicalDocument):
            doc = prior_result.data
            base_provenance = prior_result.provenance
        else:
            native_res = self._native_extractor.execute(request, context)
            if not isinstance(native_res.data, CanonicalDocument):
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Native extraction failed to produce a CanonicalDocument.",
                )
            doc = native_res.data
            base_provenance = native_res.provenance

        # Check if document has text or tables; if empty and pages exist, request OCR
        has_content = bool(doc.text.strip()) or any(len(p.tables) > 0 for p in doc.pages)
        if not has_content and len(doc.pages) > 0:
            return Result(
                data=doc,
                next_requirement="ocr",
            )

        # 2. Bank Statement Detection (timed in Darpana)
        det_scope = (
            self._darpana.time_scope(
                context=context,
                phase_name="bank_detection",
                component="shakti.bank_statements",
            )
            if self._darpana is not None
            else nullcontext()
        )
        with det_scope:
            detection = detect_bank_statement(doc, banks_dir=self._banks_dir)

        if not detection.is_bank_statement:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Document is not identified as a bank statement (reasons: {'; '.join(detection.reasons)}).",
            )

        # 3. Process Tables and Extract Transactions
        statements: list[BankStatement] = []
        raw_transactions: list[Transaction] = []

        bank_name = detection.bank_name or "Unknown Bank"
        profile_id = detection.matched_profile or "generic"

        all_tables: list[tuple[int, TableData]] = []
        for p_idx, p in enumerate(doc.pages):
            for t in p.tables:
                all_tables.append((p_idx + 1, t))
        for t in doc.tables:
            if not any(t == existing[1] for existing in all_tables):
                all_tables.append((1, t))

        # Fallback text parsing if needed
        if doc.text:
            import csv
            try:
                reader = csv.reader(io.StringIO(doc.text))
                all_rows = [r for r in reader if any(cell.strip() for cell in r)]
                for r_idx, r in enumerate(all_rows):
                    r_str = " ".join(str(c).lower() for c in r)
                    if ("date" in r_str or "txn" in r_str) and ("debit" in r_str or "credit" in r_str or "balance" in r_str):
                        headers = tuple(str(c) for c in all_rows[r_idx])
                        data_rows = tuple(tuple(str(c) for c in row) for row in all_rows[r_idx:])
                        all_tables.append((1, TableData(name="text_table", headers=headers, rows=data_rows)))
                        break
            except Exception:
                pass

        opening_balance: Decimal | None = None
        closing_balance: Decimal | None = None

        for page_num, table in all_tables:
            if not table.rows:
                continue

            # Find header row index
            header_row_idx: int | None = None
            for r_i, r in enumerate(table.rows):
                r_str = " ".join(str(c).lower() for c in r)
                if ("date" in r_str or "txn" in r_str) and ("debit" in r_str or "credit" in r_str or "balance" in r_str):
                    header_row_idx = r_i
                    break

            if header_row_idx is None:
                continue

            header_row = [str(c) for c in table.rows[header_row_idx]]
            mappings = self._mapper.map_headers(header_row, profile_id=profile_id)
            mapping_dict = {m.canonical_field: m.column_index for m in mappings}

            date_col = mapping_dict.get("date")
            desc_col = mapping_dict.get("description")
            debit_col = mapping_dict.get("debit")
            credit_col = mapping_dict.get("credit")
            bal_col = mapping_dict.get("balance")
            ref_col = mapping_dict.get("reference_number")
            chq_col = mapping_dict.get("cheque_number")

            if date_col is None or (debit_col is None and credit_col is None and bal_col is None):
                continue

            for row_idx, row in enumerate(table.rows[header_row_idx + 1:], start=header_row_idx + 1):
                row_cells = [str(c) for c in row]
                row_type = classify_row(row_cells, date_col_idx=date_col)

                if row_type == RowType.OPENING_BALANCE:
                    raw_bal = row_cells[bal_col] if bal_col is not None and bal_col < len(row_cells) else None
                    parsed_bal = parse_decimal_amount(raw_bal)
                    if parsed_bal is not None:
                        opening_balance = parsed_bal
                    continue

                if row_type == RowType.CLOSING_BALANCE:
                    raw_bal = row_cells[bal_col] if bal_col is not None and bal_col < len(row_cells) else None
                    parsed_bal = parse_decimal_amount(raw_bal)
                    if parsed_bal is not None:
                        closing_balance = parsed_bal
                    continue

                if row_type != RowType.TRANSACTION:
                    continue

                # Parse date
                raw_date = row_cells[date_col] if date_col < len(row_cells) else None
                tx_date = parse_date(raw_date)
                if tx_date is None:
                    continue

                # Parse description
                tx_desc = row_cells[desc_col].strip() if desc_col is not None and desc_col < len(row_cells) else ""

                # Parse amounts
                raw_debit = row_cells[debit_col] if debit_col is not None and debit_col < len(row_cells) else None
                raw_credit = row_cells[credit_col] if credit_col is not None and credit_col < len(row_cells) else None
                raw_bal = row_cells[bal_col] if bal_col is not None and bal_col < len(row_cells) else None

                tx_debit = parse_decimal_amount(raw_debit)
                tx_credit = parse_decimal_amount(raw_credit)
                tx_bal = parse_decimal_amount(raw_bal)

                tx_ref = row_cells[ref_col].strip() if ref_col is not None and ref_col < len(row_cells) else None
                tx_chq = row_cells[chq_col].strip() if chq_col is not None and chq_col < len(row_cells) else None

                prov = ProvenanceRecord(
                    source_input_id=request.inputs[0].input_id if request.inputs else None,
                    capability_id="bank_statements",
                    stage="bank_extraction",
                    page_number=page_num,
                    evidence={"row_index": row_idx + 1, "raw_row": row_cells},
                )

                raw_transactions.append(
                    Transaction(
                        transaction_date=tx_date,
                        description=tx_desc,
                        bank_name=bank_name,
                        reference_number=tx_ref,
                        cheque_number=tx_chq,
                        debit=tx_debit,
                        credit=tx_credit,
                        running_balance=tx_bal,
                        account_number=detection.account_number,
                        account_holder_name=detection.account_holder,
                        provenance=(prov,),
                    )
                )

        # 4. Deduplicate Transactions
        dedup_res = deduplicate_transactions(raw_transactions)

        # 5. Build and Validate BankStatement
        raw_statement = BankStatement(
            bank_name=bank_name,
            bank_profile=profile_id,
            account_number=detection.account_number,
            account_holder=detection.account_holder,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            transactions=dedup_res.unique_transactions,
            provenance=base_provenance,
        )

        validated_statement = validate_statement_balances(raw_statement)
        statements.append(validated_statement)

        # 6. Consolidate and Generate Artifacts
        consolidation = consolidate_statements(statements)
        parquet_payload = build_parquet_artifact(consolidation)
        xlsx_payload = build_xlsx_artifact(consolidation)

        return Result(
            data=consolidation,
            artifact_payloads=(parquet_payload, xlsx_payload),
            provenance=base_provenance,
            warnings=tuple(WarningRecord(code=i.code, message=i.message, stage="validation") for i in consolidation.issues),
        )
