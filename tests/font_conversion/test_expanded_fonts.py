"""Tests for Expanded Font Profiles (Chanakya, Shusha, Shivaji), TTF Extraction, and Normalization."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result
from sarathi.shakti.font_conversion.capability import FontConversionCapability
from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import (
    LegacyFontDetector,
    extract_ttf_font_family,
    load_font_profiles,
)


def test_expanded_profiles_loaded() -> None:
    """Verify Chanakya, Shusha, and Shivaji profiles are correctly loaded from data/fonts/."""
    profiles = load_font_profiles()
    assert "chanakya010" in profiles
    assert "shusha010" in profiles
    assert "shivaji010" in profiles
    assert "krutidev010" in profiles
    assert "devlys010" in profiles

    chanakya = profiles["chanakya010"]
    assert chanakya.family == "chanakya"
    assert "walkman-chanakya" in chanakya.aliases
    assert len(chanakya.mappings) > 50

    shusha = profiles["shusha010"]
    assert shusha.family == "shusha"
    assert "shusha" in shusha.aliases

    shivaji = profiles["shivaji010"]
    assert shivaji.family == "shivaji"
    assert "shivaji" in shivaji.aliases


def test_chanakya_word_conversion() -> None:
    """Verify Chanakya legacy mapping converts to valid Unicode."""
    converter = FontConverter()
    # Chanakya: '·' -> 'क', '¥æ' -> 'आ', '§' -> 'इ'
    raw_sample = "·¥æ§"
    conv = converter.convert(raw_sample, profile_id="chanakya010")
    assert "क" in conv
    assert "आ" in conv
    assert "इ" in conv


def test_shusha_word_conversion() -> None:
    """Verify Shusha legacy mapping converts to valid Unicode."""
    converter = FontConverter()
    # Shusha: 'a' -> 'क', 'A' -> 'ा', '1' -> 'र'
    raw_sample = "aA1"  # कार
    conv = converter.convert(raw_sample, profile_id="shusha010")
    assert conv == "कार"


def test_shivaji_word_conversion() -> None:
    """Verify Shivaji legacy mapping converts to valid Unicode."""
    converter = FontConverter()
    # Shivaji: 'a' -> 'क', 'b' -> 'ख'
    raw_sample = "ab"  # कख
    conv = converter.convert(raw_sample, profile_id="shivaji010")
    assert conv == "कख"


def test_typewriter_post_normalization() -> None:
    """Verify typewriter artifact post-normalization rules."""
    converter = FontConverter()
    # 1. Digits with ']' as typewriter comma: e.g. 50]000 -> 50,000 or ५०,०००
    res_num = converter.convert("50]000", profile_id="krutidev010")
    assert res_num in ("50,000", "५०,०००")

    # 2. Rupee shorthand prefix: ःपये -> रुपये
    res_inr = converter.convert("ःपये 500", profile_id="krutidev010")
    assert "रुपये" in res_inr

    # 3. Typist matra/reph inversion: कायार्लय -> कार्यालय
    res_off = converter.convert("कायार्लय", profile_id="krutidev010")
    assert res_off == "कार्यालय"


def test_ttf_font_family_extraction_valid_binary() -> None:
    """Verify binary TrueType SFNT name table parsing extracts the font name."""
    # Synthesize a minimal valid TrueType header with 'name' table
    font_name = "Walkman-Chanakya-905"
    name_bytes = font_name.encode("utf-16be")

    # Name table header: format=0, count=1, string_offset=18
    # Name record: platform_id=3, encoding_id=1, language_id=1033, name_id=1 (family), length, offset=0
    name_record = struct.pack(">HHHHHH", 3, 1, 1033, 1, len(name_bytes), 0)
    name_table_header = struct.pack(">HHH", 0, 1, 6 + 12)
    name_table_data = name_table_header + name_record + name_bytes

    # SFNT header: sfnt_version=0x00010000, num_tables=1, searchRange, entrySelector, rangeShift
    sfnt_header = struct.pack(">IH", 0x00010000, 1) + struct.pack(">HHH", 16, 0, 0)
    # Table directory entry: tag=b'name', checksum=0, offset=12 + 16, length=len(name_table_data)
    table_entry = struct.pack(">4sIII", b"name", 0, 28, len(name_table_data))

    ttf_binary = sfnt_header + table_entry + name_table_data
    extracted = extract_ttf_font_family(ttf_binary)
    assert extracted == font_name


def test_ttf_font_family_extraction_corrupt_or_truncated() -> None:
    """Verify binary extractor safely returns None for invalid or truncated TTF streams."""
    assert extract_ttf_font_family(b"") is None
    assert extract_ttf_font_family(b"CORRUPT_BYTES") is None
    assert extract_ttf_font_family(b"\x00\x01\x00\x00\x00\x01\x00\x00") is None


def test_font_conversion_selective_ocr_oracle_fallback() -> None:
    """Verify FontConversionCapability invokes visual oracle when text has unmapped font."""
    class MockVisualOracle:
        def recover_text(self, text: str) -> tuple[str, float]:
            return "पुनर्प्राप्त पाठ", 0.95

    oracle = MockVisualOracle()
    cap = FontConversionCapability(ocr_oracle=oracle)

    doc = CanonicalDocument(document_id="doc-unk", text="unmapped_legacy_token")
    prior = Result(data=doc)
    ctx = ExecutionContext("run-1", "req-1", "t-1", "s-1")
    inp = InputRef(input_id="inp-1", source_path=Path("sample.txt"), display_name="sample.txt", size_bytes=10)
    req = Request(request_id="req-1", requirement="font_conversion", inputs=(inp,))

    result = cap.execute(req, ctx, prior)
    assert result.data is not None
    assert result.data.text == "पुनर्प्राप्त पाठ"
    assert any(p.evidence.get("recovered_via") == "selective_ocr" for p in result.provenance)
