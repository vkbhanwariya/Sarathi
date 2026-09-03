"""Tests verifying lossless Smriti L1/L2 round-trip serialization and capability warning imports."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
    TableData,
    TextSpan,
    WarningRecord,
)
from sarathi.smriti.key import CacheKey
from sarathi.smriti.serialization import deserialize_result, serialize_result
from sarathi.smriti.store import SmritiCache


def test_page_spans_serialization_round_trip() -> None:
    """Test that PageData.spans with bounding boxes and confidence are preserved losslessly."""
    span1 = TextSpan(
        text="Sample text",
        confidence=0.95,
        bounding_box=(10.0, 20.0, 100.0, 200.0),
        metadata=MappingProxyType({"font": "Arial"}),
    )
    span2 = TextSpan(
        text="Second span",
        confidence=0.88,
        bounding_box=(30.0, 40.0, 50.0, 60.0),
    )
    page = PageData(
        page_number=1,
        text="Sample text Second span",
        spans=(span1, span2),
    )
    doc = CanonicalDocument(
        document_id="doc_123",
        source_input_id="in_123",
        text="Sample text Second span",
        pages=(page,),
    )
    res = Result(data=doc)

    serialized = serialize_result(res)
    deserialized = deserialize_result(serialized)

    assert isinstance(deserialized.data, CanonicalDocument)
    assert len(deserialized.data.pages) == 1
    deser_page = deserialized.data.pages[0]
    assert len(deser_page.spans) == 2

    assert deser_page.spans[0].text == "Sample text"
    assert deser_page.spans[0].confidence == 0.95
    assert deser_page.spans[0].bounding_box == (10, 20, 100, 200)
    assert deser_page.spans[0].metadata.get("font") == "Arial"

    assert deser_page.spans[1].text == "Second span"
    assert deser_page.spans[1].confidence == 0.88
    assert deser_page.spans[1].bounding_box == (30, 40, 50, 60)


def test_artifact_relative_path_serialization_round_trip() -> None:
    """Test that ArtifactIntent.relative_path is preserved losslessly through serialization."""
    doc = CanonicalDocument(
        document_id="doc_test",
        source_input_id="in_test",
        text="Content",
    )
    intent = ArtifactIntent(
        name="output.docx",
        role="final_report",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        relative_path=Path("subfolder/nested/output.docx"),
    )
    payload = ArtifactPayload(intent=intent, content=b"fake_docx_content")
    res = Result(data=doc, artifact_payloads=(payload,))

    serialized = serialize_result(res)
    deserialized = deserialize_result(serialized)

    assert len(deserialized.artifact_payloads) == 1
    deser_intent = deserialized.artifact_payloads[0].intent
    assert deser_intent.name == "output.docx"
    assert deser_intent.role == "final_report"
    assert deser_intent.relative_path == Path("subfolder/nested/output.docx")
    assert deserialized.artifact_payloads[0].content == b"fake_docx_content"


def test_smriti_l1_and_l2_cache_equivalence(tmp_path: Path) -> None:
    """Test that retrieving from L1 memory vs L2 SQLite produces identical canonical state."""
    cache = SmritiCache(cache_dir=tmp_path)

    span = TextSpan(text="Heading", confidence=0.99, bounding_box=(0.0, 0.0, 50.0, 10.0))
    intent = ArtifactIntent(
        name="report.pdf",
        role="export",
        media_type="application/pdf",
        relative_path=Path("exports/report.pdf"),
    )
    payload = ArtifactPayload(intent=intent, content=b"%PDF-1.4")
    doc = CanonicalDocument(
        document_id="d1",
        source_input_id="i1",
        text="Heading",
        pages=(PageData(page_number=1, text="Heading", spans=(span,)),),
    )
    original_result = Result(data=doc, artifact_payloads=(payload,))

    key = CacheKey(key_hash="test_key_equivalence_123", capability_id="ocr", fingerprint="fp123", profile="instant")
    cache.put(key, original_result)

    # 1. Retrieve from L1
    l1_hit = cache.get(key)
    assert l1_hit is not None
    assert l1_hit.data.pages[0].spans[0].text == "Heading"
    assert l1_hit.artifact_payloads[0].intent.relative_path == Path("exports/report.pdf")

    # 2. Invalidate L1 memory only to force L2 SQLite fetch
    cache._l1.invalidate(key=key)
    assert cache._l1.get(key) is None

    # 3. Retrieve from L2 SQLite
    l2_hit = cache.get(key)
    assert l2_hit is not None
    assert isinstance(l2_hit.data, CanonicalDocument)
    assert len(l2_hit.data.pages[0].spans) == 1
    assert l2_hit.data.pages[0].spans[0].text == "Heading"
    assert l2_hit.data.pages[0].spans[0].bounding_box == (0.0, 0.0, 50.0, 10.0)
    assert l2_hit.artifact_payloads[0].intent.relative_path == Path("exports/report.pdf")


def test_translation_legacy_font_handoff_warning() -> None:
    """Test that TranslationCapability cleanly returns WarningRecord without NameError."""
    from sarathi.shakti.translation.capability import TranslationCapability

    cap = TranslationCapability()
    # Kruti dev signature digraphs
    legacy_doc = CanonicalDocument(
        document_id="doc_legacy",
        source_input_id="in_legacy",
        text="dk;kZy; vkns'k vuqHkkx",
    )
    in_ref = InputRef(
        input_id="in_legacy",
        source_path=Path("legacy.txt"),
        display_name="legacy.txt",
        size_bytes=100,
    )
    req = Request(request_id="req_t1", requirement="translate", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run_t1", request_id="req_t1", trace_id="trace_t1", span_id="span_t1")

    prior = Result(data=legacy_doc)
    res = cap.execute(request=req, context=ctx, prior_result=prior)

    assert res.next_requirement == "font_conversion"
    assert res.resume_self is True
    assert len(res.warnings) == 1
    assert res.warnings[0].code == "LEGACY_FONT_DETECTED"


def test_ocr_empty_input_warning(tmp_path: Path) -> None:
    """Test that OCRCapability cleanly returns WarningRecord without NameError on empty input."""
    from sarathi.shakti.ocr.capability import OCRCapability

    empty_file = tmp_path / "empty.png"
    empty_file.write_bytes(b"")

    cap = OCRCapability(engine=None)
    in_ref = InputRef(
        input_id="in_ocr",
        source_path=empty_file,
        display_name="empty.png",
        size_bytes=0,
    )
    req = Request(request_id="req_ocr1", requirement="ocr", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run_ocr1", request_id="req_ocr1", trace_id="trace_ocr1", span_id="span_ocr1")

    res = cap.execute(request=req, context=ctx, prior_result=None)

    assert isinstance(res.data, CanonicalDocument)
    assert len(res.warnings) == 1
    assert res.warnings[0].code == "OCR_EMPTY_INPUT"
