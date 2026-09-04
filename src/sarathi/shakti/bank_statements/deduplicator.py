"""Deterministic Deduplicator for Bank Statement Transactions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from sarathi.shakti.bank_statements.models import (
    DuplicateDecision,
    Transaction,
    ValidationIssue,
)


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
    doc_surrogates: dict[str, str] = {}

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
        candidate_indices = candidates_by_core.get(core_key, [])

        tx_desc = tx.description.strip()
        tx_ref = (tx.reference_number or tx.cheque_number or "").strip()

        matched = False

        for existing_idx in candidate_indices:
            existing = unique[existing_idx]
            ex_desc = existing.description.strip()
            ex_ref = (existing.reference_number or existing.cheque_number or "").strip()

            desc_matches = (ex_desc == tx_desc)
            contradiction = False

            if ex_ref and tx_ref and ex_ref != tx_ref:
                contradiction = True

            if (
                existing.running_balance is not None
                and tx.running_balance is not None
                and existing.running_balance != tx.running_balance
            ):
                contradiction = True

            if not desc_matches and not (ex_ref and tx_ref and ex_ref == tx_ref):
                contradiction = True

            if contradiction:
                continue

            has_matching_ref = bool(ex_ref and tx_ref and ex_ref == tx_ref)
            has_matching_bal = bool(
                existing.running_balance is not None
                and tx.running_balance is not None
                and existing.running_balance == tx.running_balance
            )

            if has_matching_ref or has_matching_bal:
                merged_provenance = existing.provenance + tuple(p for p in tx.provenance if p not in existing.provenance)
                surviving = Transaction(
                    transaction_date=existing.transaction_date,
                    description=existing.description,
                    bank_name=existing.bank_name,
                    transaction_time=existing.transaction_time or tx.transaction_time,
                    reference_number=existing.reference_number or tx.reference_number,
                    cheque_number=existing.cheque_number or tx.cheque_number,
                    debit=existing.debit,
                    credit=existing.credit,
                    running_balance=existing.running_balance if existing.running_balance is not None else tx.running_balance,
                    account_identity=existing.account_identity,
                    currency=existing.currency or tx.currency,
                    status=existing.status,
                    issues=existing.issues,
                    provenance=merged_provenance,
                    metadata=existing.metadata,
                    posting_date=existing.posting_date or tx.posting_date,
                    value_date=existing.value_date or tx.value_date,
                    transaction_datetime=existing.transaction_datetime or tx.transaction_datetime,
                    sequence_id=existing.sequence_id,
                )
                unique[existing_idx] = surviving
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
            else:
                if desc_matches:
                    warn_issue = ValidationIssue(
                        code="PROBABLE_DUPLICATE_TRANSACTION",
                        message="Identical date, amount, and narration without reference number or running balance.",
                        severity="warning",
                    )
                    tx_with_issue = Transaction(
                        transaction_date=tx.transaction_date,
                        description=tx.description,
                        bank_name=tx.bank_name,
                        transaction_time=tx.transaction_time,
                        reference_number=tx.reference_number,
                        cheque_number=tx.cheque_number,
                        debit=tx.debit,
                        credit=tx.credit,
                        running_balance=tx.running_balance,
                        account_identity=tx.account_identity,
                        currency=tx.currency,
                        status=tx.status,
                        issues=tx.issues + (warn_issue,),
                        provenance=tx.provenance,
                        metadata=tx.metadata,
                        posting_date=tx.posting_date,
                        value_date=tx.value_date,
                        transaction_datetime=tx.transaction_datetime,
                        sequence_id=tx.sequence_id,
                    )
                    duplicates.append(
                        (
                            existing,
                            tx,
                            DuplicateDecision.PROBABLE_DUPLICATE,
                            "Match on date, amount, and description without reference number or running balance.",
                        )
                    )
                    new_idx = len(unique)
                    unique.append(tx_with_issue)
                    candidates_by_core.setdefault(core_key, []).append(new_idx)
                    matched = True
                    break

        if not matched:
            new_idx = len(unique)
            unique.append(tx)
            candidates_by_core.setdefault(core_key, []).append(new_idx)

    return DeduplicationResult(
        unique_transactions=tuple(unique),
        duplicates=tuple(duplicates),
    )
