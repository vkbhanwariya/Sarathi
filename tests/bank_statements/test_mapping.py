"""Tests for Bank Statement Header Mapping."""

import pytest

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
