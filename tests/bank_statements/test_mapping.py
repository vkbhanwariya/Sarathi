from pathlib import Path

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.bank_statements.mapper import HeaderMapper


def test_map_sbi_headers_exact() -> None:
    mapper = HeaderMapper()
    headers = ["Txn Date", "Value Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"]
    mappings = mapper.map_headers(headers, profile_id="sbi")

    mapping_dict = {m.canonical_field: m.source_header for m in mappings}
    assert "date" in mapping_dict
    assert "description" in mapping_dict
    assert "reference_number" in mapping_dict
    assert "debit" in mapping_dict
    assert "credit" in mapping_dict
    assert "balance" in mapping_dict


def test_map_generic_headers() -> None:
    mapper = HeaderMapper()
    headers = ["Date", "Narration", "Chq No", "Withdrawal", "Deposit", "Closing Balance"]
    mappings = mapper.map_headers(headers)

    mapping_dict = {m.canonical_field: m.source_header for m in mappings}
    assert mapping_dict["date"] == "Date"
    assert mapping_dict["description"] == "Narration"
    assert mapping_dict["cheque_number"] == "Chq No"
    assert mapping_dict["debit"] == "Withdrawal"
    assert mapping_dict["credit"] == "Deposit"
    assert mapping_dict["balance"] == "Closing Balance"


def test_bank_mapper_malformed_yaml_fails_deterministically(tmp_path: Path) -> None:
    """Malformed bank profile YAML must raise DoshError(INVALID_CONFIGURATION)."""
    bad_yaml = tmp_path / "sbi.yaml"
    bad_yaml.write_text("profile_id: sbi\nheaders: [invalid: yaml: {", encoding="utf-8")

    with pytest.raises(DoshError) as exc_info:
        HeaderMapper(banks_dir=tmp_path)

    assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
    assert "Failed to parse bank profile" in exc_info.value.message


def test_bank_mapper_non_dict_root_fails_deterministically(tmp_path: Path) -> None:
    """Bank profile with non-mapping root must raise DoshError(INVALID_CONFIGURATION)."""
    bad_yaml = tmp_path / "custom.yaml"
    bad_yaml.write_text("- item1\n- item2\n", encoding="utf-8")

    with pytest.raises(DoshError) as exc_info:
        HeaderMapper(banks_dir=tmp_path)

    assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION


def test_map_indian_banking_parenthetical_headers() -> None:
    """Proves parenthetical currency/direction markers are normalized and matched accurately."""
    mapper = HeaderMapper()
    # Typical Axis, BOB, Kotak, PNB header variant
    headers = ["Tran Date", "Particulars", "CHQNO", "Withdrawal(Dr)", "Deposit(Cr)", "Balance(INR)"]
    mappings = mapper.map_headers(headers)

    mapping_dict = {m.canonical_field: m.source_header for m in mappings}
    assert mapping_dict["date"] == "Tran Date"
    assert mapping_dict["description"] == "Particulars"
    assert mapping_dict["cheque_number"] == "CHQNO"
    assert mapping_dict["debit"] == "Withdrawal(Dr)"
    assert mapping_dict["credit"] == "Deposit(Cr)"
    assert mapping_dict["balance"] == "Balance(INR)"


def test_parse_date_and_typed_cell_preservation() -> None:
    """Verify that typed datetime objects and ISO strings from spreadsheets preserve dates without dropping."""
    from datetime import date, datetime

    from sarathi.shakti.bank_statements.converter import parse_date

    # Typed datetime object directly from openpyxl / calamine
    dt = datetime(2025, 1, 15, 0, 0, 0)
    assert parse_date(dt) == date(2025, 1, 15)

    # Typed date object
    d = date(2025, 1, 15)
    assert parse_date(d) == date(2025, 1, 15)

    # Stringified spreadsheet datetime: "2025-01-01 00:00:00"
    assert parse_date("2025-01-01 00:00:00") == date(2025, 1, 1)

    # ISO string with T: "2025-01-01T00:00:00"
    assert parse_date("2025-01-01T00:00:00") == date(2025, 1, 1)

    # Indian bank format with timestamp: "15/01/2025 14:30:00"
    assert parse_date("15/01/2025 14:30:00") == date(2025, 1, 15)


def test_bank_capability_with_typed_datetime_rows() -> None:
    """Verify BankStatementCapability extracts transactions when table rows contain typed datetime/Decimal objects."""
    from datetime import datetime
    from decimal import Decimal
    from pathlib import Path

    from sarathi.sankalpa import (
        CanonicalDocument,
        ExecutionContext,
        ExecutionProfile,
        InputRef,
        Request,
        Result,
        TableData,
    )
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    cap = BankStatementCapability()
    table = TableData(
        headers=("Date", "Description", "Debit", "Credit", "Balance"),
        rows=(
            (datetime(2025, 1, 1, 0, 0, 0), "Opening balance", None, None, Decimal("10000.00")),
            (datetime(2025, 1, 5, 0, 0, 0), "Salary credit", None, Decimal("50000.00"), Decimal("60000.00")),
            (datetime(2025, 1, 10, 0, 0, 0), "ATM withdrawal", Decimal("5000.00"), None, Decimal("55000.00")),
        ),
    )
    doc = CanonicalDocument(
        document_id="doc-typed-spreadsheet",
        text="",
        tables=(table,),
    )
    req = Request(
        request_id="req-typed",
        requirement="bank_statements",
        inputs=(InputRef(input_id="inp-1", source_path=Path("dummy.xlsx"), display_name="dummy.xlsx", size_bytes=100),),
        profile=ExecutionProfile.ACCURATE,
    )
    ctx = ExecutionContext(run_id="run-typed", request_id="req-typed", trace_id="trace-typed", span_id="span-typed")
    res = cap.execute(request=req, prior_result=Result(data=doc), context=ctx)
    assert res is not None
    assert res.data is not None
    assert len(res.data.statements) == 1
    stmt = res.data.statements[0]
    assert len(stmt.transactions) == 2
    assert stmt.transactions[0].transaction_date == datetime(2025, 1, 5).date()
    assert stmt.transactions[1].transaction_date == datetime(2025, 1, 10).date()
    assert not any(issue.code == "INVALID_TRANSACTION_DATE" for issue in stmt.issues)


def test_header_fuzzy_scoring_runner_up_margin() -> None:
    """0.85 <= score < 0.92 only accepted if margin over runner up is >= 0.05."""
    mapper = HeaderMapper()
    mappings = mapper.map_headers(["Withdrawl", "Deposit", "Date"])
    mapped_dict = {m.source_header: m.canonical_field for m in mappings}
    assert mapped_dict.get("Withdrawl") == "debit"
