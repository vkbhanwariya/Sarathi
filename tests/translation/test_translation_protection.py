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
