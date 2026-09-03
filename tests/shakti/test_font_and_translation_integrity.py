"""Regression tests for Font Conversion and Translation Core Integrity."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from sarathi.dosh import DoshError
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    PageData,
    Request,
    Result,
    TextSpan,
)
from sarathi.shakti.font_conversion.capability import FontConversionCapability
from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import LegacyFontDetector
from sarathi.shakti.translation.capability import TranslationCapability
from sarathi.shakti.translation.detector import LanguageDetector
from sarathi.shakti.translation.engine import CTranslate2TranslationEngine, TranslatorBackend


def test_devlys_detection_with_hint() -> None:
    """Verify LegacyFontDetector matches DevLys profile when hint is provided."""
    detector = LegacyFontDetector()
    sample_text = "LVsV cSad vksj Hkkjr ljdkj"  # Has legacy Remington signatures

    prof_id, conf = detector.detect(sample_text, font_hint="DevLys 010")
    assert prof_id == "devlys010"
    assert conf > 0.5


def test_missing_target_font_profile_raises_dosh_error() -> None:
    """Verify convert_to_legacy rejects unknown target profile without fallback."""
    converter = FontConverter()
    with pytest.raises(DoshError) as exc_info:
        converter.convert_to_legacy("मानक हिंदी", target_profile_id="non_existent_font_profile")
    assert "Requested target font profile is not supported or loaded" in exc_info.value.message


def test_font_conversion_preserves_page_spans() -> None:
    """Verify FontConversionCapability preserves PageData.spans."""
    cap = FontConversionCapability()
    span = TextSpan(
        text="Sample",
        confidence=0.98,
        bounding_box=(1.0, 2.0, 3.0, 4.0),
    )
    page = PageData(page_number=1, text="LVsV cSad", spans=(span,))
    doc = CanonicalDocument(
        document_id="doc_font_spans",
        source_input_id="in_font",
        text="LVsV cSad",
        pages=(page,),
    )

    req = Request(
        request_id="r1",
        requirement="font_conversion",
        inputs=(InputRef("in_font", Path("f.txt"), "f.txt", 10),),
    )
    ctx = ExecutionContext("run1", "r1", "tr1", "sp1")
    prior = Result(data=doc)

    res = cap.execute(request=req, context=ctx, prior_result=prior)
    assert isinstance(res.data, CanonicalDocument)
    assert len(res.data.pages) == 1
    assert len(res.data.pages[0].spans) == 1
    assert res.data.pages[0].spans[0].bounding_box == (1.0, 2.0, 3.0, 4.0)


def test_translation_unknown_language_raises_dosh_error() -> None:
    """Verify LanguageDetector rejects unknown language and unsupported directions."""
    detector = LanguageDetector()

    # Unknown language text without explicit direction must raise DoshError
    with pytest.raises(DoshError) as exc_info:
        detector.resolve_direction("12345 !@#$%")
    assert "Unable to detect language from input text" in exc_info.value.message

    # Invalid requested direction must raise DoshError
    with pytest.raises(DoshError) as exc_info2:
        detector.resolve_direction("Hello world", requested_direction="es-fr")
    assert "Unsupported or invalid translation direction" in exc_info2.value.message


class DummyMockTranslationBackend(TranslatorBackend):
    """Simple mock translation backend for testing capability and batching."""

    def translate_sentences(self, sentences: list[str], direction) -> list[str]:
        return [f"Translated({s})" for s in sentences]


def test_translation_batch_documents_and_spans() -> None:
    """Verify TranslationCapability processes tuple of CanonicalDocuments and preserves spans."""
    cap = TranslationCapability(backend=DummyMockTranslationBackend())

    span1 = TextSpan(text="Hello", confidence=0.9, bounding_box=(10.0, 20.0, 30.0, 40.0))
    doc1 = CanonicalDocument(
        document_id="doc_1",
        source_input_id="in_1",
        text="Hello world",
        pages=(PageData(page_number=1, text="Hello world", spans=(span1,)),),
    )

    span2 = TextSpan(text="Greeting", confidence=0.95, bounding_box=(50.0, 60.0, 70.0, 80.0))
    doc2 = CanonicalDocument(
        document_id="doc_2",
        source_input_id="in_2",
        text="Good morning",
        pages=(PageData(page_number=1, text="Good morning", spans=(span2,)),),
    )

    req = Request(
        request_id="r_batch",
        requirement="translation",
        inputs=(InputRef("in_1", Path("1.txt"), "1.txt", 10),),
    )
    ctx = ExecutionContext("run_b", "r_batch", "tr_b", "sp_b")
    prior = Result(data=(doc1, doc2))

    res = cap.execute(request=req, context=ctx, prior_result=prior)

    # Batch output returned as tuple of CanonicalDocument
    assert isinstance(res.data, tuple)
    assert len(res.data) == 2
    assert res.data[0].text == "Translated(Hello world)"
    assert res.data[1].text == "Translated(Good morning)"

    # Spans preserved
    assert len(res.data[0].pages[0].spans) == 1
    assert res.data[0].pages[0].spans[0].bounding_box == (10.0, 20.0, 30.0, 40.0)
    assert len(res.data[1].pages[0].spans) == 1
    assert res.data[1].pages[0].spans[0].bounding_box == (50.0, 60.0, 70.0, 80.0)

    # Artifacts created for both documents
    assert len(res.artifact_payloads) == 4


def test_translation_engine_error_does_not_leak_paths(tmp_path: Path) -> None:
    """Verify missing model assets error message does not leak local filesystem paths."""
    from sarathi.shakti.translation.models import TranslationDirection

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text('{"models": {"hi-en": {"path": "hi-en"}}}', encoding="utf-8")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    model_dir = models_dir / "hi-en"
    model_dir.mkdir()
    # spm.model is intentionally missing

    engine = CTranslate2TranslationEngine(data_root=tmp_path)
    backend = engine._ensure_backend()
    with pytest.raises(DoshError) as exc_info:
        backend.translate_sentences(["नमस्ते"], TranslationDirection.HI_TO_EN)
    err_msg = exc_info.value.message
    assert str(tmp_path) not in err_msg
    assert "Model assets for translation direction 'hi-en' are missing or incomplete." == err_msg


def test_legacy_to_legacy_preserves_detected_profile_decoding() -> None:
    """Verify legacy-to-legacy font conversion decodes source legacy before encoding to target legacy."""
    cap = FontConversionCapability()
    # Sample text in DevLys
    doc = CanonicalDocument(
        document_id="doc_devlys",
        source_input_id="in_devlys",
        text="LVsV cSad vksj Hkkjr ljdkj",
    )
    req = Request(
        request_id="r_l2l",
        requirement="font_conversion",
        inputs=(InputRef("in_devlys", Path("devlys.txt"), "devlys.txt", 20),),
        metadata=MappingProxyType({"font": "DevLys 010"}),
        custom_options=MappingProxyType({"font_mode": "to_krutidev"}),
    )
    ctx = ExecutionContext("run_l2l", "r_l2l", "tr_l2l", "sp_l2l")
    prior = Result(data=doc)

    res = cap.execute(request=req, context=ctx, prior_result=prior)
    assert isinstance(res.data, CanonicalDocument)
    # The output should have converted properly through Unicode to KrutiDev
    assert res.data.text != ""
    # Provenance records the detected source profile and target evidence
    assert res.provenance[-1].evidence["profile_id"] == "devlys010"
