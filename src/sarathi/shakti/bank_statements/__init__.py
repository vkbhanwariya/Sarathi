"""Bank Statement Consolidation Capability Package for Sarathi V2."""

from __future__ import annotations

from typing import Any

from sarathi.shakti.bank_statements.models import (
    AccountIdentity,
    BankStatement,
    BankStatementConsolidationResult,
    DuplicateDecision,
    Transaction,
    ValidationIssue,
    ValidationStatus,
    create_account_identity,
)
from sarathi.shakti.bank_statements.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO

__all__ = [
    "BankStatementCapability",
    "AccountIdentity",
    "BankStatement",
    "BankStatementConsolidationResult",
    "DuplicateDecision",
    "Transaction",
    "ValidationIssue",
    "ValidationStatus",
    "create_account_identity",
    "CAPABILITY_DECLARATION",
    "PLUGIN_INFO",
]


def __getattr__(name: str) -> Any:
    if name == "BankStatementCapability":
        from sarathi.shakti.bank_statements.capability import BankStatementCapability

        return BankStatementCapability
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
