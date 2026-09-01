"""Focused tests for Amount + Direction layout resolution."""

from datetime import date
from decimal import Decimal
import io
from pathlib import Path
import pytest

from sarathi.sankalpa import CanonicalDocument, ExecutionContext, ExecutionProfile, InputRef, Request, Result, TableData
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.models import (
    BankStatement,
    BankStatementConsolidationResult,
    Transaction,
    ValidationStatus,
)


def _execute_table(headers: tuple[str, ...], data_row: tuple[str, ...], profile_id: str = "generic") -> Transaction:
    table = TableData(rows=(headers, data_row))
    doc = CanonicalDocument(
        document_id="doc-test-dir",
        text="Bank Statement\nAccount Number: 1234567890",
        tables=(table,),
    )
    req = Request(
        request_id="req-dir-1",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-dir-1", "t1", "s1")
    cap = BankStatementCapability()
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt: BankStatement = res.data.statements[0]
    return stmt.transactions[0]


def test_amount_with_no_direction_is_unresolved() -> None:
    """Amount without direction remains unresolved (debit=None, credit=None) and raises validation warning."""
    headers = ("Date", "Description", "Amount", "Balance")
    data_row = ("01/01/2026", "Unknown Transfer", "1,500.00", "10,000.00")
    tx = _execute_table(headers, data_row)

    assert tx.debit is None
    assert tx.credit is None
    assert tx.status == ValidationStatus.WARNING
    assert any(i.code == "MISSING_AMOUNT" for i in tx.issues)


def test_amount_with_ambiguous_direction_is_unresolved() -> None:
    """Amount with ambiguous non-DR/CR direction value remains unresolved."""
    headers = ("Date", "Description", "Amount", "Dr / Cr", "Balance")
    data_row = ("01/01/2026", "Card Settlement", "2,500.00", "TRANSFER", "12,500.00")
    tx = _execute_table(headers, data_row)

    assert tx.debit is None
    assert tx.credit is None
    assert tx.status == ValidationStatus.WARNING
    assert any(i.code == "MISSING_AMOUNT" for i in tx.issues)


def test_amount_with_explicit_dr_indicator() -> None:
    """Amount with explicit DR indicator is assigned to debit."""
    for dr_val in ("DR", "Dr.", "debit", "withdrawal"):
        headers = ("Date", "Description", "Amount", "Dr / Cr", "Balance")
        data_row = ("01/01/2026", "ATM Cash", "500.00", dr_val, "9,500.00")
        tx = _execute_table(headers, data_row)

        assert tx.debit == Decimal("500.00")
        assert tx.credit is None
        assert tx.status == ValidationStatus.VALID


def test_amount_with_explicit_cr_indicator() -> None:
    """Amount with explicit CR indicator is assigned to credit."""
    for cr_val in ("CR", "Cr.", "credit", "deposit"):
        headers = ("Date", "Description", "Amount", "Dr / Cr", "Balance")
        data_row = ("01/01/2026", "Salary", "50,000.00", cr_val, "59,500.00")
        tx = _execute_table(headers, data_row)

        assert tx.credit == Decimal("50000.00")
        assert tx.debit is None
        assert tx.status == ValidationStatus.VALID
