from pathlib import Path

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.font_conversion.converter import FontConverter, _load_anubhava_corrections


def test_anubhava_corrections_loaded_and_applied() -> None:
    corrections = _load_anubhava_corrections().get("krutidev010", {})

    assert "LVsV cSad" in corrections
    assert corrections["LVsV cSad"] == "स्टेट बैंक"

    converter = FontConverter()
    conv = converter.convert("LVsV cSad", "krutidev010")
    assert conv == "स्टेट बैंक"


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


def test_font_conversion_asset_version_tracks_default_and_custom_anubhava(tmp_path: Path) -> None:
    """Item 24: Font conversion capability includes canonical default and custom anubhava in revision."""
    from sarathi.shakti.font_conversion.capability import FontConversionCapability

    # Canonical default anubhava is hashed when anubhava_path is omitted
    cap_default = FontConversionCapability()
    assert len(cap_default.asset_version) == 16

    # Custom anubhava path changes revision
    custom_anubhava = tmp_path / "anubhava.toml"
    custom_anubhava.write_text('corrections = [{profile_id="krutidev010", verified=true, source="foo", target="बार"}]\n', encoding="utf-8")
    cap_custom = FontConversionCapability(anubhava_path=custom_anubhava)
    assert cap_custom.asset_version != cap_default.asset_version

    # Modifying contents changes revision
    custom_anubhava.write_text('corrections = [{profile_id="krutidev010", verified=true, source="foo", target="बज़"}]\n', encoding="utf-8")
    cap_modified = FontConversionCapability(anubhava_path=custom_anubhava)
    assert cap_modified.asset_version != cap_custom.asset_version

