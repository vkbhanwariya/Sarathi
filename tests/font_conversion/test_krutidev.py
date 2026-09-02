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
