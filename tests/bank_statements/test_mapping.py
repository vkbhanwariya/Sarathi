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
