"""Deterministic Deduplicator for Bank Statement Transactions."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from sarathi.shakti.bank_statements.models import (
    DuplicateDecision,
    Transaction,
    ValidationIssue,
    ValidationStatus,
)

_PLACEHOLDER_REFS = frozenset({"", "-", "--", "---", "na", "n/a", "n.a.", "none", "nil", "null"})


def _clean_ref(val: str | None) -> str:
    s = (val or "").strip()
    return "" if s.lower() in _PLACEHOLDER_REFS else s


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    """Result of transaction deduplication."""

    unique_transactions: tuple[Transaction, ...]
    duplicates: tuple[tuple[Transaction, Transaction, DuplicateDecision, str], ...]


def deduplicate_transactions(transactions: Sequence[Transaction]) -> DeduplicationResult:
    """Deduplicate transactions preserving original chronological order and provenance.

    Follows the canonical Bank Veda:
    - PROVEN_DUPLICATE: Matches on account, date, amount, description, AND (reference or running balance).
      The duplicate is collapsed, and source provenance is merged into the surviving transaction.
    - PROBABLE_DUPLICATE: Matches on account, date, amount, and description, but lacks both reference
      and running balance. Both transactions are preserved in unique_transactions, and a non-destructive
      audit warning is recorded.
    """
    unique: list[Transaction] = []
    duplicates: list[tuple[Transaction, Transaction, DuplicateDecision, str]] = []

    candidates_by_core: dict[tuple[str, object, Decimal | None, Decimal | None], list[int]] = {}
    candidates_by_ref: dict[tuple[tuple, str], list[int]] = {}
    candidates_by_bal: dict[tuple[tuple, Decimal], list[int]] = {}
    candidates_by_desc: dict[tuple[tuple, str], list[int]] = {}
    candidates_no_ref: dict[tuple, list[int]] = {}
    doc_surrogates: dict[str, str] = {}

    def _register_candidate(idx: int, t: Transaction, c_key: tuple) -> None:
        candidates_by_core.setdefault(c_key, []).append(idx)
        ref = _clean_ref(t.reference_number) or _clean_ref(t.cheque_number)
        if ref:
            candidates_by_ref.setdefault((c_key, ref), []).append(idx)
        else:
            candidates_no_ref.setdefault(c_key, []).append(idx)
        if t.running_balance is not None:
            candidates_by_bal.setdefault((c_key, t.running_balance), []).append(idx)
        desc = t.description.strip()
        if desc:
            candidates_by_desc.setdefault((c_key, desc), []).append(idx)

    for tx in transactions:
        # Determine account identifier without global fallback
        if tx.account_identity and tx.account_identity.account_fingerprint:
            acc_str = tx.account_identity.account_fingerprint
        else:
            doc_id = tx.provenance[0].source_input_id if tx.provenance and tx.provenance[0].source_input_id else None
            if doc_id:
                if doc_id not in doc_surrogates:
                    doc_surrogates[doc_id] = f"surrogate_doc_{doc_id}"
                acc_str = doc_surrogates[doc_id]
            else:
                tx_material = f"{tx.transaction_date}_{tx.debit}_{tx.credit}_{tx.description}"
                tx_hash = hashlib.sha256(tx_material.encode("utf-8")).hexdigest()[:12]
                acc_str = f"surrogate_orphan_{tx_hash}"

        core_key = (acc_str, tx.transaction_date, tx.debit, tx.credit)
        all_core_indices = candidates_by_core.get(core_key, [])

        tx_desc = tx.description.strip()
        tx_ref = _clean_ref(tx.reference_number) or _clean_ref(tx.cheque_number)

        if len(all_core_indices) <= 20:
            candidate_indices = all_core_indices
        else:
            # High-cardinality candidate pruning by strong signals
            pruned_set: set[int] = set()
            if tx_ref:
                # If transaction has an explicit reference, it can only match candidates with the SAME reference
                # or unreferenced candidates (potential asymmetric reference enrichment)
                pruned_set.update(candidates_by_ref.get((core_key, tx_ref), []))
                pruned_set.update(candidates_no_ref.get(core_key, []))
            else:
                if tx.running_balance is not None:
                    pruned_set.update(candidates_by_bal.get((core_key, tx.running_balance), []))
                if tx_desc:
                    pruned_set.update(candidates_by_desc.get((core_key, tx_desc), []))
                pruned_set.update(candidates_no_ref.get(core_key, []))
            candidate_indices = sorted(pruned_set)

        matched = False

        def _check_candidate(existing: Transaction) -> tuple[bool, bool, bool, int]:
            ex_desc = existing.description.strip()
            ex_ref = _clean_ref(existing.reference_number) or _clean_ref(existing.cheque_number)
            desc_matches = ex_desc == tx_desc
            sim_ratio = 100 if desc_matches else 0
            contradiction = False

            if (
                existing.transaction_time is not None
                and tx.transaction_time is not None
                and existing.transaction_time != tx.transaction_time
            ):
                contradiction = True

            if (
                existing.currency is not None
                and tx.currency is not None
                and existing.currency.strip().upper() != tx.currency.strip().upper()
            ):
                contradiction = True

            if ex_ref and tx_ref and ex_ref != tx_ref:
                contradiction = True

            if (
                existing.running_balance is not None
                and tx.running_balance is not None
                and existing.running_balance != tx.running_balance
            ):
                contradiction = True

            is_near_desc = False
            if not desc_matches and not (ex_ref and tx_ref and ex_ref == tx_ref):
                if not ex_ref and not tx_ref:
                    try:
                        from rapidfuzz import fuzz

                        sim_ratio = int(fuzz.token_sort_ratio(ex_desc, tx_desc))
                    except ImportError:
                        import difflib

                        t1 = " ".join(sorted(ex_desc.lower().split()))
                        t2 = " ".join(sorted(tx_desc.lower().split()))
                        sim_ratio = int(difflib.SequenceMatcher(None, t1, t2).ratio() * 100)

                    if sim_ratio >= 80:
                        is_near_desc = True
                    else:
                        contradiction = True
                else:
                    contradiction = True

            ex_doc_id = (
                existing.provenance[0].source_input_id
                if existing.provenance and existing.provenance[0].source_input_id
                else None
            )
            tx_doc_id = (
                tx.provenance[0].source_input_id
                if tx.provenance and tx.provenance[0].source_input_id
                else None
            )
            ex_stmt_id = existing.statement_id or (existing.metadata.get("statement_id") if existing.metadata else None)
            tx_stmt_id = tx.statement_id or (tx.metadata.get("statement_id") if tx.metadata else None)

            is_explicit_cross_statement = bool(
                (ex_doc_id and tx_doc_id and ex_doc_id != tx_doc_id)
                or (ex_stmt_id and tx_stmt_id and ex_stmt_id != tx_stmt_id)
            )
            is_same_statement = bool(
                (ex_doc_id and tx_doc_id and ex_doc_id == tx_doc_id)
                or (ex_stmt_id and tx_stmt_id and ex_stmt_id == tx_stmt_id)
            )

            # Within the same statement, distinct sequence rows are inherently distinct transactions
            # unless a verified matching reference number proves duplicate extraction (e.g. repeated table header).
            if is_same_statement and existing.sequence_id is not None and tx.sequence_id is not None:
                if existing.sequence_id != tx.sequence_id and not (ex_ref and tx_ref and ex_ref == tx_ref):
                    contradiction = True

            if contradiction:
                return False, False, True, sim_ratio

            has_matching_ref = bool(ex_ref and tx_ref and ex_ref == tx_ref)
            has_matching_bal = bool(
                existing.running_balance is not None
                and tx.running_balance is not None
                and existing.running_balance == tx.running_balance
            )

            # Proven duplicate requires exact description match or matching reference numbers:
            # A fuzzy-only near description can NEVER be proven; it is strictly probable.
            is_proven = has_matching_ref or (
                desc_matches and has_matching_bal and (
                    (bool(ex_ref) != bool(tx_ref))
                    or is_explicit_cross_statement
                )
            )
            is_probable = (desc_matches or is_near_desc) and not is_proven
            return is_proven, is_probable, False, sim_ratio

        # Pass 1: scan all candidates for proven duplicates first
        for existing_idx in candidate_indices:
            existing = unique[existing_idx]
            is_proven, _, contradiction, _ = _check_candidate(existing)
            if not contradiction and is_proven:
                merged_provenance = existing.provenance + tuple(
                    p for p in tx.provenance if p not in existing.provenance
                )
                surviving = replace(
                    existing,
                    transaction_time=existing.transaction_time or tx.transaction_time,
                    reference_number=existing.reference_number or tx.reference_number,
                    cheque_number=existing.cheque_number or tx.cheque_number,
                    running_balance=existing.running_balance if existing.running_balance is not None else tx.running_balance,
                    currency=existing.currency or tx.currency,
                    provenance=merged_provenance,
                    posting_date=existing.posting_date or tx.posting_date,
                    value_date=existing.value_date or tx.value_date,
                    transaction_datetime=existing.transaction_datetime or tx.transaction_datetime,
                    statement_id=existing.statement_id or tx.statement_id,
                    transaction_id=existing.transaction_id or tx.transaction_id,
                    raw_description=existing.raw_description or tx.raw_description,
                    raw_reference=existing.raw_reference or tx.raw_reference,
                    source_input_id=existing.source_input_id or tx.source_input_id,
                    page_number=existing.page_number if existing.page_number is not None else tx.page_number,
                    row_index=existing.row_index if existing.row_index is not None else tx.row_index,
                    input_location=existing.input_location or tx.input_location,
                    transaction_mode=existing.transaction_mode or tx.transaction_mode,
                )
                unique[existing_idx] = surviving

                # Synchronize secondary candidate indices if surviving acquired new reference or balance
                surv_ref = _clean_ref(surviving.reference_number) or _clean_ref(surviving.cheque_number)
                ex_clean_ref = _clean_ref(existing.reference_number) or _clean_ref(existing.cheque_number)
                if surv_ref and surv_ref != ex_clean_ref:
                    candidates_by_ref.setdefault((core_key, surv_ref), []).append(existing_idx)
                    no_ref_list = candidates_no_ref.get(core_key, [])
                    if existing_idx in no_ref_list:
                        no_ref_list.remove(existing_idx)
                if surviving.running_balance is not None and surviving.running_balance != existing.running_balance:
                    candidates_by_bal.setdefault((core_key, surviving.running_balance), []).append(existing_idx)

                duplicates.append(
                    (
                        existing,
                        tx,
                        DuplicateDecision.PROVEN_DUPLICATE,
                        "Matching core fields and verified strong signal (reference or running balance).",
                    )
                )
                matched = True
                break

        # Pass 2: fall back to probable duplicate matching if no proven duplicate was found
        if not matched:
            for existing_idx in candidate_indices:
                existing = unique[existing_idx]
                _, is_probable, contradiction, sim_ratio = _check_candidate(existing)
                if not contradiction and is_probable:
                    is_near_only = sim_ratio < 100
                    warn_msg = (
                        f"Near-duplicate narration ({sim_ratio}% similarity) without reference number or running balance."
                        if is_near_only
                        else "Identical date, amount, and narration without reference number or running balance."
                    )
                    warn_issue = ValidationIssue(
                        code="PROBABLE_DUPLICATE_TRANSACTION",
                        message=warn_msg,
                        severity="warning",
                        context={
                            "similarity_ratio": sim_ratio,
                            "existing_description": existing.description,
                            "new_description": tx.description,
                        },
                    )
                    new_status = (
                        ValidationStatus.WARNING
                        if tx.status != ValidationStatus.INVALID
                        else ValidationStatus.INVALID
                    )
                    tx_with_issue = replace(
                        tx,
                        status=new_status,
                        issues=tx.issues + (warn_issue,),
                    )
                    duplicates.append(
                        (
                            existing,
                            tx,
                            DuplicateDecision.PROBABLE_DUPLICATE,
                            warn_msg,
                        )
                    )
                    new_idx = len(unique)
                    unique.append(tx_with_issue)
                    _register_candidate(new_idx, tx_with_issue, core_key)
                    matched = True
                    break

        if not matched:
            new_idx = len(unique)
            unique.append(tx)
            _register_candidate(new_idx, tx, core_key)

    return DeduplicationResult(
        unique_transactions=tuple(unique),
        duplicates=tuple(duplicates),
    )
