"""Bank Statement Consolidation Executable Capability for Sarathi."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
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
from sarathi.shakti.bank_statements.bank_registry import get_bank_registry
from sarathi.shakti.bank_statements.converter import (
    parse_balance_amount,
    parse_date,
    parse_decimal_amount,
    parse_time,
)
from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.detector import detect_bank_statement, load_bank_profiles
from sarathi.shakti.bank_statements.mapper import HeaderMapper, extract_sample_data_rows, load_bank_profile_yaml
from sarathi.shakti.bank_statements.models import (
    AccountIdentity,
    BankStatement,
    Transaction,
    ValidationIssue,
    ValidationStatus,
    create_account_identity,
    generate_statement_id,
)
from sarathi.shakti.bank_statements.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.bank_statements.row_classifier import RowType, classify_row
from sarathi.shakti.bank_statements.table_locator import (
    TableType,
    classify_table,
    find_header_row_index,
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
_PLACEHOLDER_MARKERS = frozenset({"", "-", "--", "---", "na", "n/a", "n.a.", "none", "nil", "null"})


def _clean_placeholder_text(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in _PLACEHOLDER_MARKERS:
        return None
    return s


def compute_document_fingerprint(doc: CanonicalDocument) -> str:
    """Derive a stable 12-char fingerprint for a CanonicalDocument based on factual content and metadata."""
    if doc.metadata:
        if "file_fingerprint" in doc.metadata:
            return str(doc.metadata["file_fingerprint"])[:12]
        if "source_hash" in doc.metadata:
            return str(doc.metadata["source_hash"])[:12]

    hasher = hashlib.sha256()
    for p in doc.pages:
        if p.text:
            hasher.update(p.text.encode("utf-8", errors="replace"))
    if doc.text:
        hasher.update(doc.text.encode("utf-8", errors="replace"))
    for t in doc.tables:
        if t.headers:
            hasher.update(" ".join(str(h) for h in t.headers).encode("utf-8", errors="replace"))
        for r in t.rows:
            hasher.update(" ".join(str(c) for c in r).encode("utf-8", errors="replace"))
    return hasher.hexdigest()[:12]


def detect_statement_currency(doc: CanonicalDocument, profile_cfg: Mapping[str, Any] | None = None) -> str:
    """Detect currency from profile config, document metadata, or explicit header labels.

    All Indian bank statements operate in INR. Narration or description mentioning foreign
    currencies (e.g. international transactions with exchange rates) does not alter the
    underlying INR denomination of debit, credit, or balance columns.
    """
    if profile_cfg and profile_cfg.get("currency"):
        return str(profile_cfg["currency"]).strip().upper()

    # 1. Authoritative metadata fields on CanonicalDocument
    if doc.metadata and doc.metadata.get("currency"):
        return str(doc.metadata["currency"]).strip().upper()

    # 2. Explicit labeled currency field in statement header block
    header_block = ""
    if doc.text:
        header_block += doc.text[:1000]
    if doc.pages and doc.pages[0].text:
        header_block += " " + doc.pages[0].text[:1000]

    m_curr = re.search(r"\b(?:currency|curr|denominated\s+in)\s*[:\-]?\s*([A-Z]{3})\b", header_block, re.IGNORECASE)
    if m_curr:
        return m_curr.group(1).upper()

    # 3. Explicit table column header currency indicators
    table_headers_text = " ".join(
        " ".join(str(h) for h in t.headers) for t in doc.tables if t.headers
    ).lower()

    if table_headers_text:
        m_tbl = re.search(r"\b(inr|usd|eur|gbp|sgd|cad|aed)\b", table_headers_text)
        if m_tbl:
            return m_tbl.group(1).upper()

    return "INR"


def _detect_transaction_mode(description: str) -> str:
    """Classify transaction mode from narration using canonical patterns."""
    desc_upper = description.upper()
    if "UPI" in desc_upper:
        return "UPI"
    if "NEFT" in desc_upper:
        return "NEFT"
    if "RTGS" in desc_upper:
        return "RTGS"
    if "IMPS" in desc_upper:
        return "IMPS"
    if any(k in desc_upper for k in ("ATM", "CASH", "CWDR")):
        return "CASH"
    if any(k in desc_upper for k in ("CHQ", "CHEQUE", "CLG", "CLEARING", "CTS")):
        return "CHEQUE"
    if any(k in desc_upper for k in ("CHARGE", "CHRG", "FEE", "TAX", "GST", "INT.COLL")):
        return "CHARGES"
    if re.search(r"\b(?:INT|INTEREST)\b", desc_upper):
        return "INTEREST"
    return "TRANSFER"


class BankStatementCapability:
    """Executable capability for bank statement consolidation."""

    def __init__(self, darpana: Darpana | None = None, banks_dir: Path | None = None) -> None:
        self.declaration = CAPABILITY_DECLARATION
        self._darpana = darpana
        self._banks_dir = banks_dir.resolve() if banks_dir is not None else _CANONICAL_BANKS_DIR
        self._mapper = HeaderMapper(banks_dir=self._banks_dir)
        self._profiles = {p.get("profile_id"): p for p in load_bank_profiles(self._banks_dir)}
        common_path = self._banks_dir / "common.yaml"
        self._common_config = load_bank_profile_yaml(common_path) if common_path.exists() else {}
        catalog_path = self._banks_dir / "banks_catalog.json"
        self._registry = get_bank_registry(catalog_path if catalog_path.exists() else None)

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

            init_bank_name = (
                self._registry.identify_bank(
                    text=doc.text,
                    ifsc=detection.ifsc or (detection.account_identity.ifsc if detection.account_identity else None),
                    candidate_name=detection.bank_name,
                )
                or "Unknown Bank"
            )

            doc_metadata: dict[str, Any] = {}
            raw_txns, open_bal, close_bal, doc_issues = self._extract_table_data(
                doc,
                request,
                detection.matched_profile,
                init_bank_name,
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
            raw_bank_name = (
                self._profiles.get(final_profile, {}).get("bank_name")
                if (final_profile and final_profile in self._profiles)
                else init_bank_name
            )

            ifsc_val = detection.ifsc or (detection.account_identity.ifsc if detection.account_identity else None)
            identified = self._registry.identify_bank(
                text=doc.text,
                ifsc=ifsc_val,
                candidate_name=raw_bank_name,
            )
            final_bank_name = identified or "Unknown Bank"

            if final_bank_name == "Unknown Bank":
                doc_issues.append(
                    ValidationIssue(
                        code="UNKNOWN_BANK",
                        message="Bank could not be identified against the compiled list of Indian banks. Statement marked as 'Unknown Bank'.",
                        severity="warning",
                    )
                )

            # Ensure transactions and account identity carry the verified canonical bank name
            if raw_txns and any(tx.bank_name != final_bank_name for tx in raw_txns):
                raw_txns = [replace(tx, bank_name=final_bank_name) for tx in raw_txns]
                dedup_res = deduplicate_transactions(raw_txns)

            final_account_identity = detection.account_identity
            if final_account_identity is not None and final_account_identity.bank_name != final_bank_name:
                final_account_identity = replace(
                    final_account_identity,
                    bank_name=final_bank_name,
                    bank_profile=final_profile,
                    ifsc=final_account_identity.ifsc or ifsc_val,
                )

            distinct_accounts = []
            seen_accs = set()
            for tx in dedup_res.unique_transactions:
                acc_key = tx.account_identity.account_fingerprint if tx.account_identity else None
                if acc_key and acc_key not in seen_accs:
                    seen_accs.add(acc_key)
                    distinct_accounts.append(tx.account_identity)

            if distinct_accounts:
                table_acc = distinct_accounts[0]
                if final_account_identity is None or not final_account_identity.account_fingerprint:
                    final_account_identity = table_acc
                else:
                    final_account_identity = replace(
                        final_account_identity,
                        bank_name=final_bank_name,
                        bank_profile=final_profile,
                        ifsc=table_acc.ifsc or final_account_identity.ifsc or ifsc_val,
                        account_holder=table_acc.account_holder or final_account_identity.account_holder,
                        account_type=table_acc.account_type or final_account_identity.account_type,
                    )

            doc_fp = compute_document_fingerprint(doc)
            doc_stmt_id = doc_metadata.get("statement_id") or generate_statement_id(
                bank_name=final_bank_name,
                account_identity=final_account_identity,
                doc_id=doc.source_input_id or getattr(doc, "document_id", None),
                document_fingerprint=doc_fp,
            )

            stmt_currency = detect_statement_currency(doc, self._profiles.get(final_profile))

            doc_metadata["successful_transactions"] = len(dedup_res.unique_transactions)
            doc_metadata["duplicate_transactions"] = len(dedup_res.duplicates)
            doc_metadata["raw_transactions"] = len(raw_txns)

            if len(distinct_accounts) > 1:
                scanned_by_acc = doc_metadata.get("scanned_rows_by_acc", {})
                boundaries_by_acc = doc_metadata.get("boundaries_by_acc", {})
                for acc_ident in distinct_accounts:
                    acc_txns = tuple(tx for tx in dedup_res.unique_transactions if tx.account_identity == acc_ident)
                    acc_meta = dict(doc_metadata)
                    acc_meta["successful_transactions"] = len(acc_txns)
                    acc_dups = sum(
                        1 for d in dedup_res.duplicates if d[0].account_identity == acc_ident
                    )
                    acc_meta["duplicate_transactions"] = acc_dups
                    acc_fp = acc_ident.account_fingerprint if acc_ident else None
                    if acc_fp and acc_fp in scanned_by_acc:
                        acc_meta["total_scanned_rows"] = scanned_by_acc[acc_fp]
                    else:
                        acc_meta["total_scanned_rows"] = len(acc_txns) + acc_dups
                    acc_stmt_id = generate_statement_id(
                        bank_name=final_bank_name,
                        account_identity=acc_ident,
                        doc_id=doc.source_input_id or getattr(doc, "document_id", None),
                        document_fingerprint=doc_fp,
                    )
                    acc_bounds = boundaries_by_acc.get(acc_fp, {}) if acc_fp else {}
                    acc_open = acc_bounds.get("opening")
                    acc_close = acc_bounds.get("closing")
                    statements.append(
                        validate_statement_balances(
                            BankStatement(
                                statement_id=acc_stmt_id,
                                bank_name=final_bank_name,
                                bank_profile=final_profile,
                                account_identity=acc_ident,
                                currency=stmt_currency,
                                ifsc=ifsc_val,
                                account_holder=acc_ident.account_holder if acc_ident else None,
                                account_type=acc_ident.account_type if acc_ident else None,
                                opening_balance=acc_open,
                                closing_balance=acc_close,
                                transactions=acc_txns,
                                issues=tuple(doc_issues),
                                provenance=doc_prov,
                                metadata=acc_meta,
                            )
                        )
                    )
            else:
                statement = validate_statement_balances(
                    BankStatement(
                        statement_id=doc_stmt_id,
                        bank_name=final_bank_name,
                        bank_profile=final_profile,
                        account_identity=final_account_identity,
                        currency=stmt_currency,
                        ifsc=ifsc_val,
                        account_holder=final_account_identity.account_holder if final_account_identity else None,
                        account_type=final_account_identity.account_type if final_account_identity else None,
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
            build_accounts_xlsx_artifact,
            build_parquet_artifact,
            build_transactions_xlsx_artifact,
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
            artifact_payloads=(
                build_parquet_artifact(consolidation),
                build_accounts_xlsx_artifact(consolidation),
                build_transactions_xlsx_artifact(consolidation),
            ),
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
        all_tables.extend(
            (t_idx + 1, t) for t_idx, t in enumerate(doc.tables) if not any(t == e[1] for e in all_tables)
        )

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

        doc_fp = compute_document_fingerprint(doc)
        statement_id = generate_statement_id(
            bank_name=bank_name,
            account_identity=account_identity,
            doc_id=doc.source_input_id or getattr(doc, "document_id", None),
            document_fingerprint=doc_fp,
        )
        if metadata is not None:
            metadata["statement_id"] = statement_id

        active_profile = self._profiles.get(profile_id or "", {})
        has_signed_semantics = bool(active_profile.get("signed_amounts", False))
        stmt_currency = detect_statement_currency(doc, active_profile)

        is_spreadsheet = bool(doc.tables and not doc.pages)

        # Resolve real human-friendly input filename from request inputs
        file_stem = None
        for inp in req.inputs:
            if inp.input_id == doc.source_input_id:
                if inp.display_name:
                    file_stem = Path(inp.display_name).stem
                elif inp.source_path:
                    file_stem = inp.source_path.stem
                break

        if not file_stem and req.inputs:
            first_inp = req.inputs[0]
            if first_inp.display_name:
                file_stem = Path(first_inp.display_name).stem
            elif first_inp.source_path:
                file_stem = first_inp.source_path.stem

        if not file_stem:
            raw_source_id = doc.source_input_id or getattr(doc, "document_id", None) or ""
            file_stem = Path(raw_source_id).stem if raw_source_id else "Statement"

        total_scanned_rows = 0
        best_header_score = 0.0
        scanned_rows_by_acc: dict[str, int] = {}
        boundaries_by_acc: dict[str, dict[str, Decimal]] = {}

        for page_num, table in all_tables:
            if not table.rows and not table.headers:
                continue

            if classify_table(table) != TableType.TRANSACTION_TABLE:
                continue

            hdr_idx = find_header_row_index(table)
            extracted_table = get_table_header_and_data_rows(table)
            if extracted_table is None:
                continue

            hdr_cells, data_rows = extracted_table
            sample_rows = extract_sample_data_rows(data_rows)
            hdr_offset = (hdr_idx + 2) if (hdr_idx is not None and hdr_idx >= 0) else 1
            total_scanned_rows += len(data_rows)

            tbl_account_number = None
            if table.name and re.match(r"^[A-Za-z0-9]{8,24}$", table.name.strip()):
                tbl_account_number = table.name.strip()

            if not tbl_account_number and table.headers:
                h_text = " ".join(str(c) for c in table.headers)
                m_acc = re.search(
                    r'["\']?(?:account\s*(?:no|number|num)?|ac\s*no)["\']?\s*(?:as|:|is|-)?\s*["\']?([A-Za-z0-9]{8,24})["\']?',
                    h_text,
                    re.IGNORECASE,
                )
                if m_acc:
                    tbl_account_number = m_acc.group(1).strip()

            tbl_account_holder = account_identity.account_holder if account_identity else None
            tbl_account_type = account_identity.account_type if account_identity else None

            if data_rows:
                for c_i, h in enumerate(hdr_cells):
                    h_clean = str(h).strip().lower()
                    if not tbl_account_number and re.search(r"\b(?:account|ac|acc)[_\s]*(?:no|num|number)?\b", h_clean):
                        cell_val = str(data_rows[0][c_i]).strip().strip('"\'')
                        if re.match(r"^[A-Za-z0-9]{8,24}$", cell_val):
                            tbl_account_number = cell_val
                    elif not tbl_account_holder and re.search(r"\b(?:acct[_\s]*name|account[_\s]*name|holder[_\s]*name|customer[_\s]*name)\b", h_clean):
                        cell_val = str(data_rows[0][c_i]).strip().strip('"\'')
                        if cell_val and len(cell_val) >= 3 and not cell_val.isdigit():
                            tbl_account_holder = cell_val
                    elif not tbl_account_type and re.search(r"\b(?:acct[_\s]*type|account[_\s]*type|scheme[_\s]*type)\b", h_clean):
                        cell_val = str(data_rows[0][c_i]).strip().strip('"\'')
                        if cell_val:
                            tbl_account_type = cell_val

            tbl_identity = (
                create_account_identity(
                    bank_name=bank_name,
                    raw_account_number=tbl_account_number,
                    account_holder=tbl_account_holder,
                    bank_profile=profile_id,
                    account_type=tbl_account_type,
                    ifsc=account_identity.ifsc if account_identity else None,
                )
                if tbl_account_number
                else account_identity
            )
            if tbl_identity and tbl_identity.account_fingerprint:
                scanned_rows_by_acc[tbl_identity.account_fingerprint] = (
                    scanned_rows_by_acc.get(tbl_identity.account_fingerprint, 0) + len(data_rows)
                )

            resolved_prof, best_mappings, map_score = self._mapper.resolve_best_profile(
                hdr_cells, candidate_profile=profile_id, sample_rows=sample_rows
            )
            if map_score > best_header_score:
                best_header_score = map_score
            if resolved_prof and resolved_prof != profile_id:
                active_profile = self._profiles.get(resolved_prof, {})
                has_signed_semantics = bool(active_profile.get("signed_amounts", False))
                if metadata is not None:
                    metadata["resolved_profile"] = resolved_prof

            mappings = {m.canonical_field: m.column_index for m in best_mappings}
            d_col, desc_col = mappings.get("date"), mappings.get("description")
            val_date_col, time_col = mappings.get("value_date"), mappings.get("time")
            posting_date_col = mappings.get("posting_date")
            dr_col, cr_col = mappings.get("debit"), mappings.get("credit")
            amt_col, dir_col = mappings.get("amount"), mappings.get("direction")
            b_col = mappings.get("balance")
            ref_col, chq_col = mappings.get("reference_number"), mappings.get("cheque_number")
            ref_source_header = next(
                (m.source_header for m in best_mappings if m.canonical_field == "reference_number"), ""
            )
            is_combined_ref_col = bool(re.search(r"\b(?:chq|cheque)\b", ref_source_header, re.IGNORECASE))

            date_supplied = "transaction_date"
            if d_col is None:
                if posting_date_col is not None:
                    d_col = posting_date_col
                    date_supplied = "posting_date"
                elif val_date_col is not None:
                    d_col = val_date_col
                    date_supplied = "value_date"

            if d_col is None or not (any(c is not None for c in (dr_col, cr_col, b_col)) or amt_col is not None):
                continue

            amt_indices = [c for c in (dr_col, cr_col, amt_col, b_col) if c is not None]
            table_txns: list[Transaction] = []

            for row_idx, row in enumerate(data_rows, start=1):
                row_cells = [str(c) if c is not None else "" for c in row]
                match classify_row(row_cells, date_col_idx=d_col, amount_col_indices=amt_indices):
                    case RowType.OPENING_BALANCE:
                        parsed_open = parse_balance_amount(_get_raw_cell(row, b_col))
                        if parsed_open is not None:
                            if open_bal is None:
                                open_bal = parsed_open
                            if tbl_identity and tbl_identity.account_fingerprint:
                                boundaries_by_acc.setdefault(tbl_identity.account_fingerprint, {})["opening"] = parsed_open
                    case RowType.CLOSING_BALANCE:
                        parsed_close = parse_balance_amount(_get_raw_cell(row, b_col))
                        if parsed_close is not None:
                            close_bal = parsed_close
                            if tbl_identity and tbl_identity.account_fingerprint:
                                boundaries_by_acc.setdefault(tbl_identity.account_fingerprint, {})["closing"] = parsed_close
                    case RowType.EOD_BALANCE:
                        eod_date = parse_date(_get_raw_cell(row, d_col))
                        eod_bal = parse_balance_amount(_get_raw_cell(row, b_col))
                        if eod_bal is None:
                            eod_bal = parse_balance_amount(_get_raw_cell(row, amt_col))
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

                        if time_col is not None:
                            tx_time = parse_time(_get_raw_cell(row, time_col))
                        else:
                            tx_time = parse_time(raw_date_val)

                        tx_val_date = (
                            parse_date(_get_raw_cell(row, val_date_col))
                            if val_date_col is not None
                            else (tx_date if date_supplied == "value_date" else None)
                        )
                        tx_posting_date = (
                            parse_date(_get_raw_cell(row, posting_date_col))
                            if posting_date_col is not None
                            else (tx_date if date_supplied == "posting_date" else None)
                        )

                        tx_debit = parse_decimal_amount(_get_raw_cell(row, dr_col))
                        if tx_debit is not None and tx_debit == Decimal("0"):
                            tx_debit = None
                        elif tx_debit is not None:
                            tx_debit = abs(tx_debit)

                        tx_credit = parse_decimal_amount(_get_raw_cell(row, cr_col))
                        if tx_credit is not None and tx_credit == Decimal("0"):
                            tx_credit = None
                        elif tx_credit is not None:
                            tx_credit = abs(tx_credit)

                        tx_bal = parse_balance_amount(_get_raw_cell(row, b_col))

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
                            is_both_blank = dr_col is not None or cr_col is not None
                            err_code = "BOTH_AMOUNTS_BLANK" if is_both_blank else "MISSING_AMOUNT"
                            err_msg = (
                                f"Row {row_idx}: Both debit and credit amounts are blank or zero."
                                if is_both_blank
                                else f"Row {row_idx}: Transaction amount direction could not be determined."
                            )
                            tx_iss = ValidationIssue(
                                code=err_code,
                                message=err_msg,
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
                        ref_raw = _get_cell(row_cells, ref_col)
                        ref_val = _clean_placeholder_text(ref_raw)
                        chq_raw = _get_cell(row_cells, chq_col)
                        chq_val = _clean_placeholder_text(chq_raw)
                        if ref_val:
                            repaired_utr, det_type, was_repaired = repair_utr(ref_val)
                            if was_repaired or det_type:
                                ref_val = repaired_utr

                        # If there is no dedicated cheque column, check if combined ref column holds a cheque identity
                        desc_raw = _get_cell(row_cells, desc_col) or ""
                        if chq_col is None and ref_val and not chq_val:
                            clean_ref = ref_val.strip()
                            is_chq_desc = bool(
                                re.search(r"\b(?:chq|cheque|clg|clearing|cts)\b", desc_raw, re.IGNORECASE)
                            )
                            is_chq_num = bool(re.match(r"^\d{6}$", clean_ref))
                            has_elec_kw = bool(
                                re.search(
                                    r"\b(?:upi|neft|rtgs|imps|atm|pos|card|salary|transfer|ach|ecs)\b",
                                    desc_raw,
                                    re.IGNORECASE,
                                )
                            )
                            if is_chq_desc:
                                chq_val = clean_ref
                                ref_val = None
                            elif is_combined_ref_col and is_chq_num and not has_elec_kw:
                                chq_val = clean_ref
                                ref_val = None

                        tx_meta: dict[str, Any] = {
                            "source_row_id": f"tx_{statement_id}_{current_sequence_id:04d}",
                        }
                        if date_supplied != "transaction_date":
                            tx_meta["date_supplied"] = date_supplied

                        sheet_prefix = "S" if is_spreadsheet else "P"
                        excel_row_num = (hdr_offset + row_idx) if is_spreadsheet else row_idx
                        input_loc = f"{file_stem}_{sheet_prefix}{page_num}_R{excel_row_num:02d}"
                        tx_mode = _detect_transaction_mode(desc_raw)

                        new_tx = Transaction(
                            statement_id=statement_id,
                            transaction_id=f"TXN-{current_sequence_id:04d}",
                            input_location=input_loc,
                            transaction_date=tx_date,
                            transaction_time=tx_time,
                            value_date=tx_val_date,
                            posting_date=tx_posting_date,
                            description=desc_raw,
                            bank_name=bank_name,
                            reference_number=ref_val,
                            cheque_number=chq_val,
                            debit=tx_debit,
                            credit=tx_credit,
                            running_balance=tx_bal,
                            account_identity=tbl_identity,
                            currency=stmt_currency,
                            status=tx_status,
                            issues=tuple(tx_issues),
                            provenance=(prov,),
                            metadata=tx_meta,
                            sequence_id=current_sequence_id,
                            raw_description=desc_raw,
                            raw_reference=ref_raw,
                            source_input_id=doc.source_input_id,
                            page_number=page_num,
                            row_index=row_idx,
                            transaction_mode=tx_mode,
                        )
                        raw_txns.append(new_tx)
                        table_txns.append(new_tx)

        if metadata is not None:
            metadata["total_scanned_rows"] = total_scanned_rows
            metadata["header_match_score"] = best_header_score
            metadata["source_file_stem"] = file_stem
            metadata["scanned_rows_by_acc"] = scanned_rows_by_acc
            metadata["boundaries_by_acc"] = boundaries_by_acc
            if eod_balances:
                metadata["eod_balances"] = tuple(eod_balances)
            if summary_rows:
                metadata["summary_rows"] = tuple(summary_rows)

        patterns = active_profile.get("metadata_patterns", {}) or self._common_config.get("metadata_patterns", {})
        if patterns:
            search_target = doc.text + " " + " ".join(p.text for p in doc.pages if p.text)
            if open_bal is None and "opening_balance" in patterns:
                m_open = re.search(patterns["opening_balance"], search_target, re.IGNORECASE)
                if m_open:
                    parsed_open = parse_balance_amount(m_open.group(1))
                    if parsed_open is not None:
                        open_bal = parsed_open

            if close_bal is None and "closing_balance" in patterns:
                m_close = re.search(patterns["closing_balance"], search_target, re.IGNORECASE)
                if m_close:
                    parsed_close = parse_balance_amount(m_close.group(1))
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
