"""Tests for Kruti Dev 010 Legacy Font Conversion."""

from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import LegacyFontDetector
from sarathi.shakti.font_conversion.protector import TextProtector


def test_krutidev_detection() -> None:
    detector = LegacyFontDetector()
    text = "LVsV cSad vksj Hkkjr ljdkj dk vkns'k"
    prof_id, conf = detector.detect(text)

    assert prof_id == "krutidev010"
    assert conf > 0.5


def test_krutidev_word_conversion() -> None:
    converter = FontConverter()
    protector = TextProtector()

    # Pre-base matra f (choti-i)
    raw_kitab = "fdrkc"  # f + d (क) + r (त) + k (ा) + c (ब) -> किताब
    prot_k, spans_k = protector.protect(raw_kitab)
    conv_k = protector.restore(converter.convert(prot_k, "krutidev010"), spans_k)
    assert conv_k == "किताब"

    # Postfix reph Z (र्)
    raw_karya = "dk;Z"  # d (क) + k (ा) + ; (य) + Z (र्) -> कार्य
    prot_y, spans_y = protector.protect(raw_karya)
    conv_y = protector.restore(converter.convert(prot_y, "krutidev010"), spans_y)
    assert conv_y == "कार्य"


def test_mixed_latin_krutidev_preservation() -> None:
    converter = FontConverter()
    protector = TextProtector()

    raw_text = "Hkkjr Sarkar (Govt of India), Date: 15/08/2026, Amount: Rs. 50,000/-"
    protected, spans = protector.protect(raw_text)
    converted = converter.convert(protected, "krutidev010")
    final_text = protector.restore(converted, spans)

    assert "भारत" in final_text
    assert "Govt of India" in final_text
    assert "15/08/2026" in final_text
    assert "Rs. 50,000/-" in final_text
