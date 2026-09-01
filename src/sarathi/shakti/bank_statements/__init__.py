"""Bank Statement Consolidation Capability Package for Sarathi V2."""

from __future__ import annotations

from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.models import (
    BankStatement,
    BankStatementConsolidationResult,
    DuplicateDecision,
    Transaction,
    ValidationIssue,
    ValidationStatus,
)
from sarathi.shakti.bank_statements.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO

__all__ = [
    "BankStatementCapability",
    "BankStatement",
    "BankStatementConsolidationResult",
    "DuplicateDecision",
    "Transaction",
    "ValidationIssue",
    "ValidationStatus",
    "CAPABILITY_DECLARATION",
    "PLUGIN_INFO",
]
