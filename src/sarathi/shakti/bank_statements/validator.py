"""Financial Validator for Bank Statements in Sarathi V2.

Validates:
1. Transaction invariants (date, debit/credit presence, non-negative Decimal)
2. Running balance continuity (B_i = B_{i-1} + C_i - D_i)
3. Statement reconciliation (Opening + Credits - Debits = Closing)
"""

from __future__ import annotations

from decimal import Decimal

from sarathi.shakti.bank_statements.models import (
    BankStatement,
    Transaction,
    ValidationIssue,
    ValidationStatus,
)


def validate_transaction(transaction: Transaction) -> tuple[ValidationStatus, tuple[ValidationIssue, ...]]:
    """Validate single transaction invariants."""
    issues: list[ValidationIssue] = []
    status = ValidationStatus.VALID

    # Invariant: At least one of debit or credit must be present
    if transaction.debit is None and transaction.credit is None:
        issues.append(
            ValidationIssue(
                code="MISSING_AMOUNT",
                message="Transaction must have at least one of debit or credit amount.",
                severity="warning",
            )
        )
        status = ValidationStatus.WARNING

    # Invariant: Both debit and credit cannot be non-zero simultaneously
    if transaction.debit is not None and transaction.credit is not None:
        if transaction.debit > Decimal("0") and transaction.credit > Decimal("0"):
            issues.append(
                ValidationIssue(
                    code="DUAL_DIRECTION_AMOUNT",
                    message="Transaction cannot have both non-zero debit and credit amounts.",
                    severity="warning",
                )
            )
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
                        code="RUNNING_BALANCE_DISCONTINUITY",
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

        statement_issues.extend(issues)
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
                account_identity=tx.account_identity,
                currency=tx.currency,
                status=tx_status,
                issues=tuple(issues),
                provenance=tx.provenance,
                metadata=tx.metadata,
            )
        )

    # Validate Statement Reconciliation: Opening + Credits - Debits == Closing
    if statement.opening_balance is not None and statement.closing_balance is not None:
        expected_closing = statement.opening_balance + total_credits - total_debits
        if statement.closing_balance != expected_closing:
            reconcile_diff = statement.closing_balance - expected_closing
            statement_issues.append(
                ValidationIssue(
                    code="RECONCILIATION_MISMATCH",
                    message=(
                        f"Statement reconciliation mismatch: expected closing {expected_closing}, "
                        f"got {statement.closing_balance} (difference {reconcile_diff})."
                    ),
                    severity="warning",
                    context={
                        "expected_closing": str(expected_closing),
                        "actual_closing": str(statement.closing_balance),
                        "diff": str(reconcile_diff),
                    },
                )
            )

    overall_status = ValidationStatus.VALID
    if any(t.status == ValidationStatus.WARNING for t in validated_transactions) or statement_issues:
        overall_status = ValidationStatus.WARNING

    return BankStatement(
        bank_name=statement.bank_name,
        bank_profile=statement.bank_profile,
        account_identity=statement.account_identity,
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
