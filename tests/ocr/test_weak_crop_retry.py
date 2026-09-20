"""Unit and integration tests for same-engine weak-crop retry and runtime cleanliness.

Verifies:
1. Same-engine weak-crop retry behavior on low-confidence text spans.
2. Instant profile skips retry while Accurate/Layout Preserving profile retries weak crops.
3. Numeric and token preservation guard protects against digit corruption.
4. Complete absence of NE-OCR and ONNX Runtime in the production OCR subsystem.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from sarathi.sankalpa import ExecutionProfile
from sarathi.shakti.ocr.engine import RapidOCREngine


class DummyOutput:
    def __init__(self, txts: list[str], boxes: list[Any], scores: list[float]) -> None:
        self.txts = txts
        self.boxes = boxes
        self.scores = scores


def test_absence_of_ne_ocr_and_onnxruntime_production_paths() -> None:
    """Proves that NE-OCR and ONNX Runtime are completely absent from the production OCR stack."""
    # 1. ne_ocr.py module must not exist
    engine_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "shakti" / "ocr" / "engine"
    assert not (engine_dir / "ne_ocr.py").exists(), "ne_ocr.py must be removed from production."

    # 2. Manifest must only declare the 4 approved production models
    manifest_path = Path(__file__).resolve().parents[2] / "data" / "ocr" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "ne_ocr" not in manifest["models"], "ne_ocr must not appear in manifest.json"
    assert "rec" not in manifest["models"], "old generic rec model must not appear in manifest.json"
    assert set(manifest["models"].keys()) == {"det", "cls", "rec_devanagari", "rec_v6_en"}

    # 3. Engine exports must not expose NEOCRFallbackAdapter
    ocr_engine_pkg = importlib.import_module("sarathi.shakti.ocr.engine")
    assert not hasattr(ocr_engine_pkg, "NEOCRFallbackAdapter")


def test_accurate_mode_executes_same_engine_weak_crop_retry() -> None:
    """Accurate OCR must retry weak spans using the same recognizer and record retry metadata."""
    engine = RapidOCREngine(default_lang="hi")

    invoked_crops: list[Any] = []

    def mock_call(img_arr: Any, **kwargs: Any) -> DummyOutput:
        if kwargs.get("use_det") is False:
            # Crop retry invocation on the SAME recognizer
            invoked_crops.append(img_arr)
            return DummyOutput(
                txts=["राजस्थान सरकार"],
                boxes=[],
                scores=[0.95],
            )
        # Full-page detection & recognition pass (initial low-confidence inference)
        return DummyOutput(
            txts=["राजस्धान सरकार"],
            boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
            scores=[0.52],  # Weak confidence (< 0.65)
        )

    engine._engine = mock_call

    img = Image.new("RGB", (200, 100), color="white")
    page_data, provenance, _, _ = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-retry-test",
        profile=ExecutionProfile.ACCURATE,
    )

    # Verify same-engine retry was invoked exactly once for the weak span
    assert len(invoked_crops) == 1
    assert isinstance(invoked_crops[0], np.ndarray)

    # Verify updated span text and confidence
    assert len(page_data.spans) == 1
    span = page_data.spans[0]
    assert span.text == "राजस्थान सरकार"
    assert span.confidence == 0.95
    assert span.metadata["retry_applied"] is True
    assert span.metadata["original_confidence"] == 0.52
    assert span.metadata["replacement_confidence"] == 0.95
    assert span.metadata["confidence_gain"] == 0.43

    # Verify truthful provenance evidence
    assert provenance.evidence["retry_applied"] is True
    assert provenance.evidence["retry_improved_count"] == 1
    assert provenance.evidence["retry_count"] == 1
    assert provenance.evidence["retry_total_gain"] == 0.43


def test_instant_mode_never_invokes_weak_crop_retry() -> None:
    """Instant mode is latency-oriented and must never invoke crop retries even for weak spans."""
    engine = RapidOCREngine(default_lang="hi")

    retry_invoked = False

    def mock_call(img_arr: Any, **kwargs: Any) -> DummyOutput:
        nonlocal retry_invoked
        if kwargs.get("use_det") is False:
            retry_invoked = True
            return DummyOutput(txts=["राजस्थान"], boxes=[], scores=[0.95])
        return DummyOutput(
            txts=["राजस्धान"],
            boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
            scores=[0.48],
        )

    engine._engine = mock_call

    img = Image.new("RGB", (200, 100), color="white")
    page_data, provenance, _, _ = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-instant-test",
        profile=ExecutionProfile.INSTANT,
    )

    assert not retry_invoked, "Instant mode must not execute weak-crop retries."
    assert page_data.spans[0].text == "राजस्धान"
    assert page_data.spans[0].confidence == 0.48
    assert "retry_applied" not in provenance.evidence or not provenance.evidence.get("retry_applied")


def test_numeric_preservation_guard_rejects_corrupted_retry() -> None:
    """If a retry mutates or corrupts numeric tokens, the replacement must be safely rejected."""
    engine = RapidOCREngine(default_lang="en")

    def mock_call(img_arr: Any, **kwargs: Any) -> DummyOutput:
        if kwargs.get("use_det") is False:
            # Hallucinated replacement that alters digits (1024 -> 9999)
            return DummyOutput(
                txts=["INVOICE-9999"],
                boxes=[],
                scores=[0.99],
            )
        return DummyOutput(
            txts=["INVOICE-1024"],
            boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
            scores=[0.50],
        )

    engine._engine = mock_call

    img = Image.new("RGB", (200, 100), color="white")
    page_data, provenance, _, _ = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-numeric-guard",
        profile=ExecutionProfile.ACCURATE,
    )

    # Replacement rejected because digits did not match; original text and confidence preserved
    assert page_data.spans[0].text == "INVOICE-1024"
    assert page_data.spans[0].confidence == 0.50
    assert not page_data.spans[0].metadata.get("retry_applied", False)
    assert not provenance.evidence.get("retry_applied", False)


def test_weak_crop_retry_devanagari_digit_guard() -> None:
    """Verify weak-crop retry rejects number-corrupting replacements and accepts digit-preserving ones."""
    from types import SimpleNamespace

    engine = RapidOCREngine(default_lang="hi")
    img = Image.new("RGB", (200, 200), color="white")

    def mock_corrupt(arr, **kwargs):
        if kwargs.get("use_det") is False:
            return SimpleNamespace(txts=["रकम 999"], scores=[0.95])
        return SimpleNamespace(
            txts=["रकम 100"],
            boxes=[[[10, 10], [90, 10], [90, 30], [10, 30]]],
            scores=[0.50],
        )

    engine._engine = mock_corrupt
    p_data, _, _, _ = engine.ocr_page(img, 1, "in-1", profile=ExecutionProfile.ACCURATE)
    assert p_data.spans[0].text == "रकम 100"
    assert p_data.spans[0].confidence == 0.50

    def mock_preserve(arr, **kwargs):
        if kwargs.get("use_det") is False:
            return SimpleNamespace(txts=["रकम १००"], scores=[0.95])
        return SimpleNamespace(
            txts=["रकम 100"],
            boxes=[[[10, 10], [90, 10], [90, 30], [10, 30]]],
            scores=[0.50],
        )

    engine._engine = mock_preserve
    p_data, _, _, _ = engine.ocr_page(img, 1, "in-1", profile=ExecutionProfile.ACCURATE)
    assert p_data.spans[0].text == "रकम 100"
    assert p_data.spans[0].confidence == 0.95
    assert p_data.spans[0].metadata.get("retry_applied") is True

    # Verify that disabling normalize_digits retains raw Devanagari numerals
    p_data_raw, _, _, _ = engine.ocr_page(
        img, 1, "in-1", profile=ExecutionProfile.ACCURATE, custom_options={"normalize_digits": False}
    )
    assert p_data_raw.spans[0].text == "रकम १००"
    assert p_data_raw.spans[0].confidence == 0.95


def test_weak_crop_retry_concurrency_guards_infer_request() -> None:
    """Verify weak-crop retry stays protected under inference lock/pool without Infer Request is busy."""
    import threading
    import time
    from unittest.mock import MagicMock

    coordinator = RapidOCREngine()

    active_calls = 0
    max_concurrent_seen = 0
    call_lock = threading.Lock()

    def mock_engine(img: Any, use_det: bool = True, use_cls: bool = True, **_kwargs: Any) -> MagicMock:
        nonlocal active_calls, max_concurrent_seen
        with call_lock:
            active_calls += 1
            if active_calls > max_concurrent_seen:
                max_concurrent_seen = active_calls
            if active_calls > 1:
                raise RuntimeError("Infer Request is busy")

        time.sleep(0.01)

        with call_lock:
            active_calls -= 1

        res = MagicMock()
        res.boxes = np.array([[[10, 10], [50, 10], [50, 20], [10, 20]]])
        res.txts = ["Test"]
        res.scores = [0.40]
        return res

    coordinator._engine = mock_engine

    num_threads = 4
    errors: list[Exception] = []
    results = [None] * num_threads

    def worker(idx: int) -> None:
        img = Image.new("RGB", (100, 100), color="white")
        try:
            p_data, p_prov, conf, warns = coordinator.ocr_page(
                img,
                page_number=idx + 1,
                input_id=f"inp-{idx}",
                profile=ExecutionProfile.ACCURATE,
                custom_options={"retry_enabled": True},
            )
            results[idx] = p_data
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent OCR with retry threw errors: {errors}"
    assert max_concurrent_seen == 1, f"Expected strictly 1 concurrent inference call, got {max_concurrent_seen}"
    assert all(r is not None for r in results)
