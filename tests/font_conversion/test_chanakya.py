"""Tests for Walkman Chanakya Legacy Font Conversion."""

from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import LegacyFontDetector
from sarathi.shakti.font_conversion.protector import TextProtector


def test_chanakya_detection_with_hint() -> None:
    detector = LegacyFontDetector()
    prof, conf = detector.detect("dke", font_hint="chanakya")
    assert prof == "chanakya"
    assert conf == 1.0


def test_chanakya_conversion() -> None:
    converter = FontConverter()
    protector = TextProtector()

    # d (क) + k (ा) + e (म) -> काम
    raw_kaam = "dke"
    prot, spans = protector.protect(raw_kaam)
    conv = protector.restore(converter.convert(prot, "chanakya"), spans)
    assert conv == "काम"
