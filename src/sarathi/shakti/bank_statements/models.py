"""Typed Decimal-based Financial Models and Contracts for Bank Statements in Sarathi.

All monetary arithmetic and fields use Python standard library Decimal end-to-end.
Float arithmetic is strictly prohibited.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

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
class AccountIdentity:
    """Safe typed account identity protecting PII."""

    bank_name: str
    masked_account_number: str | None = None
    account_fingerprint: str | None = None
    account_holder: str | None = None
    account_type: str | None = None
    bank_profile: str | None = None
    ifsc: str | None = None
    account_key: str | None = None
    identity_strength: str = "STRONG"

    def __post_init__(self) -> None:
        if not self.bank_name or not self.bank_name.strip():
            raise ValueError("bank_name must be a non-empty string.")
        if self.account_key is None and self.account_fingerprint is not None:
            object.__setattr__(self, "account_key", self.account_fingerprint)
        elif self.account_fingerprint is None and self.account_key is not None:
            object.__setattr__(self, "account_fingerprint", self.account_key)


def create_account_identity(
    bank_name: str,
    raw_account_number: str | None,
    account_holder: str | None = None,
    bank_profile: str | None = None,
    account_type: str | None = None,
    ifsc: str | None = None,
    account_key: str | None = None,
    identity_strength: str | None = None,
) -> AccountIdentity:
    """Create a safe AccountIdentity with masked account number, immutable account_key, and strength rating."""
    masked: str | None = None
    fingerprint: str | None = None
    strength: str = "WEAK"

    clean_bank = bank_name.strip().lower()
    clean_ifsc = ifsc.strip().upper() if ifsc and ifsc.strip() else None
    ifsc_bank = clean_ifsc[:4] if clean_ifsc and len(clean_ifsc) >= 4 and clean_ifsc[:4].isalnum() else None

    # Canonical institutional bank key: if generic/unknown, IFSC 4-letter prefix provides definitive bank identity
    is_generic_bank = clean_bank in ("generic bank", "generic", "bank", "unknown bank", "unknown")
    if is_generic_bank and ifsc_bank:
        bank_key = ifsc_bank.lower()
    else:
        bank_key = clean_bank

    if raw_account_number and raw_account_number.strip():
        raw_val = raw_account_number.strip()
        is_already_masked = bool(re.search(r"[xX*]", raw_val))

        if is_already_masked:
            clean_acc = raw_val
            masked = clean_acc
            # Masked account number requires account_holder for safe medium identity
            if account_holder and account_holder.strip():
                raw_key = f"{bank_key}:{clean_acc.lower()}:{account_holder.strip().lower()}"
                fingerprint = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]
                strength = "MEDIUM"
            else:
                fingerprint = None
                strength = "WEAK"
        else:
            # Full unmasked account: normalize delimiters (whitespace, hyphens, underscores, dots)
            clean_acc = re.sub(r"[\s\-_.]+", "", raw_val)
            if len(clean_acc) >= 4:
                masked = "X" * (len(clean_acc) - 4) + clean_acc[-4:]
            else:
                masked = "X" * len(clean_acc)

            # Deterministic immutable account_key across all statements regardless of IFSC presence
            raw_key = f"{bank_key}:{clean_acc.lower()}"
            fingerprint = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]
            strength = "STRONG"

    final_key = account_key if account_key is not None else fingerprint
    final_strength = identity_strength if identity_strength is not None else strength

    return AccountIdentity(
        bank_name=bank_name.strip(),
        masked_account_number=masked,
        account_fingerprint=final_key,
        account_holder=account_holder.strip() if account_holder else None,
        account_type=account_type.strip() if account_type else None,
        bank_profile=bank_profile.strip() if bank_profile else None,
        ifsc=ifsc.strip() if ifsc else None,
        account_key=final_key,
        identity_strength=final_strength,
    )


def generate_statement_id(
    bank_name: str,
    account_identity: AccountIdentity | None = None,
    doc_id: str | None = None,
    document_fingerprint: str | None = None,
) -> str:
    """Generate a deterministic, safe, unique statement identifier."""
    clean_bank = re.sub(r"[^a-zA-Z0-9]+", "_", bank_name.strip().lower()).strip("_") or "bank"
    acc_part = "unidentified"
    if account_identity:
        if account_identity.account_fingerprint:
            acc_part = f"acc_{account_identity.account_fingerprint[:12]}"
        elif account_identity.masked_account_number:
            clean_acc = re.sub(r"[^a-zA-Z0-9]+", "", account_identity.masked_account_number)
            acc_part = f"acc_{clean_acc}"
    doc_part = ""
    # Prioritize document fingerprint over transient/sequential doc_id labels
    effective_fp = document_fingerprint or (
        doc_id if (doc_id and not re.match(r"^inp[-_]?\d+$", doc_id.strip(), re.IGNORECASE)) else None
    )
    if effective_fp and effective_fp.strip():
        clean_fp = re.sub(r"[^a-zA-Z0-9]+", "_", effective_fp.strip()).strip("_")
        if clean_fp:
            doc_part = f"_{clean_fp[-12:]}"
    elif doc_id and doc_id.strip():
        clean_doc = re.sub(r"[^a-zA-Z0-9]+", "_", doc_id.strip()).strip("_")
        if clean_doc:
            doc_part = f"_{clean_doc[-12:]}"
    return f"stmt_{clean_bank}_{acc_part}{doc_part}"


def _validate_decimal(val: Any, name: str, non_negative: bool = False) -> Decimal | None:
    """Validate that val is a Decimal or None, finite, and optionally non-negative."""
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, Decimal):
        raise TypeError(f"{name} must be a Decimal instance or None, got {type(val)}.")
    if not val.is_finite():
        raise ValueError(f"{name} must be a finite Decimal, got {val}.")
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
    account_identity: AccountIdentity | None = None
    currency: str = "INR"
    status: ValidationStatus = ValidationStatus.VALID
    issues: tuple[ValidationIssue, ...] = ()
    provenance: tuple[ProvenanceRecord, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    posting_date: date | None = None
    value_date: date | None = None
    transaction_datetime: datetime | None = None
    sequence_id: int = 0
    statement_id: str | None = None
    transaction_id: str | None = None
    raw_description: str | None = None
    raw_reference: str | None = None
    source_input_id: str | None = None
    page_number: int | None = None
    row_index: int | None = None
    input_location: str | None = None
    transaction_mode: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_date, date):
            raise TypeError(f"transaction_date must be a date instance, got {type(self.transaction_date)}.")
        if self.transaction_time is not None and not isinstance(self.transaction_time, time):
            raise TypeError(f"transaction_time must be a time instance or None, got {type(self.transaction_time)}.")
        if not isinstance(self.description, str):
            raise TypeError(f"description must be a string, got {type(self.description)}.")
        if not self.bank_name or not isinstance(self.bank_name, str):
            raise ValueError("bank_name must be a non-empty string.")
        if self.account_identity is not None and not isinstance(self.account_identity, AccountIdentity):
            raise TypeError(
                f"account_identity must be an AccountIdentity instance or None, got {type(self.account_identity)}."
            )
        if self.posting_date is not None and not isinstance(self.posting_date, date):
            raise TypeError(f"posting_date must be a date instance or None, got {type(self.posting_date)}.")
        if self.value_date is not None and not isinstance(self.value_date, date):
            raise TypeError(f"value_date must be a date instance or None, got {type(self.value_date)}.")
        if self.transaction_datetime is not None and not isinstance(self.transaction_datetime, datetime):
            raise TypeError(
                f"transaction_datetime must be a datetime instance or None, got {type(self.transaction_datetime)}."
            )
        if isinstance(self.sequence_id, bool) or not isinstance(self.sequence_id, int):
            raise TypeError(f"sequence_id must be an integer, got {type(self.sequence_id)}.")
        if self.statement_id is not None and not isinstance(self.statement_id, str):
            raise TypeError(f"statement_id must be a string or None, got {type(self.statement_id)}.")
        if self.transaction_id is not None and not isinstance(self.transaction_id, str):
            raise TypeError(f"transaction_id must be a string or None, got {type(self.transaction_id)}.")
        if self.raw_description is not None and not isinstance(self.raw_description, str):
            raise TypeError(f"raw_description must be a string or None, got {type(self.raw_description)}.")
        if self.raw_reference is not None and not isinstance(self.raw_reference, str):
            raise TypeError(f"raw_reference must be a string or None, got {type(self.raw_reference)}.")
        if self.source_input_id is not None and not isinstance(self.source_input_id, str):
            raise TypeError(f"source_input_id must be a string or None, got {type(self.source_input_id)}.")
        if self.page_number is not None and (
            isinstance(self.page_number, bool) or not isinstance(self.page_number, int)
        ):
            raise TypeError(f"page_number must be an integer or None, got {type(self.page_number)}.")
        if self.row_index is not None and (isinstance(self.row_index, bool) or not isinstance(self.row_index, int)):
            raise TypeError(f"row_index must be an integer or None, got {type(self.row_index)}.")
        if self.input_location is not None and not isinstance(self.input_location, str):
            raise TypeError(f"input_location must be a string or None, got {type(self.input_location)}.")
        if self.transaction_mode is not None and not isinstance(self.transaction_mode, str):
            raise TypeError(f"transaction_mode must be a string or None, got {type(self.transaction_mode)}.")

        if not self.transaction_id:
            seq = self.sequence_id if self.sequence_id > 0 else 1
            if self.statement_id:
                clean_stmt = re.sub(r"[^a-zA-Z0-9_]+", "_", self.statement_id).strip("_")
                object.__setattr__(self, "transaction_id", f"tx_{clean_stmt}_{seq:05d}")
            else:
                object.__setattr__(self, "transaction_id", f"TXN-{seq:04d}")

        _validate_decimal(self.debit, "debit", non_negative=True)
        _validate_decimal(self.credit, "credit", non_negative=True)
        _validate_decimal(self.running_balance, "running_balance")

        object.__setattr__(self, "issues", _validate_seq(self.issues, ValidationIssue, "issues"))
        object.__setattr__(self, "provenance", _validate_seq(self.provenance, ProvenanceRecord, "provenance"))
        object.__setattr__(self, "metadata", _validate_mapping(self.metadata, "metadata"))

    @property
    def posting_datetime(self) -> datetime | None:
        """Canonical Veda alias for posting_date."""
        if self.posting_date is None:
            return None
        return datetime.combine(self.posting_date, time.min)


@dataclass(frozen=True, slots=True)
class BankStatement:
    """Canonical parsed bank statement for a single account."""

    bank_name: str
    bank_profile: str
    account_identity: AccountIdentity | None = None
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
    statement_id: str | None = None
    account_holder: str | None = None
    account_type: str | None = None
    branch: str | None = None
    ifsc: str | None = None
    balance_as_on: Decimal | None = None
    bank_code: str | None = None

    def __post_init__(self) -> None:
        if not self.bank_name or not isinstance(self.bank_name, str):
            raise ValueError("bank_name must be a non-empty string.")
        if not self.bank_profile or not isinstance(self.bank_profile, str):
            raise ValueError("bank_profile must be a non-empty string.")
        if self.account_identity is not None and not isinstance(self.account_identity, AccountIdentity):
            raise TypeError(
                f"account_identity must be an AccountIdentity instance or None, got {type(self.account_identity)}."
            )

        if not self.statement_id:
            object.__setattr__(
                self,
                "statement_id",
                generate_statement_id(self.bank_name, self.account_identity, None),
            )

        _validate_decimal(self.opening_balance, "opening_balance")
        _validate_decimal(self.closing_balance, "closing_balance")
        _validate_decimal(self.balance_as_on, "balance_as_on")

        object.__setattr__(self, "transactions", _validate_seq(self.transactions, Transaction, "transactions"))
        object.__setattr__(self, "issues", _validate_seq(self.issues, ValidationIssue, "issues"))
        object.__setattr__(self, "provenance", _validate_seq(self.provenance, ProvenanceRecord, "provenance"))
        object.__setattr__(self, "metadata", _validate_mapping(self.metadata, "metadata"))

    @property
    def statement_from(self) -> date | None:
        """Canonical Veda alias for statement_period_start."""
        return self.statement_period_start

    @property
    def statement_to(self) -> date | None:
        """Canonical Veda alias for statement_period_end."""
        return self.statement_period_end


@dataclass(frozen=True, slots=True)
class BankStatementConsolidationResult:
    """Consolidated bank statements across all accounts and inputs."""

    statements: tuple[BankStatement, ...]
    total_transactions: int
    total_debit: Decimal | None = None
    total_credit: Decimal | None = None
    status: ValidationStatus = ValidationStatus.VALID
    issues: tuple[ValidationIssue, ...] = ()
    transactions: tuple[Transaction, ...] = ()
    totals_by_currency: Mapping[str, tuple[Decimal, Decimal]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "statements", _validate_seq(self.statements, BankStatement, "statements"))
        if self.total_debit is not None and not isinstance(self.total_debit, Decimal):
            raise TypeError(f"total_debit must be a Decimal or None, got {type(self.total_debit)}.")
        if self.total_credit is not None and not isinstance(self.total_credit, Decimal):
            raise TypeError(f"total_credit must be a Decimal or None, got {type(self.total_credit)}.")
        object.__setattr__(self, "transactions", _validate_seq(self.transactions, Transaction, "transactions"))
        object.__setattr__(self, "totals_by_currency", dict(self.totals_by_currency))


@dataclass(frozen=True, slots=True)
class ConsolidatedAccount:
    """Canonical aggregated account summary across multiple statement periods."""

    bank_name: str
    account_key: str
    account_holder: str = "-"
    masked_account_number: str = "-"
    statements_count: int = 1
    input_location_range: str = "-"
    transaction_id_range: str = "-"
    transactions_count: int = 0
    account_identity: AccountIdentity | None = None
