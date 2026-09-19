"""SIL Differential Vector Regression Test Suite for Sarathi Font Conversion.

Validates pure-Python 7-pass font conversion against canonical SIL test vectors,
verifies P0 ASCII digit preservation, context rules, and Pramana telemetry metrics.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from sarathi.shakti.font_conversion import FontConverter

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sil"


def test_sil_krutidev_differential_vectors() -> None:
    """Verify KrutiDev 010 conversion against canonical SIL test vectors."""
    fixture_path = _FIXTURES_DIR / "krutidev010_sil_vectors.json"
    assert fixture_path.exists(), f"Missing fixture file: {fixture_path}"

    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    converter = FontConverter()

    for vec in data["vectors"]:
        res = converter.convert(vec["input"], profile_id="krutidev010")
        actual_norm = unicodedata.normalize("NFC", res)
        expected_norm = unicodedata.normalize("NFC", vec["expected"])
        assert actual_norm == expected_norm, (
            f"Vector '{vec['id']}' failed: expected '{expected_norm}', got '{actual_norm}'"
        )


def test_sil_shusha_differential_vectors() -> None:
    """Verify Shusha conversion against canonical SIL test vectors."""
    fixture_path = _FIXTURES_DIR / "shusha010_sil_vectors.json"
    assert fixture_path.exists(), f"Missing fixture file: {fixture_path}"

    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    converter = FontConverter()

    for vec in data["vectors"]:
        res = converter.convert(vec["input"], profile_id="shusha010")
        actual_norm = unicodedata.normalize("NFC", res)
        expected_norm = unicodedata.normalize("NFC", vec["expected"])
        assert actual_norm == expected_norm, (
            f"Vector '{vec['id']}' failed: expected '{expected_norm}', got '{actual_norm}'"
        )


def test_krutidev_ascii_digit_preservation() -> None:
    """Verify P0 fix: ASCII digits 0..9 are strictly preserved as Latin digits."""
    converter = FontConverter()

    # Date preservation
    date_res = converter.convert("19/09/2026", profile_id="krutidev010")
    assert date_res == "19/09/2026"
    assert all(c in "0123456789/" for c in date_res)

    # Section numbers
    sec_res = converter.convert("138", profile_id="krutidev010")
    assert sec_res == "138"

    # Monetary and phone / account numbers
    num_res = converter.convert("9876543210", profile_id="krutidev010")
    assert num_res == "9876543210"

    # Alt-code bytes convert to Devanagari numerals
    alt_res = converter.convert("\x83\x84\x85\x86\x87\x88\x89\x8a\x8b\x8c", profile_id="krutidev010")
    assert alt_res == "१२३४५६७८९०"


def test_declarative_telemetry_metrics() -> None:
    """Verify FontConversionResult and ProvenanceRecord telemetry capture operations."""
    converter = FontConverter()

    # Convert text with pre-base matra ('fd' -> 'कि') and reph ('dk;Z' -> 'कार्य')
    sample = "fd dk;Z"
    result = converter.convert_result(sample, profile_id="krutidev010")

    assert result.converted_text == "कि कार्य"
    assert result.mapped_chars_count > 0
    assert result.replacement_operations > 0
    assert result.reorder_operations >= 2  # 'f' pre-base and 'Z' reph reorders
    assert len(result.provenance) == 1
    assert result.provenance[0].stage == "font_conversion"
    assert result.provenance[0].evidence["profile_id"] == "krutidev010"

    # Convert text with unmapped high-byte legacy symbols
    sample_with_unmapped = "Hkkjr \xa9 \xae"
    res_unmapped = converter.convert_result(sample_with_unmapped, profile_id="krutidev010")
    # \xa9 is © (copyright) which is not in krutidev mappings
    assert isinstance(res_unmapped.unmapped_symbols_histogram, dict)
