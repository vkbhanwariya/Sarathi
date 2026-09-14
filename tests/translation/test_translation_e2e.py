"""Integration test for Translation pipeline composition using deterministic test backend."""

from pathlib import Path
from typing import Any

import pytest

from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    Request,
    Result,
)
from sarathi.shakti.bank_statements import BankStatementCapability
from sarathi.shakti.darshana import DarshanaCapability
from sarathi.shakti.font_conversion import FontConversionCapability
from sarathi.shakti.native_extraction import NativeExtractionCapability
from sarathi.shakti.ocr import OCRCapability
from sarathi.shakti.translation.capability import TranslationCapability


@pytest.fixture
def hindi_sample_file(tmp_path: Path) -> Path:
    p = tmp_path / "hindi_sample.txt"
    content = "भारतीय रिजर्व बैंक ने नई मौद्रिक नीति की घोषणा की।\n"
    p.write_text(content, encoding="utf-8")
    return p


def test_translation_pipeline_with_deterministic_backend(tmp_path: Path, hindi_sample_file: Path, test_backend: Any) -> None:
    runtime_dir = tmp_path / "Runtime"
    output_dir = tmp_path / "Output"
    darpana = Darpana(capacity=200)

    # Injected test backend to verify pipeline without binary neural weights in git
    test_cap = TranslationCapability(darpana=darpana, backend=test_backend)

    agni = Agni(
        runtime_root=runtime_dir,
        output_root=output_dir,
        darpana=darpana,
        capabilities={
            "identify": DarshanaCapability(),
            "read_native": NativeExtractionCapability(),
            "ocr": OCRCapability(),
            "bank_statements": BankStatementCapability(darpana=darpana),
            "font_conversion": FontConversionCapability(darpana=darpana),
            "translation": test_cap,
        },
    )

    inp = InputRef(
        input_id="inp-tr-1",
        source_path=hindi_sample_file,
        display_name="hindi_sample.txt",
        size_bytes=hindi_sample_file.stat().st_size,
    )

    req = Request(
        request_id="req-tr-1",
        requirement="translation",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
        metadata={"direction": "hi-en"},
    )

    ctx = ExecutionContext("run-tr-1", "req-tr-1", "t-tr", "s-tr")

    # Execute through canonical pipeline (read_native -> translation)
    result = agni.execute(req, context=ctx)

    assert isinstance(result, Result)
    assert isinstance(result.data, CanonicalDocument)
    doc: CanonicalDocument = result.data

    # Verify translated text contents
    assert "Reserve Bank of India" in doc.text
    assert "announced the new monetary policy" in doc.text

    # Artifact confirmation
    assert len(result.artifacts) == 2
    art_names = {a.path.name for a in result.artifacts}
    assert "Translated_Document.txt" in art_names
    assert "Translated_Document.docx" in art_names
    for art in result.artifacts:
        assert art.path.exists()
        assert art.size_bytes > 0

    # Darpana telemetry confirmation
    maruti_recs = tuple(r for r in darpana.maruti_records() if r.run_id == ctx.run_id)
    assert len(maruti_recs) > 0


def test_translation_artifact_matches_canonical_doc_exactly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify Translation produces byte-for-byte identical text in doc.text and Translated_Document.txt artifact."""
    from sarathi.shakti.translation.models import Language, TranslationDirection, TranslationResult

    class MockTranslationEngine:
        def __init__(self) -> None:
            self.call_count = 0

        def translate(
            self,
            text: str,
            direction: TranslationDirection,
            execution_binding: Any = None,
        ) -> TranslationResult:
            self.call_count += 1
            return TranslationResult(
                translated_text=f"Translated: {text}",
                source_language=Language.HINDI,
                target_language=Language.ENGLISH,
                direction=direction,
                protected_spans_count=0,
                metadata={},
            )

    cap = TranslationCapability()
    cap._engine = MockTranslationEngine()  # inject mock engine

    doc = CanonicalDocument(
        document_id="doc-tr-1",
        text="यह एक परीक्षण दस्तावेज़ है।",
        pages=(
            PageData(
                page_number=1,
                text="यह एक परीक्षण दस्तावेज़ है।",
            ),
        ),
    )
    prior = Result(data=doc)
    ctx = ExecutionContext("run-1", "req-1", "t-1", "s-1")
    inp = InputRef(input_id="inp-1", source_path=tmp_path / "sample.txt", display_name="sample.txt", size_bytes=10)
    req = Request(request_id="req-1", requirement="translation", inputs=(inp,))

    result = cap.execute(req, ctx, prior_result=prior)

    assert result.data is not None
    assert isinstance(result.data, CanonicalDocument)
    canonical_text = result.data.text

    # Verify TXT artifact content
    txt_payload = next(p for p in result.artifact_payloads if p.intent.name.endswith(".txt"))
    assert txt_payload.content.decode("utf-8") == canonical_text

    # Verify that identical doc.text was not translated repeatedly (memoization worked)
    assert cap._engine.call_count == 1


def test_translation_batch_documents_and_spans() -> None:
    """Verify TranslationCapability processes tuple of CanonicalDocuments and preserves spans."""
    from sarathi.sankalpa import TextSpan
    from sarathi.shakti.translation.engine import TranslatorBackend

    class DummyMockTranslationBackend(TranslatorBackend):
        def translate_sentences(self, sentences: list[str], direction, execution_binding: Any = None) -> list[str]:
            return [f"Translated({s})" for s in sentences]

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


def test_translation_opus_mt_engine_forwarding_and_dependency_check(tmp_path: Path) -> None:
    """Verify TranslationCapability forwards engine='opus_mt' and engine fails closed if assets missing."""
    from sarathi.dosh import DoshError, FailureCode
    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine, TranslatorBackend
    from sarathi.shakti.translation.models import TranslationDirection

    received_engine: list[str] = []

    class MockCustomBackend(TranslatorBackend):
        def translate_sentences(self, sentences: list[str], direction, execution_binding=None, engine: str = "indictrans2", **kwargs) -> tuple[list[str], str]:
            received_engine.append(engine)
            return [f"OPUS:{s}" for s in sentences], "opus_model"

    mock_cap = TranslationCapability(backend=MockCustomBackend())
    doc = CanonicalDocument(document_id="d1", source_input_id="i1", text="परीक्षण")
    req = Request(
        request_id="r1",
        requirement="translation",
        inputs=(InputRef("i1", Path("1.txt"), "1.txt", 10),),
        custom_options={"engine": "opus_mt"},
    )
    ctx = ExecutionContext("r1", "req1", "t1", "s1")
    res = mock_cap.execute(req, ctx, prior_result=Result(data=doc))
    assert res.data is not None
    assert "opus_mt" in received_engine
    assert "OPUS:परीक्षण" in res.data.text

    # Native engine validation without downloaded opus assets fails closed with DEPENDENCY_UNAVAILABLE
    empty_data_dir = tmp_path / "empty_trans"
    empty_data_dir.mkdir(parents=True, exist_ok=True)
    (empty_data_dir / "models").mkdir(parents=True, exist_ok=True)
    (empty_data_dir / "manifest.json").write_text('{"version": "1.0"}', encoding="utf-8")
    native_engine = CTranslate2TranslationEngine(data_root=empty_data_dir)
    with pytest.raises(DoshError) as excinfo:
        native_engine.translate("परीक्षण", direction=TranslationDirection.HI_TO_EN, engine="opus_mt")
    assert excinfo.value.code == FailureCode.DEPENDENCY_UNAVAILABLE
    assert "OPUS-MT" in excinfo.value.message
