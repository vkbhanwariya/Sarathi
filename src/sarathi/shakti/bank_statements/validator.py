"""Financial Validator for Bank Statements in Sarathi.

Validates:
1. Transaction invariants (date, debit/credit presence, non-negative Decimal)
2. Running balance continuity (B_i = B_{i-1} + C_i - D_i) in chronological or reverse-chronological order
3. Statement reconciliation (Opening + Credits - Debits = Closing)
"""

from __future__ import annotations

from dataclasses import replace
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
    status = transaction.status

    if transaction.debit is None and transaction.credit is None:
        if not any(i.code == "MISSING_AMOUNT" for i in transaction.issues):
            issues.append(
                ValidationIssue(
                    code="MISSING_AMOUNT",
                    message="Transaction must have at least one of debit or credit amount.",
                    severity="error",
                )
            )
        status = ValidationStatus.INVALID

    if transaction.debit is not None and transaction.credit is not None:
        if transaction.debit > Decimal("0") and transaction.credit > Decimal("0"):
            if not any(i.code == "DUAL_DIRECTION_AMOUNT" for i in transaction.issues):
                issues.append(
                    ValidationIssue(
                        code="DUAL_DIRECTION_AMOUNT",
                        message="Transaction cannot have both non-zero debit and credit amounts.",
                        severity="warning",
                    )
                )
            if status != ValidationStatus.INVALID:
                status = ValidationStatus.WARNING

    return status, tuple(issues)


def validate_statement_balances(statement: BankStatement) -> BankStatement:
    """Validate running balance continuity and statement-level reconciliation."""
    transactions = list(statement.transactions)
    validated_transactions: list[Transaction] = []
    statement_issues: list[ValidationIssue] = list(statement.issues)

    if not transactions:
        if not any(i.code == "ZERO_TRANSACTIONS_EXTRACTED" for i in statement_issues):
            statement_issues.append(
                ValidationIssue(
                    code="ZERO_TRANSACTIONS_EXTRACTED",
                    message="Statement recognized as bank statement but zero transaction rows could be extracted.",
                    severity="error",
                )
            )
        return replace(
            statement,
            status=ValidationStatus.INVALID,
            issues=tuple(statement_issues),
        )

    import datetime

    # Check if transactions appear in reverse chronological order
    # Multi-factor reverse-order detection:
    # 1. Date and timestamp progression
    dt_keys = [
        (tx.transaction_date, tx.transaction_time or datetime.time.min)
        for tx in transactions
    ]
    has_strictly_descending = any(
        dt_keys[i] > dt_keys[i + 1] for i in range(len(dt_keys) - 1)
    )
    all_non_ascending = all(
        dt_keys[i] >= dt_keys[i + 1] for i in range(len(dt_keys) - 1)
    )

    # 2. Running balance mathematical progression evidence
    fwd_bal_matches = 0
    rev_bal_matches = 0
    for i in range(len(transactions) - 1):
        t1, t2 = transactions[i], transactions[i + 1]
        if t1.running_balance is not None and t2.running_balance is not None:
            # Forward hypothesis (t1 precedes t2): t2.bal - t1.bal == t2.crd - t2.deb
            expected_fwd_delta = (t2.credit or Decimal("0")) - (t2.debit or Decimal("0"))
            if t2.running_balance - t1.running_balance == expected_fwd_delta:
                fwd_bal_matches += 1
            # Reverse hypothesis (t2 precedes t1): t1.bal - t2.bal == t1.crd - t1.deb
            expected_rev_delta = (t1.credit or Decimal("0")) - (t1.debit or Decimal("0"))
            if t1.running_balance - t2.running_balance == expected_rev_delta:
                rev_bal_matches += 1

    is_reverse = False
    if len(transactions) >= 2:
        if rev_bal_matches > fwd_bal_matches:
            is_reverse = True
        elif fwd_bal_matches > rev_bal_matches:
            is_reverse = False
        elif has_strictly_descending and all_non_ascending:
            is_reverse = True

    total_debits = sum((tx.debit or Decimal("0") for tx in transactions), Decimal("0"))
    total_credits = sum((tx.credit or Decimal("0") for tx in transactions), Decimal("0"))

    # Mathematical inference of missing boundary balance if exactly one is present
    opening_bal = statement.opening_balance
    closing_bal = statement.closing_balance
    if opening_bal is None and closing_bal is not None:
        opening_bal = closing_bal - total_credits + total_debits
    elif closing_bal is None and opening_bal is not None:
        closing_bal = opening_bal + total_credits - total_debits

    # Validate Running Balance continuity (chronologically)
    ordered_txns = list(reversed(transactions)) if is_reverse else transactions

    # Check for Debit / Credit column inversion across chronological transitions
    canon_matches = 0
    inv_matches = 0
    total_testable = 0

    for idx, tx in enumerate(ordered_txns):
        deb = tx.debit or Decimal("0")
        crd = tx.credit or Decimal("0")
        if deb == crd or tx.running_balance is None:
            continue

        prev_ref_bal = opening_bal if idx == 0 else ordered_txns[idx - 1].running_balance
        if prev_ref_bal is None:
            continue

        actual_delta = tx.running_balance - prev_ref_bal
        canon_delta = crd - deb
        inv_delta = deb - crd

        total_testable += 1
        if actual_delta == canon_delta:
            canon_matches += 1
        elif actual_delta == inv_delta:
            inv_matches += 1

    if (
        total_testable >= 2
        and inv_matches >= 2
        and inv_matches > canon_matches
        and (inv_matches / total_testable) >= 0.75
    ):
        statement_issues.append(
            ValidationIssue(
                code="DEBIT_CREDIT_INVERSION_DETECTED",
                message=(
                    "Statement columns appear to be inverted: debit and credit amounts have been "
                    "swapped to restore running balance continuity."
                ),
                severity="warning",
                context={
                    "inverted_matches": str(inv_matches),
                    "canonical_matches": str(canon_matches),
                    "total_testable": str(total_testable),
                },
            )
        )
        ordered_txns = [replace(tx, debit=tx.credit, credit=tx.debit) for tx in ordered_txns]
        total_debits = sum((tx.debit or Decimal("0") for tx in ordered_txns), Decimal("0"))
        total_credits = sum((tx.credit or Decimal("0") for tx in ordered_txns), Decimal("0"))
        if statement.opening_balance is None and statement.closing_balance is not None:
            opening_bal = closing_bal - total_credits + total_debits
        elif statement.closing_balance is None and statement.opening_balance is not None:
            closing_bal = opening_bal + total_credits - total_debits

    # Precompute reverse running balance anchors (from closing_bal backward)
    # B_{i-1} = B_i - C_i + D_i
    backward_expected: list[Decimal | None] = [None] * len(ordered_txns)
    if closing_bal is not None:
        curr_back: Decimal | None = closing_bal
        for idx in range(len(ordered_txns) - 1, -1, -1):
            tx = ordered_txns[idx]
            backward_expected[idx] = curr_back
            deb = tx.debit or Decimal("0")
            crd = tx.credit or Decimal("0")
            if curr_back is not None:
                curr_back = curr_back - crd + deb

    prev_balance: Decimal | None = opening_bal

    for idx, tx in enumerate(ordered_txns):
        tx_status, tx_issues_list = validate_transaction(tx)
        issues = list(tx_issues_list)

        debit_amt = tx.debit or Decimal("0")
        credit_amt = tx.credit or Decimal("0")

        if tx.running_balance is not None and prev_balance is not None:
            expected_balance = prev_balance + credit_amt - debit_amt
            if tx.running_balance != expected_balance:
                diff = tx.running_balance - expected_balance
                back_exp = backward_expected[idx]
                is_isolated = back_exp is not None and tx.running_balance == back_exp
                context: dict[str, str] = {
                    "expected": str(expected_balance),
                    "actual": str(tx.running_balance),
                    "diff": str(diff),
                }
                if is_isolated:
                    context["isolated_upstream_discontinuity"] = "true"
                    if idx == 0 and statement.opening_balance is not None:
                        context["suspected_source"] = "header_opening_balance_ocr"

                issues.append(
                    ValidationIssue(
                        code="RUNNING_BALANCE_DISCONTINUITY",
                        message=(
                            f"Running balance mismatch at row {idx + 1}: expected {expected_balance}, "
                            f"got {tx.running_balance} (difference {diff})."
                        ),
                        severity="warning",
                        context=context,
                    )
                )
                if tx_status == ValidationStatus.VALID:
                    tx_status = ValidationStatus.WARNING

        if tx.running_balance is not None:
            prev_balance = tx.running_balance
        elif prev_balance is not None:
            prev_balance = prev_balance + credit_amt - debit_amt

        statement_issues.extend(issues)
        combined_tx_issues = tuple(list(tx.issues) + [i for i in issues if i not in tx.issues])
        validated_transactions.append(replace(tx, status=tx_status, issues=combined_tx_issues))

    # Re-order back to original presentation order
    final_txns = list(reversed(validated_transactions)) if is_reverse else validated_transactions

    # Validate Statement Reconciliation: Opening + Credits - Debits == Closing
    if opening_bal is not None and closing_bal is not None:
        expected_closing = opening_bal + total_credits - total_debits
        if closing_bal != expected_closing:
            reconcile_diff = closing_bal - expected_closing
            statement_issues.append(
                ValidationIssue(
                    code="RECONCILIATION_MISMATCH",
                    message=(
                        f"Statement reconciliation mismatch: expected closing {expected_closing}, "
                        f"got {closing_bal} (difference {reconcile_diff})."
                    ),
                    severity="warning",
                    context={
                        "expected_closing": str(expected_closing),
                        "actual_closing": str(closing_bal),
                        "diff": str(reconcile_diff),
                    },
                )
            )

    overall_status = ValidationStatus.VALID
    if any(t.status == ValidationStatus.INVALID for t in final_txns):
        overall_status = ValidationStatus.INVALID
    elif any(t.status == ValidationStatus.WARNING for t in final_txns) or statement_issues:
        overall_status = ValidationStatus.WARNING

    return replace(
        statement,
        opening_balance=opening_bal,
        closing_balance=closing_bal,
        transactions=tuple(final_txns),
        status=overall_status,
        issues=tuple(statement_issues),
    )
