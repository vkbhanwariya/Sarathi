"""Bank Statement Consolidation Capability Package for Sarathi."""

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
    "repair_ifsc",
    "is_valid_ifsc",
    "repair_utr",
    "verify_mathematical_double_entry_balance",
    "BalanceDiscrepancy",
]


def __getattr__(name: str) -> Any:
    if name in (
        "repair_ifsc",
        "is_valid_ifsc",
        "repair_utr",
        "verify_mathematical_double_entry_balance",
        "BalanceDiscrepancy",
    ):
        from sarathi.shakti.bank_statements import utr_repair

        return getattr(utr_repair, name)
    if name == "BankStatementCapability":
        from sarathi.shakti.bank_statements.capability import BankStatementCapability

        return BankStatementCapability
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
