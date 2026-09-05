"""Tests for Kruti Dev 010 Legacy Font Conversion and Hint-Evidence Matrix."""

from pathlib import Path

from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import LegacyFontDetector
from sarathi.shakti.font_conversion.protector import TextProtector

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "krutidev_sample.txt"


def test_detector_hint_and_evidence_matrix() -> None:
    detector = LegacyFontDetector()
    english_text = "Vendor Name Invoice Number Customer Reference Payment Details Branch Office"
    legacy_text = _FIXTURE_PATH.read_text(encoding="utf-8")

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

    # 4. No hint + validated legacy evidence -> conversion
    p4, c4 = detector.detect(legacy_text, font_hint=None)
    assert p4 == "krutidev010"
    assert c4 > 0.5


def test_krutidev_word_conversion() -> None:
    converter = FontConverter()
    protector = TextProtector()

    # Pre-base matra f (choti-i)
    raw_kitab = "fdrkc"  # किताब
    prot_k, spans_k = protector.protect(raw_kitab)
    conv_k = protector.restore(converter.convert(prot_k, "krutidev010"), spans_k)
    assert conv_k == "किताब"

    # Postfix reph Z (र्)
    raw_karya = "dk;Z"  # कार्य
    prot_y, spans_y = protector.protect(raw_karya)
    conv_y = protector.restore(converter.convert(prot_y, "krutidev010"), spans_y)
    assert conv_y == "कार्य"


def test_krutidev_extended_ligatures_and_purna_viram() -> None:
    """Verify extended KrutiDev ligatures (त्त, क्र, फ्, ई, िं, रु, द्व) and purna viram (।) convert accurately."""
    converter = FontConverter()
    protector = TextProtector()

    # Purna viram A -> ।
    assert converter.convert("A", "krutidev010") == "।"

    # \u00d9k -> त्त (e.g. mÙk -> उत्त)
    assert converter.convert("mÙk", "krutidev010") == "उत्त"

    # \u00d8 -> क्र (e.g. Øe -> क्रम)
    assert converter.convert("Øe", "krutidev010") == "क्रम"

    # \xb6 -> फ् (e.g. ¶ySV -> फ्लैट)
    assert converter.convert("¶ySV", "krutidev010") == "फ्लैट"

    # \xc3 -> ई (e.g. Ã -> ई)
    assert converter.convert("Ã", "krutidev010") == "ई"

    # \xc7 -> िं (e.g. Çd -> कि)
    assert converter.convert("Çd", "krutidev010") == "किं"

    # \u2014 -> रु (e.g. —i;s -> रुपये)
    assert converter.convert("—i;s", "krutidev010") == "रुपये"

    # } -> द्व (e.g. }kjk -> द्वारा)
    assert converter.convert("}kjk", "krutidev010") == "द्वारा"


def test_krutidev_verified_glyph_coverage() -> None:
    """Verify newly mapped Kruti Dev characters and multichar sequences from verified fixture evidence."""
    converter = FontConverter()
    protector = TextProtector()

    vectors = [
        ("eq>s", "मुझे"),
        ("eq>", "मुझ"),
        ("le>uk", "समझना"),
        ("le>rs", "समझते"),
        ("la[;k", "संख्या"),
        ("[kq’kcw", "खुशबू"),
        ("'kq#vkr", "शुरुआत"),
        ("#i;s", "रुपये"),
        (":Ik", "रूप"),
        (":Ik;s", "रुपये"),
        (":I;s", "रुपये"),
        ("t:jr", "जरूरत"),
        ("fo:)", "विरुद्ध"),
        ("Vh fo’kqf)", "टी विशुद्धि"),
        ("c['kh’kukek", "बख्शीशनामा"),
        ("[ksrh", "खेती"),
    ]

    for raw, expected in vectors:
        prot, spans = protector.protect(raw, protect_devanagari=True, is_explicit_legacy=True)
        conv = converter.convert(prot, "krutidev010")
        restored = protector.restore(conv, spans)
        assert expected in restored, f"Failed converting '{raw}': got '{restored}', expected '{expected}'"
