"""Typed Decimal-based Financial Models and Contracts for Bank Statements in Sarathi V2.

All monetary arithmetic and fields use Python standard library Decimal end-to-end.
Float arithmetic is strictly prohibited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from sarathi.sankalpa import ProvenanceRecord


class ValidationStatus(StrEnum):
    """Validation status for transactions and statements."""

    VALID = "valid"
    WARNING = "warning"
    INVALID = "invalid"


class DuplicateDecision(StrEnum):
    """Deduplication decisions."""

    PROVEN_DUPLICATE = "proven_duplicate"
    PROBABLE_DUPLICATE = "probable_duplicate"
    DISTINCT = "distinct"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Non-fatal or fatal validation issue observed on a transaction or statement."""

    code: str
    message: str
    severity: str = "warning"
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code or not self.code.strip():
            raise ValueError("ValidationIssue code must be a non-empty string.")
        if not self.message or not self.message.strip():
            raise ValueError("ValidationIssue message must be a non-empty string.")
        if isinstance(self.context, Mapping):
            object.__setattr__(self, "context", MappingProxyType(dict(self.context)))
        else:
            raise TypeError(f"context must be a Mapping, got {type(self.context)}.")


@dataclass(frozen=True, slots=True)
class Transaction:
    """Canonical typed Decimal-based transaction record."""

    transaction_date: date
    description: str
    bank_name: str
    transaction_time: time | None = None
    reference_number: str | None = None
    cheque_number: str | None = None
    debit: Decimal | None = None
    credit: Decimal | None = None
    running_balance: Decimal | None = None
    account_number: str | None = None
    account_holder_name: str | None = None
    currency: str = "INR"
    status: ValidationStatus = ValidationStatus.VALID
    issues: tuple[ValidationIssue, ...] = ()
    provenance: tuple[ProvenanceRecord, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_date, date):
            raise TypeError(f"transaction_date must be a date instance, got {type(self.transaction_date)}.")
        if self.transaction_time is not None and not isinstance(self.transaction_time, time):
            raise TypeError(f"transaction_time must be a time instance or None, got {type(self.transaction_time)}.")
        if not isinstance(self.description, str):
            raise TypeError(f"description must be a string, got {type(self.description)}.")
        if not self.bank_name or not isinstance(self.bank_name, str):
            raise ValueError("bank_name must be a non-empty string.")

        # Decimal type validation & magnitude rules
        if self.debit is not None:
            if isinstance(self.debit, bool) or not isinstance(self.debit, Decimal):
                raise TypeError(f"debit must be a Decimal instance or None, got {type(self.debit)}.")
            if self.debit < Decimal("0"):
                raise ValueError(f"debit magnitude must be non-negative, got {self.debit}.")

        if self.credit is not None:
            if isinstance(self.credit, bool) or not isinstance(self.credit, Decimal):
                raise TypeError(f"credit must be a Decimal instance or None, got {type(self.credit)}.")
            if self.credit < Decimal("0"):
                raise ValueError(f"credit magnitude must be non-negative, got {self.credit}.")

        if self.running_balance is not None:
            if isinstance(self.running_balance, bool) or not isinstance(self.running_balance, Decimal):
                raise TypeError(f"running_balance must be a Decimal instance or None, got {type(self.running_balance)}.")

        if isinstance(self.issues, (list, tuple)):
            for i, iss in enumerate(self.issues):
                if not isinstance(iss, ValidationIssue):
                    raise TypeError(f"issues[{i}] must be a ValidationIssue, got {type(iss)}.")
            object.__setattr__(self, "issues", tuple(self.issues))
        else:
            raise TypeError(f"issues must be a sequence of ValidationIssue, got {type(self.issues)}.")

        if isinstance(self.provenance, (list, tuple)):
            for i, prov in enumerate(self.provenance):
                if not isinstance(prov, ProvenanceRecord):
                    raise TypeError(f"provenance[{i}] must be a ProvenanceRecord, got {type(prov)}.")
            object.__setattr__(self, "provenance", tuple(self.provenance))
        else:
            raise TypeError(f"provenance must be a sequence of ProvenanceRecord, got {type(self.provenance)}.")

        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")


@dataclass(frozen=True, slots=True)
class BankStatement:
    """Canonical parsed bank statement for a single account."""

    bank_name: str
    bank_profile: str
    account_number: str | None
    account_holder: str | None
    statement_period_start: date | None = None
    statement_period_end: date | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    currency: str = "INR"
    transactions: tuple[Transaction, ...] = ()
    status: ValidationStatus = ValidationStatus.VALID
    issues: tuple[ValidationIssue, ...] = ()
    provenance: tuple[ProvenanceRecord, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.bank_name or not isinstance(self.bank_name, str):
            raise ValueError("bank_name must be a non-empty string.")
        if not self.bank_profile or not isinstance(self.bank_profile, str):
            raise ValueError("bank_profile must be a non-empty string.")

        if self.opening_balance is not None and not isinstance(self.opening_balance, Decimal):
            raise TypeError(f"opening_balance must be a Decimal or None, got {type(self.opening_balance)}.")
        if self.closing_balance is not None and not isinstance(self.closing_balance, Decimal):
            raise TypeError(f"closing_balance must be a Decimal or None, got {type(self.closing_balance)}.")

        if isinstance(self.transactions, (list, tuple)):
            for i, tx in enumerate(self.transactions):
                if not isinstance(tx, Transaction):
                    raise TypeError(f"transactions[{i}] must be a Transaction, got {type(tx)}.")
            object.__setattr__(self, "transactions", tuple(self.transactions))
        else:
            raise TypeError(f"transactions must be a sequence of Transaction, got {type(self.transactions)}.")

        if isinstance(self.issues, (list, tuple)):
            for i, iss in enumerate(self.issues):
                if not isinstance(iss, ValidationIssue):
                    raise TypeError(f"issues[{i}] must be a ValidationIssue, got {type(iss)}.")
            object.__setattr__(self, "issues", tuple(self.issues))
        else:
            raise TypeError(f"issues must be a sequence of ValidationIssue, got {type(self.issues)}.")

        if isinstance(self.provenance, (list, tuple)):
            for i, prov in enumerate(self.provenance):
                if not isinstance(prov, ProvenanceRecord):
                    raise TypeError(f"provenance[{i}] must be a ProvenanceRecord, got {type(prov)}.")
            object.__setattr__(self, "provenance", tuple(self.provenance))
        else:
            raise TypeError(f"provenance must be a sequence of ProvenanceRecord, got {type(self.provenance)}.")

        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")


@dataclass(frozen=True, slots=True)
class BankStatementConsolidationResult:
    """Consolidated bank statements across all accounts and inputs."""

    statements: tuple[BankStatement, ...]
    total_transactions: int
    total_debit: Decimal
    total_credit: Decimal
    status: ValidationStatus = ValidationStatus.VALID
    issues: tuple[ValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.statements, (list, tuple)):
            for i, s in enumerate(self.statements):
                if not isinstance(s, BankStatement):
                    raise TypeError(f"statements[{i}] must be a BankStatement, got {type(s)}.")
            object.__setattr__(self, "statements", tuple(self.statements))
        else:
            raise TypeError(f"statements must be a sequence of BankStatement, got {type(self.statements)}.")

        if not isinstance(self.total_debit, Decimal):
            raise TypeError(f"total_debit must be a Decimal, got {type(self.total_debit)}.")
        if not isinstance(self.total_credit, Decimal):
            raise TypeError(f"total_credit must be a Decimal, got {type(self.total_credit)}.")
