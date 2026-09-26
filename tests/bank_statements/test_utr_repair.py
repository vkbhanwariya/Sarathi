"""Unit and Integration Tests for Banking UTR/IFSC Auto-Repair and Balance Integrity (Phase 5)."""

from __future__ import annotations

from sarathi.shakti.bank_statements.utr_repair import (
    is_valid_ifsc,
    repair_ifsc,
    repair_utr,
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


def test_bank_statement_extraction_auto_repairs_utr() -> None:
    """Verify that BankStatementCapability auto-repairs OCR-corrupted UTR in reference column."""
    from pathlib import Path

    from sarathi.sankalpa import (
        CanonicalDocument,
        ExecutionContext,
        InputRef,
        PageData,
        Request,
        Result,
        TableData,
    )
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    headers = ["Txn Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"]
    # Provide corrupted NEFT reference with OCR 'O' instead of '0'
    corrupted_ref = "SBIN123456789O12"
    data_rows = [
        ["01/01/2024", "TRANSFER FROM RAM", corrupted_ref, "", "5000.00", "15000.00"],
    ]

    cdoc = CanonicalDocument(
        document_id="doc-utr-1",
        pages=(
            PageData(
                page_number=1,
                tables=(
                    TableData(
                        headers=tuple(headers),
                        rows=tuple([tuple(headers)] + [tuple(r) for r in data_rows]),
                    ),
                ),
            ),
        ),
    )

    cap = BankStatementCapability()
    req = Request(
        request_id="req-utr-repair",
        requirement="bank_statements",
        inputs=(InputRef("in-1", Path("dummy.csv"), "dummy.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-utr-repair", "t1", "s1")
    prior = Result(data=cdoc)
    res = cap.execute(req, ctx, prior_result=prior)
    assert res.data is not None
    assert len(res.data.transactions) == 1
    assert res.data.transactions[0].reference_number == "SBIN123456789012"
