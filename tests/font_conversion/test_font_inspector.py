"""Unit and Integration Tests for Binary Font Inspection and Profile Inheritance (Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import load_font_profiles
from sarathi.shakti.font_conversion.font_inspector import (
    BinaryFontMetadata,
    inspect_font_bytes,
)
from tools.audit_font_profile import audit_profile_fidelity

_SAMPLE_TTF = Path(".venv/Lib/site-packages/playwright/driver/package/lib/vite/traceViewer/codicon.DCmgc-ay.ttf")


def test_inspect_font_bytes_corrupted_or_empty_is_failsafe() -> None:
    """Zero crash or exception on corrupted, empty, or short bytes."""
    meta_empty = inspect_font_bytes(b"")
    assert isinstance(meta_empty, BinaryFontMetadata)
    assert meta_empty.family_name is None
    assert not meta_empty.is_modern_unicode
    assert not meta_empty.is_legacy_symbol

    meta_garbage = inspect_font_bytes(b"NOT_A_VALID_FONT_DATA" * 10)
    assert isinstance(meta_garbage, BinaryFontMetadata)
    assert meta_garbage.family_name is None


def test_inspect_real_ttf_metadata() -> None:
    """Inspect real TrueType font bytes from workspace virtualenv if present."""
    if not _SAMPLE_TTF.exists():
        pytest.skip("Sample TTF not available in current environment")

    font_bytes = _SAMPLE_TTF.read_bytes()
    meta = inspect_font_bytes(font_bytes)
    assert meta.family_name == "codicon"
    assert meta.postscript_name == "codicon"
    assert len(meta.cmap_platforms) > 0


def test_profile_inheritance_krutidev_base_abstract() -> None:
    """Verify that krutidev_base is marked abstract and not exposed as an active profile."""
    profiles = load_font_profiles()
    assert "krutidev_base" not in profiles
    assert "krutidev010" in profiles
    assert "krutidev011" in profiles
    assert "krutidev290" in profiles


def test_krutidev_variants_delta_behavior() -> None:
    """Verify variant delta behavior between Kruti Dev 010, 011, and 290."""
    converter = FontConverter()

    # 1. 010 vs 011 quote/halant-sh vs shr swap:
    # In 010: “ (U+201C, byte 147) -> श्, ‘ (U+2018, byte 145) -> श्र्
    # In 011: “ (U+201C, byte 147) -> श्र्, ‘ (U+2018, byte 145) -> श्
    res_010_sh = converter.convert("“", profile_id="krutidev010")
    res_011_sh = converter.convert("“", profile_id="krutidev011")
    assert res_010_sh == "श्"
    assert res_011_sh == "श्र्"

    res_010_shr = converter.convert("‘", profile_id="krutidev010")
    res_011_shr = converter.convert("‘", profile_id="krutidev011")
    assert res_010_shr == "श्र्"
    assert res_011_shr == "श्"

    # 2. 290 nukta behavior: byte ¤ (164) maps to nukta '़' in 290
    res_290_nukta = converter.convert("¤", profile_id="krutidev290")
    assert res_290_nukta == "़"

    # 3. Base inheritance verification: all variants inherit standard consonants and vowels
    # 'd' -> 'क', 'k' -> 'ा' => 'dk' -> 'का'
    for pid in ("krutidev010", "krutidev011", "krutidev290"):
        assert converter.convert("dk", profile_id=pid) == "का"
        assert converter.convert("fd", profile_id=pid) == "कि"
        assert converter.convert("dZ", profile_id=pid) == "र्क"


def test_audit_profile_fidelity_shivaji_and_kruti() -> None:
    """Verify profile fidelity auditor identifies 1:1 round-trips and intentional aliases."""
    profiles = load_font_profiles()
    converter = FontConverter(profiles=profiles)

    # Shivaji has 100% 1:1 canonical round-trip mappings
    summary_shivaji, records_shivaji = audit_profile_fidelity(profiles["shivaji010"], converter)
    assert summary_shivaji.pass_audit is True
    assert summary_shivaji.unexpected_loss_count == 0
    assert summary_shivaji.canonical_count == summary_shivaji.total_mappings

    # Krutidev010 has intentional aliases tracked by reverse_preferred
    summary_kruti, records_kruti = audit_profile_fidelity(profiles["krutidev010"], converter)
    assert summary_kruti.total_mappings > 150
    assert summary_kruti.canonical_count > 100
    assert summary_kruti.intentional_alias_count > 0
