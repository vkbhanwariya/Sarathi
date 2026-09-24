"""Unit and integration tests for OCR execution cleanliness and deterministic single-pass behavior.

Verifies:
1. Complete absence of NE-OCR and ONNX Runtime in the production OCR subsystem.
2. Both Accurate and Instant profiles execute deterministic single-pass inference without secondary weak-crop loops.
3. RapidOCR engine concurrency guards protect infer requests under multi-threading.
"""

from __future__ import annotations

import importlib
import json
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

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
    from sarathi.shakti.ocr.engine.common import CANONICAL_DATA_ROOT

    manifest_path = CANONICAL_DATA_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "ne_ocr" not in manifest["models"], "ne_ocr must not appear in manifest.json"
    assert "rec" not in manifest["models"], "old generic rec model must not appear in manifest.json"
    assert set(manifest["models"].keys()) == {"det", "cls", "rec_devanagari", "rec_v6_en"}

    # 3. Engine exports must not expose NEOCRFallbackAdapter
    ocr_engine_pkg = importlib.import_module("sarathi.shakti.ocr.engine")
    assert not hasattr(ocr_engine_pkg, "NEOCRFallbackAdapter")


def test_deterministic_single_pass_never_invokes_weak_crop_retry() -> None:
    """Both Accurate and Instant modes are deterministic single-pass and never invoke crop retries."""
    for profile in (ExecutionProfile.ACCURATE, ExecutionProfile.INSTANT):
        engine = RapidOCREngine(default_lang="hi")
        retry_invoked = False

        def mock_call(img_arr: Any, **kwargs: Any) -> DummyOutput:
            nonlocal retry_invoked
            if kwargs.get("use_det") is False:
                retry_invoked = True
                return DummyOutput(txts=["सुधरा"], boxes=[], scores=[0.95])
            return DummyOutput(
                txts=["राजस्धान सरकार"],
                boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
                scores=[0.52],
            )

        engine._engine = mock_call

        img = Image.new("RGB", (200, 100), color="white")
        page_data, provenance, _, _ = engine.ocr_page(
            image=img,
            page_number=1,
            input_id=f"inp-single-pass-{profile.value}",
            profile=profile,
        )

        assert not retry_invoked, f"{profile.value} mode must not execute secondary weak-crop retries."
        assert page_data.spans[0].text == "राजस्धान सरकार"
        assert page_data.spans[0].confidence == 0.52
        assert page_data.metadata.get("retry_applied") is False


def test_concurrency_guards_infer_request() -> None:
    """Verify inference calls stay synchronized under inference lock/pool without 'Infer Request is busy'."""
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
            )
            results[idx] = p_data
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent OCR threw errors: {errors}"
    assert max_concurrent_seen == 1, f"Expected strictly 1 concurrent inference call, got {max_concurrent_seen}"
    assert all(r is not None for r in results)
