"""Unit and integration tests for NE-OCR selective Devanagari fallback adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import ExecutionProfile
from sarathi.shakti.ocr.engine import NEOCRFallbackAdapter, RapidOCREngine


@pytest.fixture
def sample_vocab_path(tmp_path: Path) -> Path:
    vocab_file = tmp_path / "ne_ocr_vocab.json"
    data = {
        "vocab": [
            "<blank>",
            "0",
            "1",
            "a",
            "b",
            "र",
            "ा",
            "ज",
            "स",
            "्",
            "थ",
            "न",
            "<eos>",
        ]
    }
    vocab_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return vocab_file


class DummyNEOCR(NEOCRFallbackAdapter):
    """Test double for NEOCRFallbackAdapter returning configurable output."""

    def __init__(
        self,
        available: bool = True,
        return_tuple: tuple[str, float | None] | None = ("राजस्थान", 0.95),
    ) -> None:
        super().__init__(model_path=None, vocab_path=None)
        self._available = available
        self._return_tuple = return_tuple
        self.invoked_crops: list[Any] = []

    def is_available(self) -> bool:
        return self._available

    def recognize_crop(self, crop_image: Any) -> tuple[str, float | None] | None:
        self.invoked_crops.append(crop_image)
        if not self._available:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="NE-OCR fallback engine is not available.",
            )
        return self._return_tuple



def test_ne_ocr_discovery_and_availability(tmp_path: Path, sample_vocab_path: Path) -> None:
    # 1. Missing model and vocab
    adapter_empty = NEOCRFallbackAdapter(data_root=tmp_path)
    assert not adapter_empty.is_available()

    # 2. Only vocab present
    adapter_vocab_only = NEOCRFallbackAdapter(vocab_path=sample_vocab_path, data_root=tmp_path)
    assert not adapter_vocab_only.is_available()

    # 3. Model and vocab both present
    dummy_model = tmp_path / "ne_ocr.onnx"
    dummy_model.write_bytes(b"dummy onnx bytes")
    adapter_ready = NEOCRFallbackAdapter(model_path=dummy_model, vocab_path=sample_vocab_path)
    assert adapter_ready.is_available()


def test_ne_ocr_crop_preprocessing() -> None:
    adapter = NEOCRFallbackAdapter()

    # Create test RGB image
    img = Image.new("RGB", (200, 60), color=(128, 64, 32))
    tensor = adapter.preprocess_crop(img)

    assert isinstance(tensor, np.ndarray)
    assert tensor.shape == (1, 3, 32, 128)
    assert tensor.dtype == np.float32
    assert tensor.min() >= 0.0
    assert tensor.max() <= 1.0


def test_ne_ocr_decoding_predictions(sample_vocab_path: Path) -> None:
    adapter = NEOCRFallbackAdapter(vocab_path=sample_vocab_path)
    vocab = adapter._load_vocab()

    # Create synthetic logits for 'राज'
    # Tokens: 5 ('र'), 6 ('ा'), 7 ('ज'), 12 ('<eos>')
    target_tokens = [5, 6, 7, 12]
    num_classes = len(vocab)
    seq_len = len(target_tokens)
    logits = np.zeros((1, seq_len, num_classes), dtype=np.float32)

    for step_idx, tok_id in enumerate(target_tokens):
        logits[0, step_idx, tok_id] = 10.0  # High logit for target class

    text, conf = adapter.decode_predictions(logits, vocab)
    assert text == "राज"
    assert conf is not None
    assert conf > 0.9


def test_ne_ocr_vitstr_vocab_alignment(tmp_path: Path) -> None:
    """DocTR ViTSTR vocab where <blank> is at 0 must drop <blank> and append <eos>."""
    raw_vocab_file = tmp_path / "raw_vitstr_vocab.json"
    data = {"vocab": ["<blank>", "क", "ख", "ग"]}
    raw_vocab_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    adapter = NEOCRFallbackAdapter(vocab_path=raw_vocab_file)
    vocab = adapter._load_vocab()
    assert vocab == ["क", "ख", "ग", "<eos>"]


def test_ne_ocr_unavailability_raises_dosherror() -> None:
    adapter = NEOCRFallbackAdapter(model_path=Path("nonexistent.onnx"))
    with pytest.raises(DoshError) as exc_info:
        adapter.recognize_crop(Image.new("RGB", (50, 20)))
    assert exc_info.value.code == FailureCode.DEPENDENCY_UNAVAILABLE


class DummyOutput:
    def __init__(self, txts: list[str], boxes: list[Any], scores: list[float]) -> None:
        self.txts = txts
        self.boxes = boxes
        self.scores = scores


def test_rapidocr_engine_routes_devanagari_to_ne_ocr() -> None:
    """Accurate OCR must route weak Devanagari spans to NE-OCR and record truthful provenance."""
    mock_ne_ocr = DummyNEOCR(available=True, return_tuple=("राजस्थान सरकार", 0.94))

    engine = RapidOCREngine(
        ne_ocr_adapter=mock_ne_ocr,
        default_lang="hi",
    )

    engine._engine = lambda _arr: DummyOutput(
        txts=["राजस्धान सरकार"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.52],  # Low confidence (< 0.65)
    )

    img = Image.new("RGB", (200, 100), color="white")
    page_data, provenance, page_conf, warnings = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-test-neocr",
        profile=ExecutionProfile.ACCURATE,
    )

    # Verify NE-OCR was invoked
    assert len(mock_ne_ocr.invoked_crops) == 1

    # Verify span text and metadata
    assert len(page_data.spans) == 1
    span = page_data.spans[0]
    assert span.text == "राजस्थान सरकार"
    assert span.confidence == 0.94
    assert span.metadata["fallback_applied"] is True
    assert span.metadata["fallback_engine"] == "ne_ocr"
    assert span.metadata["original_confidence"] == 0.52
    assert span.metadata["replacement_confidence"] == 0.94

    # Verify provenance evidence
    assert provenance.evidence["fallback_applied"] is True
    assert provenance.evidence["fallback_engine"] == "ne_ocr"
    assert provenance.evidence["fallback_improved_count"] == 1


def test_instant_profile_never_invokes_ne_ocr() -> None:
    """Instant profile must never invoke NE-OCR fallback even for weak spans."""
    mock_ne_ocr = DummyNEOCR(available=True, return_tuple=("राजस्थान सरकार", 0.94))

    engine = RapidOCREngine(
        ne_ocr_adapter=mock_ne_ocr,
        default_lang="hi",
    )

    engine._engine = lambda _arr: DummyOutput(
        txts=["राजस्धान सरकार"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.50],
    )

    img = Image.new("RGB", (200, 100), color="white")
    page_data, provenance, _, _ = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-instant",
        profile=ExecutionProfile.INSTANT,
    )

    # Zero fallback calls in INSTANT profile
    assert len(mock_ne_ocr.invoked_crops) == 0
    assert page_data.spans[0].text == "राजस्धान सरकार"
    assert page_data.spans[0].confidence == 0.50
    assert "fallback_applied" not in provenance.evidence


def test_english_numeric_spans_bypass_ne_ocr_and_retain_rapidocr_text() -> None:
    """Low-confidence English/numeric text without Devanagari should bypass NE-OCR and retain RapidOCR."""
    mock_ne_ocr = DummyNEOCR(available=True, return_tuple=("NE_RESULT", 0.95))

    engine = RapidOCREngine(
        ne_ocr_adapter=mock_ne_ocr,
        default_lang="en",
    )

    engine._engine = lambda _arr: DummyOutput(
        txts=["1NV-2026-99"],  # English alphanumeric with OCR error
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.55],
    )

    img = Image.new("RGB", (200, 100), color="white")
    page_data, provenance, _, _ = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-eng-fallback",
        profile=ExecutionProfile.ACCURATE,
    )

    # NE-OCR is bypassed for non-Devanagari, and no external subprocess is executed
    assert len(mock_ne_ocr.invoked_crops) == 0
    assert page_data.spans[0].text == "1NV-2026-99"
    assert page_data.spans[0].confidence == 0.55
    assert "fallback_applied" not in provenance.evidence


@pytest.mark.real_model
def test_ne_ocr_concurrent_worker_inference() -> None:
    """NE-OCR must support concurrent multi-worker recognize_crop calls without collisions."""
    import concurrent.futures

    adapter = NEOCRFallbackAdapter()
    if not adapter.is_available():
        pytest.skip("NE-OCR model weights not available on host.")

    img = Image.new("RGB", (200, 50), color="white")
    results: list[tuple[str, float | None] | None] = []

    def _call_crop(idx: int) -> tuple[str, float | None] | None:
        return adapter.recognize_crop(img)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_call_crop, i) for i in range(16)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    assert len(results) == 16
    # No exception raised during concurrent execution
