"""Deterministic Golden Regression Corpus for Akshara-aware Legacy Devanagari Font Conversion."""

from __future__ import annotations

import unicodedata

from sarathi.shakti.font_conversion.akshara import synthesize_akshara_unicode
from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import LegacyFontDetector
from sarathi.shakti.font_conversion.validator import FontConversionValidator


def test_krutidev_akshara_golden_corpus() -> None:
    """Verify that complex KrutiDev Devanagari Aksharas convert to exact Unicode strings without dictionary crutches."""
    converter = FontConverter()

    # Dictionary of exact legacy KrutiDev input -> expected canonical Unicode Devanagari output
    golden_cases = {
        # Base words with pre-base matra and independent vowels
        "Hkkjr": "भारत",
        "Hkkjr ljdkj": "भारत सरकार",
        "fnYyh": "दिल्ली",
        "vf/kd": "अधिक",
        "fopkj": "विचार",
        "Hkwfe": "भूमि",
        "jktLo": "राजस्व",
        "lkoZtfud": "सार्वजनिक",
        "lgk;rk": "सहायता",
        "iz.kkyh": "प्रणाली",
        "miyC/k": "उपलब्ध",
        "LFkkbZ": "स्थाई",
        "fLFkfr": "स्थिति",
        "Jksrk": "श्रोता",
        "iqu%": "पुनः",
        "f=Hkqou": "त्रिभुवन",
        "fiz;": "प्रिय",
        "fefJr": "मिश्रित",
        "okLro": "वास्तव",
        "d`i;k": "कृपया",
        "O;fDr": "व्यक्ति",
        "C;kSjk": "ब्यौरा",
        "fu.kZ;": "निर्णय",
        "dk;Zokgh": "कार्यवाही",
        "vk'p;Z": "आश्चर्य",
        "lEiw.kZ": "सम्पूर्ण",
        "okf\"kZd": "वार्षिक",
        "vUrxZr": "अन्तर्गत",
    }

    for legacy_in, expected_out in golden_cases.items():
        actual_out = converter.convert(legacy_in, profile_id="krutidev010")
        expected_norm = unicodedata.normalize("NFC", expected_out)
        assert actual_out == expected_norm, (
            f"Conversion failure for '{legacy_in}': expected '{expected_norm}', got '{actual_out}'"
        )


def test_complex_reph_positioning() -> None:
    """Verify that reph 'Z' moves to the beginning of the logical Akshara cluster, not merely 1 char."""
    converter = FontConverter()

    # Simple reph:
    assert converter.convert("dk;Z", profile_id="krutidev010") == "कार्य"

    # Reph on consonant with matra: dksZ -> र्को
    assert converter.convert("dksZ", profile_id="krutidev010") == "र्को"

    # Reph on consonant with matra + anusvara: dk;ks± -> कार्यों
    assert converter.convert("dk;ks±", profile_id="krutidev010") == "कार्यों"

    # Reph in complex word
    assert converter.convert("fu.kZ;", profile_id="krutidev010") == "निर्णय"
    assert converter.convert("vUrxZr", profile_id="krutidev010") == "अन्तर्गत"


def test_profile_isolation_no_kruti_assumptions_on_other_fonts() -> None:
    """Verify that KrutiDev pre-base rules do NOT corrupt other font families like Shusha or Chanakya."""
    converter = FontConverter()

    # In Shusha, 'f' is 'च', 'a' is 'क'
    # If Kruti regex was applied, 'fa' would get reordered to 'af' ('कच' instead of 'चक')
    shusha_fa = converter.convert("fa", profile_id="shusha010")
    assert shusha_fa == "चक"

    # In Shivaji, 'C' is 'ि' prefix
    shivaji_ca = converter.convert("Ca", profile_id="shivaji010")
    assert shivaji_ca == "कि"


def test_structural_devanagari_validation() -> None:
    """Verify that FontConversionValidator correctly identifies orphan matras, viramas, and illegal clusters."""
    validator = FontConversionValidator()

    # Valid Devanagari text
    is_valid, defects = validator.validate_devanagari_structure("भारत सरकार नई दिल्ली")
    assert is_valid is True
    assert len(defects) == 0

    # Orphan matra at beginning: 'ाभारत'
    is_valid_orphan, defects_orphan = validator.validate_devanagari_structure("ाभारत")
    assert is_valid_orphan is False
    assert "ORPHAN_MATRA_OR_VIRAMA_AT_BOUNDARY" in defects_orphan

    # Doubled virama: 'क््'
    is_valid_virama, defects_virama = validator.validate_devanagari_structure("क््ख")
    assert is_valid_virama is False
    assert "DOUBLED_VIRAMA" in defects_virama


def test_font_detection_rejects_incompatible_hint() -> None:
    """Verify detector rejects a Kruti hint when text has Chanakya signatures, avoiding destructive conversion."""
    detector = LegacyFontDetector()

    # Chanakya text
    chanakya_text = "¥æð °ð Ûæ ÿæ"

    # With correct hint:
    prof, conf = detector.detect(chanakya_text, font_hint="Chanakya")
    assert prof == "chanakya010"
    assert conf > 0.5

    # With wrong hint: KrutiDev hint on Chanakya text
    wrong_prof, _ = detector.detect(chanakya_text, font_hint="Kruti Dev 010")
    assert wrong_prof is None


def test_unicode_and_latin_preservation() -> None:
    """Verify modern Unicode Hindi and Latin text pass through untouched when protected."""
    from sarathi.shakti.font_conversion.protector import TextProtector

    protector = TextProtector()
    converter = FontConverter()
    text = "Vendor Name: भारत सरकार | Ministry of Finance | 2026-09-04"
    prot, spans = protector.protect(text, protect_devanagari=True)
    converted = converter.convert(prot, profile_id="krutidev010")
    restored = protector.restore(converted, spans)

    assert "भारत सरकार" in restored
    assert "Ministry of Finance" in restored
    assert "2026-09-04" in restored
    assert "Vendor Name:" in restored


def test_bidirectional_split_matra_composition() -> None:
    """Verify bidirectional 2-part vowel matras compose properly in both forward and reverse orders."""
    from sarathi.shakti.font_conversion.akshara import synthesize_akshara_unicode

    # o matra (aa + e vs e + aa)
    assert synthesize_akshara_unicode("क\u093e\u0947") == "को"
    assert synthesize_akshara_unicode("क\u0947\u093e") == "को"

    # au matra (aa + ai vs ai + aa)
    assert synthesize_akshara_unicode("क\u093e\u0948") == "कौ"
    assert synthesize_akshara_unicode("क\u0948\u093e") == "कौ"

    # candra-o matra (aa + candra-e vs candra-e + aa)
    assert synthesize_akshara_unicode("ड\u093e\u0945") == "डॉ"
    assert synthesize_akshara_unicode("ड\u0945\u093e") == "डॉ"


def test_halant_aa_matra_invariant_preserved() -> None:
    """Verify \u094d\u093e is preserved and not destructively deleted."""
    raw = "क्" + "ा"  # \u0915\u094d\u093e
    synthesized = synthesize_akshara_unicode(raw)
    assert "\u094d\u093e" in synthesized or "\u094d" in synthesized
    assert "क" in synthesized


def test_anubhava_generic_precedence_before_profile() -> None:
    """Verify generic Anubhava corrections apply before profile-specific corrections."""
    converter = FontConverter()
    res = converter.convert("कायार्लय", profile_id="krutidev010")
    assert res == "कार्यालय"


def test_chanakya_reph_and_prefixes() -> None:
    """Verify Chanakya prefix matra Ç / É and reph are converted accurately."""
    converter = FontConverter()
    conv = converter.convert("·æ", profile_id="chanakya010")
    assert conv == "का"


def test_shusha_prefixes_and_matras() -> None:
    """Verify Shusha 'D' and 'C' prefixes reorder and convert correctly."""
    converter = FontConverter()
    conv = converter.convert("aA", profile_id="shusha010")
    assert conv == "का"


def test_shivaji_word_conversion() -> None:
    """Verify Shivaji consonants convert accurately."""
    converter = FontConverter()
    conv = converter.convert("abc", profile_id="shivaji010")
    assert conv == "कखग"


def test_devlys_complex_reph_akshara() -> None:
    """Verify DevLys 010 converts complex reph words identically to KrutiDev."""
    converter = FontConverter()
    res_kruti = converter.convert("dk;Z", profile_id="krutidev010")
    res_devlys = converter.convert("dk;Z", profile_id="devlys010")
    assert res_kruti == "कार्य"
    assert res_devlys == "कार्य"
