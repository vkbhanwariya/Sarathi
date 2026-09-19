"""Unit and Integration Tests for Banking UTR/IFSC Auto-Repair and Balance Integrity (Phase 5)."""

from __future__ import annotations

from decimal import Decimal

from sarathi.shakti.bank_statements.utr_repair import (
    BalanceDiscrepancy,
    is_valid_ifsc,
    repair_ifsc,
    repair_utr,
    verify_mathematical_double_entry_balance,
)


def test_ifsc_valid_and_ocr_repair() -> None:
    """Verify IFSC syntax validation and deterministic OCR character repair."""
    # 1. Valid IFSC codes
    assert is_valid_ifsc("SBIN0001234") is True
    assert is_valid_ifsc("HDFC0000001") is True
    assert is_valid_ifsc("PUNB0123456") is True

    # 2. Corrupted bank code (digit 1 -> letter I, digit 0 -> letter O)
    repaired, was_repaired = repair_ifsc("SB1N0001234")
    assert was_repaired is True
    assert repaired == "SBIN0001234"

    # 3. Corrupted 5th position (letter O -> digit 0)
    repaired_o, was_repaired_o = repair_ifsc("HDFCO000001")
    assert was_repaired_o is True
    assert repaired_o == "HDFC0000001"

    # 4. Corrupted 5th position (letter D -> digit 0)
    repaired_d, was_repaired_d = repair_ifsc("PUNBD123456")
    assert was_repaired_d is True
    assert repaired_d == "PUNB0123456"

    # 5. Non-recoverable invalid string
    invalid_res, invalid_flag = repair_ifsc("XYZ")
    assert invalid_flag is False


def test_utr_syntax_and_ocr_repair() -> None:
    """Verify RBI UTR syntax detection and auto-repair across NEFT, RTGS, and UPI."""
    # 1. NEFT: 16 characters (4 letters + 12 digits)
    neft_clean = "SBIN123456789012"
    repaired_neft, tx_type, was_rep = repair_utr(neft_clean)
    assert tx_type == "NEFT"
    assert repaired_neft == neft_clean
    assert was_rep is False

    # NEFT with OCR confusion (digit 1 in bank code, letter O in digits)
    neft_corrupted = "SB1N123456789O12"
    rep_neft, tx_type_c, was_rep_c = repair_utr(neft_corrupted)
    assert tx_type_c == "NEFT"
    assert rep_neft == "SBIN123456789012"
    assert was_rep_c is True

    # 2. RTGS: 22 characters (4 letters + R/0-9 + 17 digits)
    rtgs_clean = "PUNBR52024091912345678"
    repaired_rtgs, tx_type_r, was_rep_r = repair_utr(rtgs_clean)
    assert tx_type_r == "RTGS"
    assert repaired_rtgs == rtgs_clean
    assert was_rep_r is False

    # RTGS with OCR confusion (letter O in date digits)
    rtgs_corrupted = "PUNBR52O24O91912345678"
    rep_rtgs, tx_type_rc, was_rep_rc = repair_utr(rtgs_corrupted)
    assert tx_type_rc == "RTGS"
    assert rep_rtgs == "PUNBR52024091912345678"
    assert was_rep_rc is True

    # 3. UPI / IMPS: 12 numeric digits
    upi_corrupted = "123456789O12"
    rep_upi, tx_type_u, was_rep_u = repair_utr(upi_corrupted, tx_type="UPI")
    assert tx_type_u == "UPI"
    assert rep_upi == "123456789012"
    assert was_rep_u is True


def test_mathematical_double_entry_balance_verification() -> None:
    """Verify B_i = B_{i-1} + C_i - D_i double-entry calculation and variance reporting."""
    # Clean sequence:
    # Row 0: Opening 1000.00
    # Row 1: Credit 250.00, Debit 0 -> Balance 1250.00
    # Row 2: Credit 0, Debit 500.00 -> Balance 750.00
    clean_rows = [
        (None, None, Decimal("1000.00")),
        (Decimal("250.00"), Decimal("0.00"), Decimal("1250.00")),
        (Decimal("0.00"), Decimal("500.00"), Decimal("750.00")),
    ]
    discrepancies_clean = verify_mathematical_double_entry_balance(clean_rows)
    assert len(discrepancies_clean) == 0

    # Corrupted sequence:
    # Row 1 expected balance 1250.00, but actual is 1200.00 (variance: -50.00)
    corrupted_rows = [
        (None, None, Decimal("1000.00")),
        (Decimal("250.00"), Decimal("0.00"), Decimal("1200.00")),
        (Decimal("0.00"), Decimal("500.00"), Decimal("700.00")),
    ]
    discrepancies = verify_mathematical_double_entry_balance(corrupted_rows)
    assert len(discrepancies) == 1
    d = discrepancies[0]
    assert isinstance(d, BalanceDiscrepancy)
    assert d.row_index == 1
    assert d.previous_balance == Decimal("1000.00")
    assert d.credit == Decimal("250.00")
    assert d.expected_balance == Decimal("1250.00")
    assert d.actual_balance == Decimal("1200.00")
    assert d.variance == Decimal("-50.00")
