"""Tests for Anubhava Approved Corrections Store."""

from sarathi.shakti.font_conversion.anubhava import AnubhavaStore
from sarathi.shakti.font_conversion.converter import FontConverter


def test_anubhava_corrections_loaded_and_applied() -> None:
    anubhava = AnubhavaStore()
    corrections = anubhava.get_corrections("krutidev010")

    assert "LVsV cSad" in corrections
    assert corrections["LVsV cSad"] == "स्टेट बैंक"

    converter = FontConverter(anubhava=anubhava)
    conv = converter.convert("LVsV cSad", "krutidev010")
    assert conv == "स्टेट बैंक"
