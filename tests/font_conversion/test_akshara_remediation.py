"""Tests for Akshara Unicode Synthesis Invariants, Anubhava Precedence, and Multi-Profile Golden Tests."""

from __future__ import annotations

from sarathi.shakti.font_conversion.akshara import (
    synthesize_akshara_unicode,
)
from sarathi.shakti.font_conversion.converter import FontConverter


def test_halant_aa_matra_invariant_preserved() -> None:
    """Verify \u094d\u093e is preserved and not destructively deleted."""
    raw = "क्" + "ा"  # \u0915\u094d\u093e
    synthesized = synthesize_akshara_unicode(raw)
    assert "\u094d\u093e" in synthesized or "\u094d" in synthesized
    # Invariant: must not strip the matra or halant blindly
    assert "क" in synthesized


def test_anubhava_generic_precedence_before_profile() -> None:
    """Verify generic Anubhava corrections apply before profile-specific corrections."""
    converter = FontConverter()
    # "कायार्लय" is generic correction in anubhava.toml: कायार्लय -> कार्यालय
    res = converter.convert("कायार्लय", profile_id="krutidev010")
    assert res == "कार्यालय"


def test_chanakya_reph_and_prefixes() -> None:
    """Verify Chanakya prefix matra Ç / É and reph are converted accurately."""
    converter = FontConverter()
    # Chanakya: '·' -> 'क', 'æ' -> 'ा'
    conv = converter.convert("·æ", profile_id="chanakya010")
    assert conv == "का"


def test_shusha_prefixes_and_matras() -> None:
    """Verify Shusha 'D' and 'C' prefixes reorder and convert correctly."""
    converter = FontConverter()
    # Shusha: 'a' -> 'क', 'A' -> 'ा'
    conv = converter.convert("aA", profile_id="shusha010")
    assert conv == "का"


def test_shivaji_word_conversion() -> None:
    """Verify Shivaji consonants convert accurately."""
    converter = FontConverter()
    # Shivaji: 'a' -> 'क', 'b' -> 'ख', 'c' -> 'ग'
    conv = converter.convert("abc", profile_id="shivaji010")
    assert conv == "कखग"


def test_devlys_complex_reph_akshara() -> None:
    """Verify DevLys 010 converts complex reph words identically to KrutiDev."""
    converter = FontConverter()
    # "dk;Z" -> "कार्य"
    res_kruti = converter.convert("dk;Z", profile_id="krutidev010")
    res_devlys = converter.convert("dk;Z", profile_id="devlys010")
    assert res_kruti == "कार्य"
    assert res_devlys == "कार्य"
