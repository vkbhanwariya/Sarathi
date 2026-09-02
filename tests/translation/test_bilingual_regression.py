from typing import Any
"""Tests for Bilingual Sentence Translation Regression across both directions."""

from pathlib import Path
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
from sarathi.shakti.translation.models import TranslationDirection


def test_hindi_to_english_sentence_translation(test_backend: Any) -> None:
    engine = CTranslate2TranslationEngine(backend=test_backend)

    src = "भारतीय रिजर्व बैंक ने नई मौद्रिक नीति की घोषणा की।"
    res = engine.translate(src, direction=TranslationDirection.HI_TO_EN)

    assert "Reserve Bank of India" in res.translated_text
    assert "announced the new monetary policy" in res.translated_text


def test_english_to_hindi_sentence_translation(test_backend: Any) -> None:
    engine = CTranslate2TranslationEngine(backend=test_backend)

    src = "The applicant submitted the identity document on date 15/08/2026 for verification."
    res = engine.translate(src, direction=TranslationDirection.EN_TO_HI)

    assert "आवेदक ने सत्यापन के लिए" in res.translated_text
    assert "15/08/2026" in res.translated_text


def test_missing_runtime_and_model_fails_explicitly() -> None:
    """Verify missing local models or dependencies fails with DEPENDENCY_UNAVAILABLE without fallback."""
    engine = CTranslate2TranslationEngine(data_root=Path("/non/existent/translation/data"))

    with pytest.raises(DoshError) as exc_info:
        engine.translate("भारत सरकार", direction=TranslationDirection.HI_TO_EN)

    assert exc_info.value.code == FailureCode.DEPENDENCY_UNAVAILABLE
