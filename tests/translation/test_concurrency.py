"""Tests for Translation capability multi-document concurrency and semantic equivalence."""

import threading
import time
from pathlib import Path
from typing import Any, Sequence

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

    def __init__(self, delay_sec: float = 0.02) -> None:
        self.delay_sec = delay_sec
        self.current_active = 0
        self.max_active_seen = 0
        self.lock = threading.Lock()
        self.call_order: list[str] = []

    def translate_sentences(
        self,
        sentences: Sequence[str],
        direction: TranslationDirection,
        execution_binding: Any = None,
    ) -> list[str]:
        with self.lock:
            self.current_active += 1
            if self.current_active > self.max_active_seen:
                self.max_active_seen = self.current_active
            self.call_order.append(sentences[0] if sentences else "")

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
            InputRef(input_id=f"in-{i + 1}", source_path=Path(f"doc_{i + 1}.txt"), display_name=f"doc_{i + 1}.txt", size_bytes=100)
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
    tracking_backend = ThreadTrackingBackend(delay_sec=0.03)

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
            InputRef(input_id=f"in-{i + 1}", source_path=Path(f"doc_{i + 1}.txt"), display_name=f"doc_{i + 1}.txt", size_bytes=100)
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
    assert tracking_backend.max_active_seen <= 2, f"Concurrency exceeded approved_concurrency (2): {tracking_backend.max_active_seen}"


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
            InputRef(input_id=f"in-{i + 1}", source_path=Path(f"doc_{i + 1}.txt"), display_name=f"doc_{i + 1}.txt", size_bytes=100)
            for i in range(4)
        ),
        profile=ExecutionProfile.ACCURATE,
        metadata={"direction": "hi-en"},
    )

    cap = TranslationCapability(backend=tracking_backend, yantra=yantra)
    with pytest.raises(DoshError) as exc_info:
        cap.execute(request=req, context=ctx, prior_result=prior_result)

    assert exc_info.value.code == FailureCode.OPERATION_CANCELLED
