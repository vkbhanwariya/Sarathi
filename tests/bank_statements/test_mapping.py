from pathlib import Path

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.bank_statements.mapper import HeaderMapper


def test_map_standard_headers() -> None:
    mapper = HeaderMapper()
    headers = ["Txn Date", "Value Date", "Description", "Ref No", "Cheque No", "Debit", "Credit", "Balance"]
    mappings = mapper.map_headers(headers)

    mapping_dict = {m.canonical_field: m.source_header for m in mappings}
    assert mapping_dict["date"] == "Txn Date"
    assert mapping_dict["value_date"] == "Value Date"
    assert mapping_dict["description"] == "Description"
    assert mapping_dict["reference_number"] == "Ref No"
    assert mapping_dict["cheque_number"] == "Cheque No"
    assert mapping_dict["debit"] == "Debit"
    assert mapping_dict["credit"] == "Credit"
    assert mapping_dict["balance"] == "Balance"


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


def test_chq_and_chq_no_map_strictly_to_cheque_number() -> None:
    """chq or chq no. must strictly map to cheque_number and never to reference_number."""
    mapper = HeaderMapper()
    # 1. Single chq no header
    headers1 = ["Date", "Description", "Chq No.", "Debit", "Credit", "Balance"]
    mappings1 = {m.canonical_field: m.source_header for m in mapper.map_headers(headers1)}
    assert mappings1.get("cheque_number") == "Chq No."
    assert "reference_number" not in mappings1

    # 2. Both Ref No and Chq No present
    headers2 = ["Date", "Description", "Ref No", "Chq No", "Debit", "Credit", "Balance"]
    mappings2 = {m.canonical_field: m.source_header for m in mapper.map_headers(headers2)}
    assert mappings2.get("reference_number") == "Ref No"
    assert mappings2.get("cheque_number") == "Chq No"

    # 3. Chq without 'no'
    headers3 = ["Date", "Description", "CHQ", "Withdrawal", "Deposit", "Balance"]
    mappings3 = {m.canonical_field: m.source_header for m in mapper.map_headers(headers3)}
    assert mappings3.get("cheque_number") == "CHQ"
    assert "reference_number" not in mappings3

    # 4. Pure reference headers map strictly to reference_number and never cheque_number
    for ref_header in ("Ref No", "Ref No.", "Reference No", "UTR", "Txn ID", "Journal No"):
        headers_ref = ["Date", "Description", ref_header, "Debit", "Credit", "Balance"]
        mappings_ref = {m.canonical_field: m.source_header for m in mapper.map_headers(headers_ref)}
        assert mappings_ref.get("reference_number") == ref_header, f"Failed for {ref_header}"
        assert "cheque_number" not in mappings_ref, f"Unexpected cheque_number mapped for {ref_header}"

    # 5. Combined cheque/ref headers map consistently to reference_number
    for comb_header in ("Chq/Ref No", "Chq./Ref.No.", "Cheque/Ref No", "Ref No/Cheque No", "Ref/Chq No"):
        headers_comb = ["Date", "Description", comb_header, "Debit", "Credit", "Balance"]
        mappings_comb = {m.canonical_field: m.source_header for m in mapper.map_headers(headers_comb)}
        assert mappings_comb.get("reference_number") == comb_header, f"Failed for {comb_header}"
        assert "cheque_number" not in mappings_comb, f"Unexpected cheque_number mapped for combined {comb_header}"


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


def test_resolve_best_profile_matches_schema(tmp_path: Path) -> None:
    """HeaderMapper.resolve_best_profile dynamically identifies format-isolated bank profile."""
    prof_yaml = tmp_path / "sbi_pdf_fmt1.yaml"
    prof_yaml.write_text(
        """
profile_id: "sbi_pdf_fmt1"
parent_bank: "sbi"
bank_name: "State Bank of India"
container_format: "pdf"
headers:
  date: ["txn date"]
  value_date: ["value date"]
  description: ["description"]
  reference_number: ["ref no", "reference no"]
  debit: ["debit"]
  credit: ["credit"]
  balance: ["balance"]
""",
        encoding="utf-8",
    )
    mapper = HeaderMapper(banks_dir=tmp_path)
    headers = ["Txn Date", "Value Date", "Description", "Ref No", "Debit", "Credit", "Balance"]
    best_profile, mappings, score = mapper.resolve_best_profile(headers, candidate_profile="generic")
    assert best_profile == "sbi_pdf_fmt1"
    assert score > 10.0
    mapped_fields = {m.canonical_field for m in mappings}
    assert "date" in mapped_fields
    assert "reference_number" in mapped_fields
    assert "balance" in mapped_fields


def test_extract_sample_data_rows() -> None:
    """extract_sample_data_rows must sample first 3, middle distributed, and last 3 rows."""
    from sarathi.shakti.bank_statements.mapper import extract_sample_data_rows

    # Short table <= 8 rows returns all rows
    short_rows = [(f"row_{i}",) for i in range(5)]
    assert extract_sample_data_rows(short_rows) == tuple(short_rows)

    # Long table with 20 rows: head (0, 1, 2), mid, tail (17, 18, 19)
    long_rows = [(f"row_{i}",) for i in range(20)]
    sampled = extract_sample_data_rows(long_rows, head_count=3, mid_count=2, tail_count=3)
    assert len(sampled) == 8
    sampled_indices = [int(r[0].split("_")[1]) for r in sampled]
    assert sampled_indices[:3] == [0, 1, 2]
    assert sampled_indices[-3:] == [17, 18, 19]
    # Middle indices must lie strictly between head and tail
    assert 2 < sampled_indices[3] < sampled_indices[4] < 17


def test_resolve_best_profile_with_sample_rows_boosts_confidence(tmp_path: Path) -> None:
    """Providing factual sample rows validates data types and boosts mapping confidence score."""
    prof_yaml = tmp_path / "sbi_pdf_fmt1.yaml"
    prof_yaml.write_text(
        """
profile_id: "sbi_pdf_fmt1"
parent_bank: "sbi"
bank_name: "State Bank of India"
headers:
  date: ["txn date"]
  value_date: ["value date"]
  description: ["description"]
  reference_number: ["ref no", "reference no"]
  debit: ["debit"]
  credit: ["credit"]
  balance: ["balance"]
""",
        encoding="utf-8",
    )
    mapper = HeaderMapper(banks_dir=tmp_path)
    headers = ["Txn Date", "Value Date", "Description", "Ref No", "Debit", "Credit", "Balance"]
    sample_rows = [
        ("01/01/2026", "01/01/2026", "SALARY CREDIT", "REF100", "", "50,000.00", "50,000.00"),
        ("05/01/2026", "05/01/2026", "ELECTRICITY BILL", "REF101", "1,500.00", "", "48,500.00"),
        ("10/01/2026", "10/01/2026", "GROCERY STORE", "REF102", "3,200.00", "", "45,300.00"),
    ]

    # Without sample rows
    _, _, score_no_samples = mapper.resolve_best_profile(headers, candidate_profile="sbi_pdf_fmt1")

    # With sample rows verifying dates, decimals, and descriptions
    prof_with_samples, _, score_with_samples = mapper.resolve_best_profile(
        headers, candidate_profile="sbi_pdf_fmt1", sample_rows=sample_rows
    )

    assert prof_with_samples == "sbi_pdf_fmt1"
    assert score_with_samples > score_no_samples


def test_currency_detection_narration_isolation_defaults_to_inr() -> None:
    """Narration mentioning foreign currencies with exchange rates must not override statement INR currency."""
    from sarathi.sankalpa import CanonicalDocument, PageData, TableData
    from sarathi.shakti.bank_statements.capability import detect_statement_currency

    # 1. Narration mentioning foreign currency (USD) and forex rate must remain INR
    t_inr = TableData(
        name="t1",
        headers=("Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(("01/01/2026", "POS 401284XXXXXX0001 STEAM GAMES SEATTLE WA USD 14.99 @ 84.50", "1,266.65", "", "45,000.00"),),
    )
    doc_inr = CanonicalDocument(
        document_id="d_inr",
        text="State Bank of India Statement. Transaction: USD 14.99 @ 84.50 + Markup fee $1.20.",
        pages=(PageData(page_number=1, text="USD 14.99 @ 84.50", tables=(t_inr,)),),
        tables=(t_inr,),
    )
    assert detect_statement_currency(doc_inr) == "INR", "Narration mentioning USD/rates must not alter INR denomination"

    # 2. Narration mentioning EUR or other foreign currencies remains INR
    t_eur = TableData(
        name="t2",
        headers=("Date", "Narration", "Withdrawal", "Deposit", "Balance"),
        rows=(("02/01/2026", "HOTEL BERLIN EUR 120.00 RATE 91.50", "10,980.00", "", "34,020.00"),),
    )
    doc_eur = CanonicalDocument(
        document_id="d_eur",
        text="HDFC Bank Statement. EUR hotel booking.",
        pages=(PageData(page_number=1, text="EUR 120.00", tables=(t_eur,)),),
        tables=(t_eur,),
    )
    assert detect_statement_currency(doc_eur) == "INR", "Narration mentioning EUR must remain INR"

    # 3. Explicit labeled currency or document metadata is respected
    doc_explicit = CanonicalDocument(
        document_id="d_exp",
        text="Account Statement\nCurrency: USD\nAccount No: 123456789",
        tables=(t_inr,),
    )
    assert detect_statement_currency(doc_explicit) == "USD", "Explicit labeled Currency: USD must be respected"


def test_explicit_ref_col_not_converted_to_cheque(tmp_path: Path) -> None:
    """Explicit 'Ref No' column with 6-digit number and 'Cash deposit' must remain reference_number."""
    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, PageData, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    table = TableData(
        name="t_ref",
        headers=("Date", "Narration", "Ref No", "Debit", "Credit", "Balance"),
        rows=(("01/01/2026", "Cash deposit at branch", "123456", "", "10,000.00", "50,000.00"),),
    )
    doc = CanonicalDocument(
        document_id="d_ref",
        text="Account Statement HDFC Bank",
        pages=(PageData(page_number=1, text="HDFC Bank", tables=(table,)),),
        tables=(table,),
    )

    cap = BankStatementCapability()
    req = Request(
        request_id="req1",
        requirement="bank_statements",
        inputs=(InputRef("i1", tmp_path / "stmt.csv", "stmt.csv", 100),),
    )
    ctx = ExecutionContext("run1", "req1", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    tx = res.data.statements[0].transactions[0]
    assert tx.reference_number == "123456", f"Expected reference_number='123456', got {tx.reference_number}"
    assert tx.cheque_number is None, f"Expected cheque_number=None on explicit Ref No column, got {tx.cheque_number}"


def test_mixed_currency_totals_none(tmp_path: Path) -> None:
    """Mixed-currency consolidation must yield total_debit=None, total_credit=None, and populate totals_by_currency."""
    from decimal import Decimal

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, PageData, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    t_usd = TableData(
        name="t_usd",
        headers=("Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(("01/01/2026", "US Consulting", "100.00", "", "1,000.00"),),
    )
    doc_usd = CanonicalDocument(
        document_id="d_usd",
        text="Account Statement\nCurrency: USD",
        metadata={"currency": "USD"},
        pages=(PageData(page_number=1, text="Account Statement\nCurrency: USD", tables=(t_usd,)),),
        tables=(t_usd,),
    )

    t_inr = TableData(
        name="t_inr",
        headers=("Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(("01/01/2026", "India Vendor", "200.00", "", "2,000.00"),),
    )
    doc_inr = CanonicalDocument(
        document_id="d_inr",
        text="Account Statement\nCurrency: INR",
        metadata={"currency": "INR"},
        pages=(PageData(page_number=1, text="Account Statement\nCurrency: INR", tables=(t_inr,)),),
        tables=(t_inr,),
    )

    cap = BankStatementCapability()
    req = Request(
        request_id="req_mix",
        requirement="bank_statements",
        inputs=(
            InputRef("i_usd", tmp_path / "usd.csv", "usd.csv", 100),
            InputRef("i_inr", tmp_path / "inr.csv", "inr.csv", 100),
        ),
    )
    ctx = ExecutionContext("run_mix", "req_mix", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=(doc_usd, doc_inr)))

    consolidation = res.data
    assert consolidation.total_debit is None, f"Expected total_debit=None for mixed currencies, got {consolidation.total_debit}"
    assert consolidation.total_credit is None, f"Expected total_credit=None for mixed currencies, got {consolidation.total_credit}"
    assert "USD" in consolidation.totals_by_currency
    assert "INR" in consolidation.totals_by_currency
    assert consolidation.totals_by_currency["USD"][0] == Decimal("100.00")
    assert consolidation.totals_by_currency["INR"][0] == Decimal("200.00")
    assert any(i.code == "MIXED_CURRENCIES" for i in consolidation.issues)
