"""Tests for Decimal Amount Normalization and Cleaning."""

from decimal import Decimal

from sarathi.shakti.bank_statements.converter import parse_decimal_amount


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
