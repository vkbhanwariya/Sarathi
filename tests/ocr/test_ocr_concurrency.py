"""Focused regression tests for multi-threaded OCR coordinator inference concurrency.

Validates that concurrent page-level OCR tasks running across multiple worker threads
(e.g., 8 workers as configured for GPU hardware) do not encounter OpenVINO InferRequest
collision ('Infer Request is busy') and serialize inference safely under self._infer_lock.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock

import numpy as np
from PIL import Image

from sarathi.sankalpa import ExecutionProfile
from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine


def test_ocr_coordinator_serializes_concurrent_inference_calls() -> None:
    """Simulate OpenVINO's single-InferRequest constraint: if two threads call engine()

    concurrently, it raises RuntimeError('Infer Request is busy').
    Verify that coordinator._infer_lock prevents concurrent calls.
    """
    coordinator = RapidOCREngine()

    # Track active calls inside engine
    active_calls = 0
    max_concurrent_seen = 0
    call_lock = threading.Lock()

    def mock_engine(img: Any, use_cls: bool = True) -> MagicMock:
        nonlocal active_calls, max_concurrent_seen
        with call_lock:
            active_calls += 1
            if active_calls > max_concurrent_seen:
                max_concurrent_seen = active_calls
            if active_calls > 1:
                raise RuntimeError("Infer Request is busy")

        # Simulate GPU inference latency
        time.sleep(0.01)

        with call_lock:
            active_calls -= 1

        res = MagicMock()
        res.boxes = np.array([[[10, 10], [50, 10], [50, 20], [10, 20]]])
        res.txts = ["Test"]
        res.scores = [0.95]
        return res

    coordinator._engine = mock_engine

    # Run 8 concurrent threads calling ocr_page
    num_threads = 8
    errors: list[Exception] = []
    results = [None] * num_threads

    def worker(idx: int) -> None:
        img = Image.new("RGB", (100, 100), color="white")
        try:
            p_data, p_prov, conf, warns = coordinator.ocr_page(
                img,
                page_number=idx + 1,
                input_id=f"inp-{idx}",
                profile=ExecutionProfile.INSTANT,
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
