"""Tests for Translation Span Protection and Restoration."""

from typing import Any

from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
from sarathi.shakti.translation.models import TranslationDirection
from sarathi.shakti.translation.protector import TranslationProtector


def test_factual_spans_and_identifiers_preserved_byte_for_byte(test_backend: Any) -> None:
    protector = TranslationProtector()
    engine = CTranslate2TranslationEngine(backend=test_backend, protector=protector)

    sample = (
        "दिनांक 15/08/2026 को खाता संख्या ACC-998811 में ₹ 1,50,000.50 जमा (100%) किए गए। "
        "विवरण https://sbi.co.in/txn तथा ईमेल contact@gov.in पर देखें।"
    )

    result = engine.translate(sample, direction=TranslationDirection.HI_TO_EN)
    translated = result.translated_text

    # Verify factual spans survive byte-for-byte
    assert "15/08/2026" in translated
    assert "ACC-998811" in translated
    assert "1,50,000.50" in translated
    assert "(100%)" in translated
    assert "https://sbi.co.in/txn" in translated
    assert "contact@gov.in" in translated


def test_span_protection_detects_corrupted_or_dropped_placeholders() -> None:
    """Verify restore_with_validation reports missing or duplicated placeholders."""
    from dataclasses import dataclass

    from sarathi.shakti.text.span_protection import BaseSpanProtector

    @dataclass
    class DummySpan:
        placeholder: str
        original_text: str

    protector = BaseSpanProtector()
    p0 = protector.format_placeholder(0)
    p1 = protector.format_placeholder(1)
    spans = [
        DummySpan(placeholder=p0, original_text="₹1000"),
        DummySpan(placeholder=p1, original_text="PAN-ABCDE1234F"),
    ]

    # Case 1: Model deleted p0 from output
    text_missing = f"The client paid and has PAN {p1}"
    restored, issues = protector.restore_with_validation(text_missing, spans)
    assert len(issues) == 1
    assert issues[0]["code"] == "PROTECTED_SPAN_MISSING"
    assert issues[0]["original_text"] == "₹1000"
    assert "PAN-ABCDE1234F" in restored

    # Case 2: Model duplicated p0 in output
    text_duplicated = f"The client paid {p0} twice: {p0}, with PAN {p1}"
    restored, issues = protector.restore_with_validation(text_duplicated, spans)
    assert len(issues) == 1
    assert issues[0]["code"] == "PROTECTED_SPAN_DUPLICATED"
    assert issues[0]["count"] == 2
    assert "₹1000 twice: ₹1000" in restored
