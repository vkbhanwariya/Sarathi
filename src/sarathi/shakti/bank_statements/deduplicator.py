"""Deterministic Deduplicator for Bank Statement Transactions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
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

    seen_signatures: dict[str, int] = {}
    seen_content_signatures: dict[str, int] = {}
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

        amt_str = f"D:{tx.debit}" if tx.debit is not None else f"C:{tx.credit}"
        has_ref = bool(tx.reference_number or tx.cheque_number)
        has_bal = tx.running_balance is not None

        ref_val = tx.reference_number or tx.cheque_number or ""
        ref_str = f"R:{ref_val}"
        bal_str = f"B:{tx.running_balance}" if has_bal else "B:None"

        # Content-only signature (date, amount, description)
        content_sig = f"{acc_str}_{tx.transaction_date}_{amt_str}_{tx.description.strip()}"

        if has_ref or has_bal:
            # Full strict signature with balance and/or reference
            strict_sig = f"{content_sig}_{bal_str}_{ref_str}"
            if strict_sig in seen_signatures:
                existing_idx = seen_signatures[strict_sig]
                existing = unique[existing_idx]
                duplicates.append(
                    (
                        existing,
                        tx,
                        DuplicateDecision.PROVEN_DUPLICATE,
                        "Exact match on date, amount, balance, reference, and description.",
                    )
                )
                merged_provenance = existing.provenance + tuple(p for p in tx.provenance if p not in existing.provenance)
                surviving = Transaction(
                    transaction_date=existing.transaction_date,
                    description=existing.description,
                    bank_name=existing.bank_name,
                    transaction_time=existing.transaction_time,
                    reference_number=existing.reference_number,
                    cheque_number=existing.cheque_number,
                    debit=existing.debit,
                    credit=existing.credit,
                    running_balance=existing.running_balance,
                    account_identity=existing.account_identity,
                    currency=existing.currency,
                    status=existing.status,
                    issues=existing.issues,
                    provenance=merged_provenance,
                    metadata=existing.metadata,
                    posting_date=existing.posting_date,
                    value_date=existing.value_date,
                    transaction_datetime=existing.transaction_datetime,
                    sequence_id=existing.sequence_id,
                )
                unique[existing_idx] = surviving
                continue
            else:
                seen_signatures[strict_sig] = len(unique)
        else:
            # Without reference or balance, identical transactions are PROBABLE_DUPLICATE candidates
            if content_sig in seen_content_signatures:
                existing_idx = seen_content_signatures[content_sig]
                existing = unique[existing_idx]
                duplicates.append(
                    (
                        existing,
                        tx,
                        DuplicateDecision.PROBABLE_DUPLICATE,
                        "Match on date, amount, and description without reference number or running balance.",
                    )
                )
                # Keep both in unique list per Bank Veda; add non-destructive audit warning to candidate
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
                unique.append(tx_with_issue)
                continue
            else:
                seen_content_signatures[content_sig] = len(unique)

        seen_content_signatures[content_sig] = len(unique)
        unique.append(tx)

    return DeduplicationResult(
        unique_transactions=tuple(unique),
        duplicates=tuple(duplicates),
    )
