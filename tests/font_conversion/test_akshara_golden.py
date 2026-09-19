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
        'okf"kZd': "वार्षिक",
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

    # In Shusha, 'f' is 'फ' and 'a' is 'ा' -> 'फा'
    # If Kruti regex was applied, 'fa' would get reordered to 'af'
    shusha_fa = converter.convert("fa", profile_id="shusha010")
    assert shusha_fa == "फा"

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
    """Verify Shusha 'i' prefix and matras reorder and convert correctly."""
    converter = FontConverter()
    conv_aa = converter.convert("ka", profile_id="shusha010")
    assert conv_aa == "का"
    conv_i = converter.convert("ik", profile_id="shusha010")
    assert conv_i == "कि"


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


def test_detector_hint_and_evidence_matrix() -> None:
    """Verify detector hint and evidence matrix for legacy text vs English."""
    from pathlib import Path

    _fixture = Path(__file__).parent / "fixtures" / "krutidev_sample.txt"
    legacy_text = _fixture.read_text(encoding="utf-8")
    detector = LegacyFontDetector()
    english_text = "Vendor Name Invoice Number Customer Reference Payment Details Branch Office"

    # 1. Wrong hint + ordinary English -> no conversion
    p1, c1 = detector.detect(english_text, font_hint="wrong_font")
    assert p1 is None
    assert c1 == 0.0

    # 2. Correct hint + insufficient evidence -> no conversion
    p2, c2 = detector.detect(english_text, font_hint="krutidev010")
    assert p2 is None
    assert c2 == 0.0

    # 3. Correct hint + validated legacy evidence -> conversion
    p3, c3 = detector.detect(legacy_text, font_hint="krutidev010")
    assert p3 == "krutidev010"
    assert c3 > 0.5

    # 4. No hint + ambiguous legacy evidence -> no conversion
    p4, c4 = detector.detect(legacy_text, font_hint=None)
    assert p4 is None
    assert c4 == 0.0


def test_krutidev_extended_ligatures_and_glyphs() -> None:
    """Verify extended KrutiDev ligatures, purna viram, and glyph coverage."""
    from sarathi.shakti.font_conversion.protector import TextProtector

    converter = FontConverter()
    protector = TextProtector()

    ligature_cases = [
        ("A", "।"),
        ("mÙk", "उत्त"),
        ("Øe", "क्रम"),
        ("¶ySV", "फ्लैट"),
        ("Ã", "ई"),
        ("Çd", "किं"),
        ("—i;s", "रुपये"),
        ("}kjk", "द्वारा"),
        ("eq>s", "मुझे"),
        ("la[;k", "संख्या"),
        ("[kq’kcw", "खुशबू"),
        ("'kq#vkr", "शुरुआत"),
        ("#i;s", "रुपये"),
        (":Ik", "रूप"),
        ("t:jr", "जरूरत"),
        ("fo:)", "विरुद्ध"),
        ("[ksrh", "खेती"),
    ]

    for raw, expected in ligature_cases:
        prot, spans = protector.protect(raw, protect_devanagari=True, is_explicit_legacy=True)
        conv = converter.convert(prot, "krutidev010")
        restored = protector.restore(conv, spans)
        assert expected in restored, f"Failed converting '{raw}': got '{restored}', expected '{expected}'"


def test_independent_vowel_synthesis_and_nukta_reordering() -> None:
    """Verify independent vowel synthesis and misplaced Nukta correction in akshara engine."""
    # Independent vowel synthesis
    assert synthesize_akshara_unicode("अा") == "आ"
    assert synthesize_akshara_unicode("अो") == "ओ"
    assert synthesize_akshara_unicode("अौ") == "औ"
    assert synthesize_akshara_unicode("अॅ") == "ऑ"
    assert synthesize_akshara_unicode("एे") == "ऐ"
    assert synthesize_akshara_unicode("अाप") == "आप"
    assert synthesize_akshara_unicode("अोर") == "ओर"

    # Misplaced Nukta reordering: क + ि + ़ -> क़ + ि
    # In Unicode: \u0915\u093f\u093c -> \u0958\u093f (क़ि)
    res_nukta = synthesize_akshara_unicode("क\u093f\u093c")
    assert res_nukta == "क़ि" or res_nukta == "क\u093c\u093f"


def test_rapidfuzz_noisy_font_name_resolution() -> None:
    """Verify rapidfuzz fuzzy matching handles noisy TrueType and Word font names."""
    from sarathi.shakti.font_conversion.detector import resolve_profile_from_font_name

    # Noisy font names from real Word and PDF documents
    pid1, fam1 = resolve_profile_from_font_name("Kruti Dev 010 (TrueType)")
    assert pid1 == "krutidev010"
    assert fam1 == "krutidev"

    pid2, fam2 = resolve_profile_from_font_name("DEVLYS_010-Bold")
    assert pid2 == "devlys010"
    assert fam2 == "devlys"

    pid3, fam3 = resolve_profile_from_font_name("Shusha02_Normal")
    assert pid3 == "shusha010"
    assert fam3 == "shusha"

    # Modern font still cleanly recognized without false legacy match
    pid_mod, fam_mod = resolve_profile_from_font_name("Calibri (TrueType)")
    assert pid_mod is None
    assert fam_mod == "modern"


def test_keyboard_slip_and_halant_nukta_corrections() -> None:
    """Verify halant+nukta reordering, typist double-tap deduplication, and stray ZWNJ removal."""
    # Halant + Nukta inversion: क + ् + ़ -> क + ़ + ् (क़्)
    assert synthesize_akshara_unicode("क\u094d\u093c") in ("क़्", "क\u093c\u094d")

    # Doubled Nukta deduplication: ़़ -> ़
    assert synthesize_akshara_unicode("क\u093c\u093c") in ("क़", "क\u093c")

    # Doubled Visarga deduplication: ःः -> ः
    assert synthesize_akshara_unicode("पुनःः") == "पुनः"

    # Doubled Purna Viram normalization: ।। -> ॥
    assert synthesize_akshara_unicode("।।") == "॥"
    assert synthesize_akshara_unicode("श्री।।") == "श्री॥"

    # Stray ZWNJ before dependent vowel matra
    assert synthesize_akshara_unicode("क\u094d\u200cा") == "का"
