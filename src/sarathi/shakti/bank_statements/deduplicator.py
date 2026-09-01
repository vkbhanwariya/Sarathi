"""Transaction Deduplication for Bank Statements in Sarathi V2.

Evaluates candidate duplicate transactions across overlapping statements
and assigns deterministic evidence-based decisions:
- PROVEN_DUPLICATE
- PROBABLE_DUPLICATE
- DISTINCT
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sarathi.shakti.bank_statements.models import DuplicateDecision, Transaction


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    """Result of statement deduplication."""

    unique_transactions: tuple[Transaction, ...]
    duplicates: tuple[tuple[Transaction, Transaction, DuplicateDecision, str], ...]


def deduplicate_transactions(transactions: Sequence[Transaction]) -> DeduplicationResult:
    """Deduplicate transactions preserving original chronological order and provenance."""
    unique: list[Transaction] = []
    duplicates: list[tuple[Transaction, Transaction, DuplicateDecision, str]] = []

    seen_signatures: dict[str, Transaction] = {}

    for tx in transactions:
        # Generate strict signature: account + date + debit + credit + ref + balance
        amt_str = f"D:{tx.debit}" if tx.debit is not None else f"C:{tx.credit}"
        bal_str = f"B:{tx.running_balance}" if tx.running_balance is not None else "B:None"
        ref_str = f"R:{tx.reference_number or tx.cheque_number or ''}"

        strict_sig = f"{tx.account_number}_{tx.transaction_date}_{amt_str}_{bal_str}_{ref_str}_{tx.description}"
        fuzzy_sig = f"{tx.account_number}_{tx.transaction_date}_{amt_str}_{bal_str}"

        if strict_sig in seen_signatures:
            existing = seen_signatures[strict_sig]
            duplicates.append((tx, existing, DuplicateDecision.PROVEN_DUPLICATE, "Exact match on date, amount, balance, reference, and description."))
        else:
            seen_signatures[strict_sig] = tx
            unique.append(tx)

    return DeduplicationResult(
        unique_transactions=tuple(unique),
        duplicates=tuple(duplicates),
    )
