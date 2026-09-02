"""Tests for Font Conversion Anubhava Approved Corrections Data."""

from sarathi.shakti.font_conversion.converter import FontConverter, _load_anubhava_corrections


def test_anubhava_corrections_loaded_and_applied() -> None:
    corrections = _load_anubhava_corrections().get("krutidev010", {})

    assert "LVsV cSad" in corrections
    assert corrections["LVsV cSad"] == "स्टेट बैंक"

    converter = FontConverter()
    conv = converter.convert("LVsV cSad", "krutidev010")
    assert conv == "स्टेट बैंक"
