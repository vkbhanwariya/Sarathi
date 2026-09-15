from decimal import Decimal
from pathlib import Path

import pytest

from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.converter import parse_decimal_amount
from sarathi.shakti.bank_statements.models import BankStatement, Transaction, ValidationStatus


def test_parse_valid_decimal_amounts() -> None:
    assert parse_decimal_amount("1,250.50") == Decimal("1250.50")
    assert parse_decimal_amount("₹ 1,250.50") == Decimal("1250.50")
    assert parse_decimal_amount("Rs. 500") == Decimal("500")
    assert parse_decimal_amount("50/-") == Decimal("50")
    assert parse_decimal_amount("50Cr") == Decimal("50")
    assert parse_decimal_amount("50Dr") == Decimal("50")
    assert parse_decimal_amount("1 250.50") == Decimal("1250.50")
    assert parse_decimal_amount(1000) == Decimal("1000")
    assert parse_decimal_amount(Decimal("99.99")) == Decimal("99.99")


def test_parse_parenthetical_negative_amount() -> None:
    assert parse_decimal_amount("(1,250.00)") == Decimal("-1250.00")
    assert parse_decimal_amount("(50.25)") == Decimal("-50.25")


def test_parse_empty_and_null_amounts() -> None:
    assert parse_decimal_amount(None) is None
    assert parse_decimal_amount("") is None
    assert parse_decimal_amount("   ") is None
    assert parse_decimal_amount("-") is None
    assert parse_decimal_amount("N/A") is None
    assert parse_decimal_amount("nil") is None


def test_parse_invalid_amount_returns_none() -> None:
    """Per Bank Veda, unparseable amounts stay unresolved (None) rather than raising or defaulting."""
    assert parse_decimal_amount("invalid_non_numeric_amount") is None


def test_ambiguous_spacing_rejected() -> None:
    """Per Bank Veda, ambiguous spacing (like '5 0') must stay unresolved, never silently repaired."""
    assert parse_decimal_amount("5 0") is None
    assert parse_decimal_amount("12 34") is None


def test_non_finite_decimal_rejected() -> None:
    """Non-finite Decimal values (NaN, Infinity) must be rejected with ValueError."""
    import pytest

    from sarathi.shakti.bank_statements.models import _validate_decimal

    with pytest.raises(ValueError, match="must be a finite Decimal"):
        _validate_decimal(Decimal("NaN"), "amount")
    with pytest.raises(ValueError, match="must be a finite Decimal"):
        _validate_decimal(Decimal("Infinity"), "amount")
    with pytest.raises(ValueError, match="must be a finite Decimal"):
        _validate_decimal(Decimal("-Infinity"), "amount")


def _execute_table(headers: tuple[str, ...], data_row: tuple[str, ...]) -> Transaction:
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
    """Amount without direction remains unresolved (debit=None, credit=None) and raises validation error/invalidity."""
    headers = ("Date", "Description", "Amount", "Balance")
    data_row = ("01/01/2026", "Unknown Transfer", "1,500.00", "10,000.00")
    tx = _execute_table(headers, data_row)

    assert tx.debit is None
    assert tx.credit is None
    assert tx.status == ValidationStatus.INVALID
    assert any(i.code == "MISSING_AMOUNT" for i in tx.issues)


def test_amount_with_ambiguous_direction_is_unresolved() -> None:
    """Amount with ambiguous non-DR/CR direction value remains unresolved."""
    headers = ("Date", "Description", "Amount", "Dr / Cr", "Balance")
    data_row = ("01/01/2026", "Card Settlement", "2,500.00", "TRANSFER", "12,500.00")
    tx = _execute_table(headers, data_row)

    assert tx.debit is None
    assert tx.credit is None
    assert tx.status == ValidationStatus.INVALID
    assert any(i.code == "MISSING_AMOUNT" for i in tx.issues)


@pytest.mark.parametrize("dr_val", ["DR", "Dr.", "debit", "withdrawal"])
def test_amount_with_explicit_dr_indicator(dr_val: str) -> None:
    """Amount with explicit DR indicator is assigned to debit."""
    headers = ("Date", "Description", "Amount", "Dr / Cr", "Balance")
    data_row = ("01/01/2026", "ATM Cash", "500.00", dr_val, "9,500.00")
    tx = _execute_table(headers, data_row)

    assert tx.debit == Decimal("500.00")
    assert tx.credit is None
    assert tx.status == ValidationStatus.VALID


@pytest.mark.parametrize("cr_val", ["CR", "Cr.", "credit", "deposit"])
def test_amount_with_explicit_cr_indicator(cr_val: str) -> None:
    """Amount with explicit CR indicator is assigned to credit."""
    headers = ("Date", "Description", "Amount", "Dr / Cr", "Balance")
    data_row = ("01/01/2026", "Salary", "50,000.00", cr_val, "59,500.00")
    tx = _execute_table(headers, data_row)

    assert tx.credit == Decimal("50000.00")
    assert tx.debit is None
    assert tx.status == ValidationStatus.VALID
