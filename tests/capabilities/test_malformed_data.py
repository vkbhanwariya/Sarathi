"""Regression tests for strict approved-data handling and malformed configuration/data files."""

from pathlib import Path

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import InputRef, Request
from sarathi.shakti.bank_statements.mapper import HeaderMapper
from sarathi.shakti.font_conversion.converter import _load_anubhava_corrections
from sarathi.shakti.translation.glossary import GlossaryStore


def test_translation_glossary_missing_file_preserves_baseline(tmp_path: Path) -> None:
    """Missing glossary.yaml should safely return empty dictionary."""
    store = GlossaryStore(glossary_dir=tmp_path)
    assert store.get_terms(direction="hi-en") == {}  # type: ignore[arg-type]


def test_translation_glossary_malformed_yaml_fails_deterministically(tmp_path: Path) -> None:
    """Malformed glossary.yaml must raise DoshError(INVALID_CONFIGURATION)."""
    bad_yaml = tmp_path / "glossary.yaml"
    bad_yaml.write_text("this: is: [invalid: yaml: syntax: {", encoding="utf-8")

    with pytest.raises(DoshError) as exc_info:
        GlossaryStore(glossary_dir=tmp_path)

    assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
    assert "Failed to parse translation glossary" in exc_info.value.message


def test_translation_glossary_non_list_entries_fails_deterministically(tmp_path: Path) -> None:
    """Glossary with invalid entries field must raise DoshError(INVALID_CONFIGURATION)."""
    bad_yaml = tmp_path / "glossary.yaml"
    bad_yaml.write_text("entries: 'not-a-list'\n", encoding="utf-8")

    with pytest.raises(DoshError) as exc_info:
        GlossaryStore(glossary_dir=tmp_path)

    assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION


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


def test_font_anubhava_missing_file_preserves_baseline(tmp_path: Path) -> None:
    """Missing anubhava.toml should safely return empty dictionary."""
    missing = tmp_path / "anubhava.toml"
    assert _load_anubhava_corrections(anubhava_path=missing) == {}


def test_font_anubhava_malformed_toml_fails_deterministically(tmp_path: Path) -> None:
    """Malformed anubhava.toml must raise DoshError(INVALID_CONFIGURATION)."""
    bad_toml = tmp_path / "anubhava.toml"
    bad_toml.write_text("[[corrections\nprofile_id = 'unclosed string\n", encoding="utf-8")

    with pytest.raises(DoshError) as exc_info:
        _load_anubhava_corrections(anubhava_path=bad_toml)

    assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
    assert "Failed to parse font conversion Anubhava TOML" in exc_info.value.message


def test_request_preserve_partial_strict_bool_validation(tmp_path: Path) -> None:
    """Request.preserve_partial must reject non-boolean inputs with TypeError."""
    dummy_file = tmp_path / "doc.txt"
    dummy_file.write_text("dummy", encoding="utf-8")
    inp = InputRef("inp-1", dummy_file, "doc.txt", 5)

    # Valid bools
    req_true = Request("req-1", "read_native", inputs=(inp,), preserve_partial=True)
    assert req_true.preserve_partial is True

    req_false = Request("req-2", "read_native", inputs=(inp,), preserve_partial=False)
    assert req_false.preserve_partial is False

    # Invalid non-bools
    for invalid in (1, 0, "true", "false", None, [True]):
        with pytest.raises(TypeError) as exc_info:
            Request("req-bad", "read_native", inputs=(inp,), preserve_partial=invalid)  # type: ignore[arg-type]
        assert "preserve_partial must be a bool" in str(exc_info.value)
