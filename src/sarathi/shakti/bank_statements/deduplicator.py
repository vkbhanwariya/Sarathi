"""Deterministic Deduplicator for Bank Statement Transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sarathi.shakti.bank_statements.models import (
    DuplicateDecision,
    Transaction,
)


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    """Result of transaction deduplication."""

    unique_transactions: tuple[Transaction, ...]
    duplicates: tuple[tuple[Transaction, Transaction, DuplicateDecision, str], ...]


def deduplicate_transactions(transactions: Sequence[Transaction]) -> DeduplicationResult:
    """Deduplicate transactions preserving original chronological order and provenance."""
    unique: list[Transaction] = []
    duplicates: list[tuple[Transaction, Transaction, DuplicateDecision, str]] = []

    # Map signatures to indices in unique list to support merging provenance into surviving transaction
    seen_signatures: dict[str, int] = {}
    doc_surrogates: dict[str, str] = {}

    for tx in transactions:
        # Determine account identifier without global fallback
        if tx.account_identity and tx.account_identity.account_fingerprint:
            acc_str = tx.account_identity.account_fingerprint
        else:
            # Generate distinct session-scoped surrogate ID per document provenance
            doc_id = tx.provenance[0].source_input_id if tx.provenance and tx.provenance[0].source_input_id else None
            if doc_id:
                if doc_id not in doc_surrogates:
                    doc_surrogates[doc_id] = f"surrogate_doc_{doc_id}"
                acc_str = doc_surrogates[doc_id]
            else:
                # Orphan without document: isolate by transaction id to avoid false collisions
                acc_str = f"surrogate_orphan_{id(tx)}"

        # Generate strict signature: account_fingerprint + date + debit + credit + ref + balance
        amt_str = f"D:{tx.debit}" if tx.debit is not None else f"C:{tx.credit}"
        bal_str = f"B:{tx.running_balance}" if tx.running_balance is not None else "B:None"
        ref_val = tx.reference_number or tx.cheque_number or ""
        ref_str = f"R:{ref_val}"

        strict_sig = f"{acc_str}_{tx.transaction_date}_{amt_str}_{bal_str}_{ref_str}_{tx.description}"

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
            # Merge source reference provenance into the surviving transaction
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
        else:
            seen_signatures[strict_sig] = len(unique)
            unique.append(tx)

    return DeduplicationResult(
        unique_transactions=tuple(unique),
        duplicates=tuple(duplicates),
    )
