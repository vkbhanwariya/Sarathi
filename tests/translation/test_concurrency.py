"""Tests for Translation capability multi-document concurrency and semantic equivalence."""

import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    CanonicalDocument,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    PluginServices,
    Request,
    Result,
    TableData,
)
from sarathi.shakti.translation.capability import TranslationCapability
from sarathi.shakti.translation.models import TranslationDirection
from sarathi.shakti.translation.provider import TranslationProvider
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class ThreadTrackingBackend:
    """Mock backend that tracks in-flight concurrency across thread execution."""

    def __init__(self, delay_sec: float = 0.02, wait_for_concurrency: int = 1) -> None:
        self.delay_sec = delay_sec
        self.wait_for_concurrency = wait_for_concurrency
        self.current_active = 0
        self.max_active_seen = 0
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.call_order: list[str] = []

    def translate_sentences(
        self,
        sentences: Sequence[str],
        direction: TranslationDirection,
        execution_binding: Any = None,
        engine: str = "indictrans2",
        **kwargs: Any,
    ) -> list[str]:
        with self.cond:
            self.current_active += 1
            if self.current_active > self.max_active_seen:
                self.max_active_seen = self.current_active
            self.call_order.append(sentences[0] if sentences else "")
            self.cond.notify_all()
            if self.wait_for_concurrency > 1 and self.max_active_seen < self.wait_for_concurrency:
                self.cond.wait_for(
                    lambda: self.max_active_seen >= self.wait_for_concurrency,
                    timeout=2.0,
                )

        time.sleep(self.delay_sec)

        with self.lock:
            self.current_active -= 1

        return [f"[EN: {s}]" for s in sentences]


def _build_test_docs(count: int = 4) -> list[CanonicalDocument]:
    docs = []
    sample_texts = [
        "भारतीय रिजर्व बैंक ने मौद्रिक नीति 15/08/2024 को जारी की।",
        "यह एक दूसरा दस्तावेज है जिसमें ₹50,000 की राशि का उल्लेख है।",
        "कंपनी का खाता संख्या AC-987654321 सक्रिय है।",
        "अंतिम दस्तावेज में सभी नियम एवं शर्तें स्पष्ट रूप से दी गई हैं।",
    ]
    for i in range(count):
        text = sample_texts[i % len(sample_texts)]
        table = TableData(
            name="विवरण",
            headers=("शीर्षक", "मान"),
            rows=(("दस्तावेज क्रमांक", f"DOC-{i + 1}"), ("दिनांक", "01/01/2025")),
        )
        page = PageData(page_number=1, text=text, tables=[table])
        doc = CanonicalDocument(
            document_id=f"doc-{i + 1}",
            source_input_id=f"in-{i + 1}",
            detected_type="native_document",
            text=text,
            pages=[page],
            tables=[table],
        )
        docs.append(doc)
    return docs


def test_translation_provider_injects_yantra(tmp_path: Path) -> None:
    inv = DeviceInventory([DeviceInfo("cpu-0", DeviceType.CPU, capacity=4)])
    yantra = Yantra(inv)
    services = PluginServices(
        yantra=yantra,
        darpana=None,
        kavacha=None,
        settings=None,
        data_root=tmp_path,
    )

    prov = TranslationProvider()
    caps = prov.create_capabilities(services)

    assert "translation" in caps
    trans_cap = caps["translation"]
    assert isinstance(trans_cap, TranslationCapability)
    assert trans_cap._yantra is yantra


def test_translation_concurrent_and_sequential_semantic_equivalence(test_backend: Any) -> None:
    """Verify that parallel multi-document translation yields semantically and structurally identical results to sequential execution."""
    docs = _build_test_docs(count=4)
    prior_result = Result(data=tuple(docs), confidence=None)

    inv = DeviceInventory([DeviceInfo("cpu-0", DeviceType.CPU, capacity=4)])
    yantra = Yantra(inv)

    binding = ExecutionBinding(
        device_id="cpu-0",
        device_type=DeviceType.CPU,
        backend="cpu",
        backend_device_id="CPU",
        approved_concurrency=4,
    )
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1", execution_binding=binding)
    req = Request(
        request_id="req-1",
        requirement="translation",
        inputs=tuple(
            InputRef(
                input_id=f"in-{i + 1}",
                source_path=Path(f"doc_{i + 1}.txt"),
                display_name=f"doc_{i + 1}.txt",
                size_bytes=100,
            )
            for i in range(4)
        ),
        profile=ExecutionProfile.ACCURATE,
        metadata={"direction": "hi-en"},
    )

    cap_seq = TranslationCapability(backend=test_backend, yantra=None)
    cap_conc = TranslationCapability(backend=test_backend, yantra=yantra)

    res_seq = cap_seq.execute(request=req, context=ctx, prior_result=prior_result)
    res_conc = cap_conc.execute(request=req, context=ctx, prior_result=prior_result)

    # 1. Compare data documents
    assert isinstance(res_seq.data, tuple)
    assert isinstance(res_conc.data, tuple)
    assert len(res_seq.data) == len(res_conc.data) == 4

    for d_seq, d_conc in zip(res_seq.data, res_conc.data):
        assert d_seq.document_id == d_conc.document_id
        assert d_seq.source_input_id == d_conc.source_input_id
        assert d_seq.detected_type == d_conc.detected_type
        assert d_seq.text == d_conc.text
        assert len(d_seq.pages) == len(d_conc.pages)
        for p_seq, p_conc in zip(d_seq.pages, d_conc.pages):
            assert p_seq.page_number == p_conc.page_number
            assert p_seq.text == p_conc.text
            assert len(p_seq.tables) == len(p_conc.tables)
            for t_seq, t_conc in zip(p_seq.tables, p_conc.tables):
                assert t_seq.headers == t_conc.headers
                assert t_seq.rows == t_conc.rows

    # 2. Compare artifact payloads
    assert len(res_seq.artifact_payloads) == len(res_conc.artifact_payloads) == 8
    for p_seq, p_conc in zip(res_seq.artifact_payloads, res_conc.artifact_payloads):
        assert p_seq.intent.name == p_conc.intent.name
        assert p_seq.intent.role == p_conc.intent.role
        assert p_seq.intent.media_type == p_conc.intent.media_type
        if p_seq.intent.media_type == "text/plain":
            assert p_seq.content == p_conc.content

    # 3. Compare provenance
    assert len(res_seq.provenance) == len(res_conc.provenance)
    for pr_seq, pr_conc in zip(res_seq.provenance, res_conc.provenance):
        assert pr_seq.source_input_id == pr_conc.source_input_id
        assert pr_seq.capability_id == pr_conc.capability_id
        assert pr_seq.evidence == pr_conc.evidence


def test_translation_concurrency_bounded_by_approved_concurrency() -> None:
    """Verify that multi-document translation concurrency honors approved_concurrency bounds and preserves exact order."""
    tracking_backend = ThreadTrackingBackend(delay_sec=0.02, wait_for_concurrency=2)

    inv = DeviceInventory([DeviceInfo("cpu-0", DeviceType.CPU, capacity=8)])
    yantra = Yantra(inv)

    docs = _build_test_docs(count=6)
    prior_result = Result(data=tuple(docs), confidence=None)

    # Limit approved_concurrency to 2
    binding = ExecutionBinding(
        device_id="cpu-0",
        device_type=DeviceType.CPU,
        backend="cpu",
        backend_device_id="CPU",
        approved_concurrency=2,
    )
    ctx = ExecutionContext("run-2", "req-2", "t2", "s2", execution_binding=binding)
    req = Request(
        request_id="req-2",
        requirement="translation",
        inputs=tuple(
            InputRef(
                input_id=f"in-{i + 1}",
                source_path=Path(f"doc_{i + 1}.txt"),
                display_name=f"doc_{i + 1}.txt",
                size_bytes=100,
            )
            for i in range(6)
        ),
        profile=ExecutionProfile.ACCURATE,
        metadata={"direction": "hi-en"},
    )

    cap = TranslationCapability(backend=tracking_backend, yantra=yantra)
    result = cap.execute(request=req, context=ctx, prior_result=prior_result)

    assert isinstance(result.data, tuple)
    assert len(result.data) == 6

    # Verify result document order matches original document input order
    for idx, d in enumerate(result.data):
        assert d.document_id == f"doc-{idx + 1}"
        assert d.source_input_id == f"in-{idx + 1}"

    # Invariant: Concurrency must be > 1 (parallelism active) and <= 2 (approved_concurrency bound)
    assert tracking_backend.max_active_seen > 1, f"Expected concurrency > 1, got {tracking_backend.max_active_seen}"
    assert tracking_backend.max_active_seen <= 2, (
        f"Concurrency exceeded approved_concurrency (2): {tracking_backend.max_active_seen}"
    )


def test_translation_concurrent_cancellation_honored() -> None:
    """Verify cooperative cancellation stops multi-document concurrent translation."""
    tracking_backend = ThreadTrackingBackend(delay_sec=0.05)

    inv = DeviceInventory([DeviceInfo("cpu-0", DeviceType.CPU, capacity=4)])
    yantra = Yantra(inv)

    docs = _build_test_docs(count=4)
    prior_result = Result(data=tuple(docs), confidence=None)

    token = CancellationToken()
    # Pre-cancel token
    token.cancel()

    binding = ExecutionBinding(
        device_id="cpu-0",
        device_type=DeviceType.CPU,
        backend="cpu",
        backend_device_id="CPU",
        approved_concurrency=4,
    )
    ctx = ExecutionContext("run-3", "req-3", "t3", "s3", execution_binding=binding, cancellation_token=token)
    req = Request(
        request_id="req-3",
        requirement="translation",
        inputs=tuple(
            InputRef(
                input_id=f"in-{i + 1}",
                source_path=Path(f"doc_{i + 1}.txt"),
                display_name=f"doc_{i + 1}.txt",
                size_bytes=100,
            )
            for i in range(4)
        ),
        profile=ExecutionProfile.ACCURATE,
        metadata={"direction": "hi-en"},
    )

    cap = TranslationCapability(backend=tracking_backend, yantra=yantra)
    with pytest.raises(DoshError) as exc_info:
        cap.execute(request=req, context=ctx, prior_result=prior_result)

    assert exc_info.value.code == FailureCode.OPERATION_CANCELLED


@pytest.mark.real_model
def test_ctranslate2_concurrency_cache_key_reuses_model_instance() -> None:
    """Verify backend translator cache reuses model instances across differing concurrency profiles to prevent duplicate allocations."""
    from sarathi.sankalpa import DeviceType, ExecutionBinding
    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine

    engine = CTranslate2TranslationEngine()
    try:
        backend = engine._ensure_backend()
    except DoshError as exc:
        if exc.code == FailureCode.DEPENDENCY_UNAVAILABLE:
            pytest.skip("CTranslate2 neural model weights not provisioned.")
        raise

    b1 = ExecutionBinding(
        device_id="cpu-0",
        device_type=DeviceType.CPU,
        backend="cpu",
        backend_device_id="CPU",
        approved_concurrency=1,
    )
    b4 = ExecutionBinding(
        device_id="cpu-0",
        device_type=DeviceType.CPU,
        backend="cpu",
        backend_device_id="CPU",
        approved_concurrency=4,
    )

    # Run single-stream translation
    backend.translate_sentences(["Hello world"], TranslationDirection.EN_TO_HI, execution_binding=b1)
    # Run multi-stream translation
    backend.translate_sentences(["Hello world"], TranslationDirection.EN_TO_HI, execution_binding=b4)

    # Invariant in Vedas/Capabilities.md: Model instances are cached strictly by
    # (engine, model_path, device, device_index) to prevent duplicate allocations across differing concurrency configurations.
    keys = list(backend._translators.keys())
    assert len(keys) == 1, f"Expected 1 shared translator instance, got {len(keys)}: {keys}"
    assert "indictrans2" in keys[0]
    assert "en-hi" in keys[0]
    assert "cpu:0" in keys[0]


@pytest.mark.real_model
def test_ctranslate2_does_not_mutate_global_openmp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that CTranslate2 native backend does not pollute global os.environ with OpenMP settings."""
    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine

    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)

    engine = CTranslate2TranslationEngine()
    try:
        backend = engine._ensure_backend()
    except DoshError as exc:
        if exc.code == FailureCode.DEPENDENCY_UNAVAILABLE:
            pytest.skip("CTranslate2 neural model weights not provisioned.")
        raise
    backend.translate_sentences(["Testing thread isolation"], TranslationDirection.EN_TO_HI)

    import os

    assert "OMP_NUM_THREADS" not in os.environ, "Translation must not pollute global OMP_NUM_THREADS"
    assert "MKL_NUM_THREADS" not in os.environ, "Translation must not pollute global MKL_NUM_THREADS"


def test_translate_batch_deduplicates_identical_sentences() -> None:
    """Verify translate_batch deduplicates identical sentences across multiple input texts before calling backend."""
    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine

    captured_batches: list[list[str]] = []

    class MockBackend:
        def translate_sentences(self, sentences, direction, execution_binding=None, engine="indictrans2", **kwargs):
            captured_batches.append(list(sentences))
            # Echo translation uppercase for deterministic testing
            return [s.upper() for s in sentences]

    engine = CTranslate2TranslationEngine(backend=MockBackend())

    # 3 distinct input texts that share identical sentences
    texts = [
        "Notice is issued to the respondents. The interim protection granted earlier shall continue.",
        "List on 24.05.2024. The interim protection granted earlier shall continue.",
        "Notice is issued to the respondents. List on 24.05.2024.",
    ]

    results = engine.translate_batch(texts, direction=TranslationDirection.EN_TO_HI)

    assert len(results) == 3
    # Verify that backend was invoked with deduplicated sentences
    assert len(captured_batches) == 1
    backend_sent_list = captured_batches[0]

    # Total sentences across all 3 texts is 2 + 2 + 2 = 6 sentences.
    # 'Notice is issued...' and 'The interim protection...' are deduplicated, reducing 6 to 4!
    assert len(backend_sent_list) == 4

    # All 3 texts must receive their full, correctly translated bodies in original order
    assert "THE INTERIM PROTECTION GRANTED EARLIER SHALL CONTINUE" in results[0].translated_text
    assert "IS ISSUED TO THE RESPONDENTS" in results[0].translated_text
    assert "सूचना" in results[0].translated_text

    assert "THE INTERIM PROTECTION GRANTED EARLIER SHALL CONTINUE" in results[1].translated_text
    assert "24.05.2024" in results[1].translated_text  # protected date restored

    assert "IS ISSUED TO THE RESPONDENTS" in results[2].translated_text
    assert "सूचना" in results[2].translated_text
    assert "24.05.2024" in results[2].translated_text


def test_translate_token_bounded_chunking_and_input_truncation_warning(monkeypatch: Any, tmp_path: Path) -> None:
    """Verify sentences exceeding token limit are chunked and input truncation is detected."""
    from types import SimpleNamespace

    from sarathi.shakti.translation.engine import (
        CTranslate2NativeBackend,
        _chunk_long_sentence,
    )

    class FakeSPM:
        def encode_as_pieces(self, text: str) -> list[str]:
            # Each word is 10 tokens
            return [f"tok_{i}" for i in range(len(text.split()) * 10)]

        def decode_pieces(self, pieces: list[str]) -> str:
            return " ".join(pieces)

    # 1. Test _chunk_long_sentence on a 40-word sentence with no punctuation (400 tokens > 256 limit)
    spm = FakeSPM()
    long_sentence = "word " * 40
    chunks = _chunk_long_sentence(long_sentence.strip(), spm, max_tokens=256)
    assert len(chunks) >= 2
    # Verify every chunk is <= 256 tokens
    for c_text, _ in chunks:
        assert len(spm.encode_as_pieces(c_text)) <= 256

    # 2. Test translate_sentences captures max_input_length=1024 and flags input truncation
    captured_kwargs: dict[str, Any] = {}

    class FakeTranslator:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def translate_batch(self, tokenized: Any, **kwargs: Any) -> Any:
            nonlocal captured_kwargs
            captured_kwargs.update(kwargs)
            return [SimpleNamespace(hypotheses=[["out_tok"]])] * len(tokenized)

    import ctranslate2

    monkeypatch.setattr(ctranslate2, "Translator", FakeTranslator)

    model_dir = tmp_path / "models" / "indictrans2" / "hi-en"
    model_dir.mkdir(parents=True)
    (model_dir / "spm.model").write_bytes(b"dummy")
    (model_dir / "model.bin").write_bytes(b"dummy")

    backend = CTranslate2NativeBackend(root=tmp_path, manifest={})
    backend._spms[f"src:{(model_dir / 'spm.model').resolve()}"] = FakeSPM()
    backend._spms[f"tgt:{(model_dir / 'spm.model').resolve()}"] = FakeSPM()

    # Create a giant sentence that exceeds 1024 tokens (110 words * 10 = 1100 tokens)
    giant_piece = "giant " * 110
    # Monkeypatch _chunk_long_sentence to return the giant piece directly to trigger piece_input_truncation
    monkeypatch.setattr(
        "sarathi.shakti.translation.engine._chunk_long_sentence",
        lambda s, spm, max_tok: [(s, "")],
    )

    res = backend.translate_sentences([giant_piece], direction=TranslationDirection.HI_TO_EN)
    assert captured_kwargs.get("max_input_length") == 1024
    assert res.input_truncation_flags == (True,)
