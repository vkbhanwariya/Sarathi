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


def test_translation_pipeline_with_deterministic_backend(
    tmp_path: Path, hindi_sample_file: Path, test_backend: Any
) -> None:
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
            **kwargs: Any,
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
        def translate_sentences(
            self,
            sentences: list[str],
            direction,
            execution_binding: Any = None,
            engine: str = "indictrans2",
            **kwargs: Any,
        ) -> list[str]:
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
        def translate_sentences(
            self, sentences: list[str], direction, execution_binding=None, engine: str = "indictrans2", **kwargs
        ) -> tuple[list[str], str]:
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


def test_translation_telemetry_never_emits_fabricated_confidence(tmp_path: Path, test_backend: Any) -> None:
    """Proves translation telemetry records confidence=None and measured duration."""
    darpana = Darpana(capacity=100)
    cap = TranslationCapability(darpana=darpana, backend=test_backend)

    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("भारतीय रिजर्व बैंक\n", encoding="utf-8")

    inp = InputRef(
        input_id="inp-tr-truth",
        source_path=sample_file,
        display_name="sample.txt",
        size_bytes=sample_file.stat().st_size,
    )
    req = Request(
        request_id="req-tr-truth",
        requirement="translation",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
        metadata={"direction": "hi-en"},
    )
    ctx = ExecutionContext("run-tr-truth", "req-tr-truth", "t-tr", "s-tr")
    doc = CanonicalDocument(
        document_id="doc-tr-truth",
        text="भारतीय रिजर्व बैंक ने नई मौद्रिक नीति की घोषणा की।",
        pages=(
            PageData(
                page_number=1,
                text="भारतीय रिजर्व बैंक ने नई मौद्रिक नीति की घोषणा की।",
            ),
        ),
    )
    prior = Result(data=doc)

    result = cap.execute(req, ctx, prior_result=prior)

    assert isinstance(result, Result)
    assert result.confidence is None

    # Check Pramana telemetry records
    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    assert len(pramana_recs) > 0
    for prec in pramana_recs:
        assert prec.confidence is None, f"Expected confidence=None but got {prec.confidence}"
        assert prec.attributes.get("min_confidence") is None
        assert prec.attributes.get("max_confidence") is None

    # Check Maruti worker execution duration
    maruti_recs = [r for r in darpana.maruti_records() if r.run_id == ctx.run_id and r.phase_name == "worker_execution"]
    assert len(maruti_recs) > 0
    for mrec in maruti_recs:
        assert isinstance(mrec.duration_ns, int)
        assert mrec.duration_ns >= 0


@pytest.mark.parametrize(
    ("direction", "src_text", "expected_fragment"),
    [
        (
            "hi-en",
            "भारतीय रिजर्व बैंक ने नई मौद्रिक नीति की घोषणा की।",
            "Reserve Bank of India",
        ),
        (
            "en-hi",
            "The applicant submitted the identity document on date 15/08/2026 for verification.",
            "आवेदक ने सत्यापन के लिए",
        ),
    ],
)
def test_bilingual_sentence_translation_directions(
    test_backend: Any, direction: str, src_text: str, expected_fragment: str
) -> None:
    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
    from sarathi.shakti.translation.models import TranslationDirection

    engine = CTranslate2TranslationEngine(backend=test_backend)
    dir_enum = TranslationDirection(direction)
    res = engine.translate(src_text, direction=dir_enum)
    assert expected_fragment in res.translated_text


def test_indictrans2_native_engine_missing_assets_fails_dependency_unavailable(tmp_path: Path) -> None:
    """IndicTrans2 native engine fails closed with DEPENDENCY_UNAVAILABLE when assets missing."""
    from sarathi.dosh import DoshError, FailureCode
    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
    from sarathi.shakti.translation.models import TranslationDirection

    empty_data_dir = tmp_path / "empty_indic"
    empty_data_dir.mkdir(parents=True, exist_ok=True)
    (empty_data_dir / "models").mkdir(parents=True, exist_ok=True)
    (empty_data_dir / "manifest.json").write_text('{"version": "1.0", "models": {"hi-en": {}}}', encoding="utf-8")
    native_engine = CTranslate2TranslationEngine(data_root=empty_data_dir)
    with pytest.raises(DoshError) as excinfo:
        native_engine.translate("परीक्षण", direction=TranslationDirection.HI_TO_EN, engine="indictrans2")
    assert excinfo.value.code == FailureCode.DEPENDENCY_UNAVAILABLE
    assert "Model assets for IndicTrans2 translation direction 'hi-en' are missing or incomplete." == excinfo.value.message


def test_translate_batch_multi_sentence_batching_and_ordering(test_backend: Any) -> None:
    """Verify CTranslate2TranslationEngine.translate_batch batches sentences and preserves ordering."""
    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
    from sarathi.shakti.translation.models import TranslationDirection

    engine = CTranslate2TranslationEngine(backend=test_backend)
    inputs = [
        "भारतीय रिजर्व बैंक",
        "",
        "   ",
        "खाता विवरण",
        "नमस्ते दुनिया",
    ]
    results = engine.translate_batch(inputs, direction=TranslationDirection.HI_TO_EN)
    assert len(results) == len(inputs)
    assert "Reserve Bank of India" in results[0].translated_text
    assert results[1].translated_text == ""
    assert results[2].translated_text == "   "
    assert len(results[3].translated_text) > 0
    assert len(results[4].translated_text) > 0
    assert results[0].protected_spans_count >= 0


def test_structural_placeholder_not_translated_and_markdown_table_exported(tmp_path: Path) -> None:
    """Verify {{TABLE:Table_1}} is not passed to machine translation and exports clean markdown in .txt."""
    from sarathi.sankalpa import TableData
    from sarathi.shakti.translation.models import Language, TranslationDirection, TranslationResult

    called_inputs: list[str] = []

    class CapturingTranslationEngine:
        def translate(
            self,
            text: str,
            direction: TranslationDirection,
            execution_binding: Any = None,
            **kwargs: Any,
        ) -> TranslationResult:
            called_inputs.append(text)
            return TranslationResult(
                translated_text=f"अनुवाद: {text}",
                source_language=Language.ENGLISH,
                target_language=Language.HINDI,
                direction=direction,
                protected_spans_count=0,
                metadata={},
            )

    cap = TranslationCapability()
    cap._engine = CapturingTranslationEngine()

    table = TableData(
        name="Table_1",
        headers=("Col1", "Col2"),
        rows=(("Data1", "Data2"), ("Data3", "Data4")),
    )
    doc = CanonicalDocument(
        document_id="doc-tbl-1",
        text="{{TABLE:Table_1}}",
        tables=(table,),
    )
    prior = Result(data=doc)
    ctx = ExecutionContext("run-tbl-1", "req-tbl-1", "t-1", "s-1")
    inp = InputRef(input_id="inp-tbl-1", source_path=tmp_path / "table.pdf", display_name="table.pdf", size_bytes=100)
    req = Request(request_id="req-tbl-1", requirement="translation", inputs=(inp,))

    result = cap.execute(req, ctx, prior_result=prior)

    # 1. Verify that {{TABLE:Table_1}} was NEVER sent to the translation engine
    assert "{{TABLE:Table_1}}" not in called_inputs

    # 2. Verify translated_doc.text keeps {{TABLE:Table_1}} anchor intact for DOCX builder
    assert isinstance(result.data, CanonicalDocument)
    assert result.data.text == "{{TABLE:Table_1}}"

    # 3. Verify Translated_Document.txt artifact payload contains formatted markdown table
    txt_payload = next(p for p in result.artifact_payloads if p.intent.name.endswith(".txt"))
    txt_content = txt_payload.content.decode("utf-8")
    assert "| अनुवाद: Col1 | अनुवाद: Col2 |" in txt_content
    assert "| --- | --- |" in txt_content
    assert "{{TABLE:Table_1}}" not in txt_content


def test_translation_capability_extracts_legal_context_and_populates_provenance(
    tmp_path: Path, test_backend: Any
) -> None:
    """Verify TranslationCapability extracts legal context and attaches it to document metadata and provenance."""
    darpana = Darpana(capacity=50)
    cap = TranslationCapability(darpana=darpana, backend=test_backend)

    legal_sample = """
    IN THE HIGH COURT OF DELHI AT NEW DELHI
    W.P.(C) 4567/2023
    CNR No. DLHC010045672023

    RAMESH CHANDRA ... PETITIONER
    VERSUS
    UNION OF INDIA & ORS. ... RESPONDENTS

    CORAM:
    HON'BLE MR. JUSTICE PRATEEK JALAN

    JUDGMENT
    1. The petitioner approached this Hon'ble Court under Article 226 of the Constitution of India and Section 482 of the CrPC.
    2. Reliance is placed on AIR 1980 SC 1789.
    """

    doc = CanonicalDocument(
        document_id="doc-legal-1",
        text=legal_sample,
        pages=(PageData(page_number=1, text=legal_sample),),
    )
    prior = Result(data=doc)
    ctx = ExecutionContext("run-leg-1", "req-leg-1", "t-leg", "s-leg")
    inp = InputRef(
        input_id="inp-leg-1",
        source_path=tmp_path / "order.txt",
        display_name="order.txt",
        size_bytes=len(legal_sample),
    )
    req = Request(
        request_id="req-leg-1",
        requirement="translation",
        inputs=(inp,),
        metadata={"direction": "en-hi"},
    )

    result = cap.execute(req, ctx, prior_result=prior)

    assert result.data is not None
    assert isinstance(result.data, CanonicalDocument)
    res_doc: CanonicalDocument = result.data

    # 1. Verify legal context attached to document metadata
    assert "legal_context" in res_doc.metadata
    leg_meta = res_doc.metadata["legal_context"]
    assert leg_meta["is_legal_document"] is True
    assert leg_meta["court_name"] == "High Court of Delhi"
    assert leg_meta["cnr_number"] == "DLHC010045672023"
    assert any("Article 226" in r for r in leg_meta["statutory_references"])
    assert any("AIR 1980 SC" in r for r in leg_meta["statutory_references"])

    # 2. Verify legal context attached to Darpana provenance
    assert len(result.provenance) > 0
    prov = result.provenance[-1]
    assert "legal_context" in prov.evidence
    prov_legal = prov.evidence["legal_context"]
    assert prov_legal["court_name"] == "High Court of Delhi"
    assert prov_legal["cnr_number"] == "DLHC010045672023"

    # 3. Verify statutory citations survive translation in output
    assert "DLHC010045672023" in res_doc.text
    assert "AIR 1980 SC 1789" in res_doc.text
