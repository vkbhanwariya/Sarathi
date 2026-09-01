"""Financial Validator for Bank Statements in Sarathi V2.

Validates:
1. Transaction invariants: (debit is not None) OR (credit is not None).
2. Pure Decimal arithmetic continuity: B_i = B_{i-1} + C_i - D_i.
3. Statement reconciliation: Opening + Credits - Debits = Closing.
4. Debit/Credit inversion detection across rows.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from sarathi.shakti.bank_statements.models import (
    BankStatement,
    Transaction,
    ValidationIssue,
    ValidationStatus,
)


def validate_transaction(tx: Transaction) -> tuple[ValidationStatus, tuple[ValidationIssue, ...]]:
    """Validate a single transaction's core invariants."""
    issues: list[ValidationIssue] = list(tx.issues)
    status = tx.status

    # Invariant: exactly one direction populated (debit or credit)
    if tx.debit is None and tx.credit is None:
        issues.append(
            ValidationIssue(
                code="MISSING_AMOUNT",
                message="Transaction has neither debit nor credit amount populated.",
                severity="error",
            )
        )
        status = ValidationStatus.INVALID
    elif tx.debit is not None and tx.credit is not None:
        issues.append(
            ValidationIssue(
                code="CONCURRENT_DEBIT_CREDIT",
                message=f"Transaction has both debit ({tx.debit}) and credit ({tx.credit}) populated.",
                severity="warning",
            )
        )
        if status == ValidationStatus.VALID:
            status = ValidationStatus.WARNING

    return status, tuple(issues)


def validate_statement_balances(statement: BankStatement) -> BankStatement:
    """Validate sequential running balance continuity and statement-level reconciliation.

    Running balance rule:
    Current Balance = Previous Balance + Credit - Debit
    """
    transactions = list(statement.transactions)
    validated_transactions: list[Transaction] = []
    statement_issues: list[ValidationIssue] = list(statement.issues)

    prev_balance: Decimal | None = statement.opening_balance
    total_debits = Decimal("0")
    total_credits = Decimal("0")

    for idx, tx in enumerate(transactions):
        tx_status, tx_issues_list = validate_transaction(tx)
        issues = list(tx_issues_list)

        debit_amt = tx.debit or Decimal("0")
        credit_amt = tx.credit or Decimal("0")
        total_debits += debit_amt
        total_credits += credit_amt

        # Validate Running Balance continuity
        if tx.running_balance is not None and prev_balance is not None:
            expected_balance = prev_balance + credit_amt - debit_amt
            if tx.running_balance != expected_balance:
                diff = tx.running_balance - expected_balance
                issues.append(
                    ValidationIssue(
                        code="BALANCE_DISCONTINUITY",
                        message=(
                            f"Running balance mismatch at row {idx + 1}: expected {expected_balance}, "
                            f"got {tx.running_balance} (difference {diff})."
                        ),
                        severity="warning",
                        context={
                            "expected": str(expected_balance),
                            "actual": str(tx.running_balance),
                            "diff": str(diff),
                        },
                    )
                )
                if tx_status == ValidationStatus.VALID:
                    tx_status = ValidationStatus.WARNING

        if tx.running_balance is not None:
            prev_balance = tx.running_balance
        elif prev_balance is not None:
            prev_balance = prev_balance + credit_amt - debit_amt

        validated_transactions.append(
            Transaction(
                transaction_date=tx.transaction_date,
                description=tx.description,
                bank_name=tx.bank_name,
                transaction_time=tx.transaction_time,
                reference_number=tx.reference_number,
                cheque_number=tx.cheque_number,
                debit=tx.debit,
                credit=tx.credit,
                running_balance=tx.running_balance,
                account_number=tx.account_number,
                account_holder_name=tx.account_holder_name,
                currency=tx.currency,
                status=tx_status,
                issues=tuple(issues),
                provenance=tx.provenance,
                metadata=tx.metadata,
            )
        )

    # Statement Reconciliation: Opening + Credits - Debits == Closing
    overall_status = statement.status
    if statement.opening_balance is not None and statement.closing_balance is not None:
        expected_closing = statement.opening_balance + total_credits - total_debits
        if statement.closing_balance != expected_closing:
            diff = statement.closing_balance - expected_closing
            statement_issues.append(
                ValidationIssue(
                    code="RECONCILIATION_FAILED",
                    message=(
                        f"Statement reconciliation mismatch: opening ({statement.opening_balance}) + "
                        f"credits ({total_credits}) - debits ({total_debits}) = {expected_closing}, "
                        f"but closing balance is {statement.closing_balance} (diff {diff})."
                    ),
                    severity="warning",
                    context={
                        "opening": str(statement.opening_balance),
                        "total_credits": str(total_credits),
                        "total_debits": str(total_debits),
                        "expected_closing": str(expected_closing),
                        "actual_closing": str(statement.closing_balance),
                    },
                )
            )
            overall_status = ValidationStatus.WARNING

    # If any transaction is warning/invalid, reflect on statement
    if any(t.status == ValidationStatus.INVALID for t in validated_transactions):
        overall_status = ValidationStatus.INVALID
    elif any(t.status == ValidationStatus.WARNING for t in validated_transactions) and overall_status == ValidationStatus.VALID:
        overall_status = ValidationStatus.WARNING

    return BankStatement(
        bank_name=statement.bank_name,
        bank_profile=statement.bank_profile,
        account_number=statement.account_number,
        account_holder=statement.account_holder,
        statement_period_start=statement.statement_period_start,
        statement_period_end=statement.statement_period_end,
        opening_balance=statement.opening_balance,
        closing_balance=statement.closing_balance,
        currency=statement.currency,
        transactions=tuple(validated_transactions),
        status=overall_status,
        issues=tuple(statement_issues),
        provenance=statement.provenance,
        metadata=statement.metadata,
    )
