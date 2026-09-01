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


def _validate_decimal(val: Any, name: str, non_negative: bool = False) -> Decimal | None:
    """Validate that val is a Decimal or None, and optionally non-negative."""
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, Decimal):
        raise TypeError(f"{name} must be a Decimal instance or None, got {type(val)}.")
    if non_negative and val < Decimal("0"):
        raise ValueError(f"{name} magnitude must be non-negative, got {val}.")
    return val


def _validate_seq(seq: Any, item_cls: type, name: str) -> tuple:
    """Validate that seq is a list/tuple of item_cls and return an immutable tuple."""
    if not isinstance(seq, (list, tuple)):
        raise TypeError(f"{name} must be a sequence of {item_cls.__name__}, got {type(seq)}.")
    for i, item in enumerate(seq):
        if not isinstance(item, item_cls):
            raise TypeError(f"{name}[{i}] must be a {item_cls.__name__}, got {type(item)}.")
    return tuple(seq)


def _validate_mapping(mapping: Any, name: str) -> MappingProxyType:
    """Validate that mapping is a Mapping and return an immutable MappingProxyType."""
    if not isinstance(mapping, Mapping):
        raise TypeError(f"{name} must be a Mapping, got {type(mapping)}.")
    return MappingProxyType(dict(mapping))


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
        object.__setattr__(self, "context", _validate_mapping(self.context, "context"))


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

        _validate_decimal(self.debit, "debit", non_negative=True)
        _validate_decimal(self.credit, "credit", non_negative=True)
        _validate_decimal(self.running_balance, "running_balance")

        object.__setattr__(self, "issues", _validate_seq(self.issues, ValidationIssue, "issues"))
        object.__setattr__(self, "provenance", _validate_seq(self.provenance, ProvenanceRecord, "provenance"))
        object.__setattr__(self, "metadata", _validate_mapping(self.metadata, "metadata"))


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

        _validate_decimal(self.opening_balance, "opening_balance")
        _validate_decimal(self.closing_balance, "closing_balance")

        object.__setattr__(self, "transactions", _validate_seq(self.transactions, Transaction, "transactions"))
        object.__setattr__(self, "issues", _validate_seq(self.issues, ValidationIssue, "issues"))
        object.__setattr__(self, "provenance", _validate_seq(self.provenance, ProvenanceRecord, "provenance"))
        object.__setattr__(self, "metadata", _validate_mapping(self.metadata, "metadata"))


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
        object.__setattr__(self, "statements", _validate_seq(self.statements, BankStatement, "statements"))
        if not isinstance(self.total_debit, Decimal):
            raise TypeError(f"total_debit must be a Decimal, got {type(self.total_debit)}.")
        if not isinstance(self.total_credit, Decimal):
            raise TypeError(f"total_credit must be a Decimal, got {type(self.total_credit)}.")
