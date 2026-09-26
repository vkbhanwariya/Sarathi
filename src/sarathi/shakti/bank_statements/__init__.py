"""Bank Statement Consolidation Capability Package for Sarathi."""

from __future__ import annotations

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
]


from sarathi.shakti.text.lazy import lazy_exports

lazy_exports(
    globals(),
    {
        "repair_ifsc": ".utr_repair:repair_ifsc",
        "is_valid_ifsc": ".utr_repair:is_valid_ifsc",
        "repair_utr": ".utr_repair:repair_utr",
        "BankStatementCapability": ".capability:BankStatementCapability",
    },
)
