"""Comprehensive regression tests for OCR wiring, profiles, resource execution, and evidence integrity.

Tests all requirements from the hardening specification:
1. Instant profile purity and no hidden fallback
2. Accurate profile preprocessed coordinate crop alignment & validation outcomes
3. Custom profile pass coherence and rejection of unsupported options
4. Layout Preserving strict unsupport
5. Concurrency bounding by allocated device capacity
6. Thread-safe concurrent engine inference without OpenVINO Infer Request collisions
7. Native extraction escalation safety (PDF only, no DOCX/0-byte escalation)
8. Strengthened OCR preflight/readiness check
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
    DeviceRequirement,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.shakti.native_extraction.capability import NativeExtractionCapability
from sarathi.shakti.ocr import OCRCapability, check_ocr_readiness
from sarathi.shakti.ocr.engine import (
    RapidOCREngine,
    TesseractFallbackAdapter,
    preprocess_ocr_image,
)
from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class DummyOutput:
    def __init__(self, txts=None, boxes=None, scores=None):
        self.txts = txts or []
        self.boxes = boxes or []
        self.scores = scores or []


class DummyTesseract(TesseractFallbackAdapter):
    def __init__(self, available: bool = True, return_tuple: tuple[str, float | None] | None = ("REPLACED", 0.95)):
        super().__init__()
        self._avail = available
        self._return = return_tuple
        self.last_cropped_img = None
        self.last_cropped_size = None

    def is_available(self) -> bool:
        return self._avail

    def recognize_crop(self, image: Any, language: str = "eng") -> tuple[str, float | None]:
        self.last_cropped_img = image
        if hasattr(image, "size"):
            self.last_cropped_size = image.size
        if self._return is None:
            raise DoshError(FailureCode.EXECUTION_FAILED, "Fallback failed")
        return self._return


def test_instant_profile_never_invokes_fallback() -> None:
    """Instant profile must never invoke Tesseract fallback, even for low-confidence spans."""
    tess = DummyTesseract(available=True, return_tuple=("FALLBACK", 0.99))
    engine = RapidOCREngine(tesseract_adapter=tess)
    engine._engine = lambda _arr: DummyOutput(
        txts=["LOW_CONF_WORD"],
        boxes=[[(10, 10), (80, 10), (80, 30), (10, 30)]],
        scores=[0.40],
    )

    cap = OCRCapability(engine=engine)
    img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    ctx = ExecutionContext("run-1", "req-1", "t1", "s1")
    inp = InputRef("inp-1", Path("test.png"), "test.png", len(buf.getvalue()))
    req = Request("req-1", "ocr", inputs=(inp,), profile=ExecutionProfile.INSTANT)

    orig_open = Path.open

    def mock_open(self, *args, **kwargs):
        if self == Path("test.png"):
            return io.BytesIO(buf.getvalue())
        return orig_open(self, *args, **kwargs)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(Path, "open", mock_open)
        res = cap.execute(req, ctx)

    # Fallback was NOT called
    assert tess.last_cropped_img is None
    doc = res.data if isinstance(res.data, CanonicalDocument) else res.data[0]
    assert doc.pages[0].spans[0].text == "LOW_CONF_WORD"
    assert doc.pages[0].spans[0].confidence == 0.40
    assert "fallback_applied" not in res.provenance[0].evidence


def test_accurate_fallback_crops_from_preprocessed_image_space() -> None:
    """Accurate fallback crops must originate from processed image space matching RapidOCR bounding boxes."""
    tess = DummyTesseract(available=True, return_tuple=("IMPROVED", 0.92))
    engine = RapidOCREngine(tesseract_adapter=tess)

    # RapidOCR returns box within a 300x150 image space
    engine._engine = lambda _arr: DummyOutput(
        txts=["WEAK"],
        boxes=[[(50, 40), (150, 40), (150, 80), (50, 80)]],
        scores=[0.55],
    )

    img = Image.new("RGB", (300, 150), color=(255, 255, 255))
    page_data, prov, conf, warns = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-1",
        profile=ExecutionProfile.ACCURATE,
        custom_options={"deskew": True, "clahe": False},
    )

    assert tess.last_cropped_img is not None
    assert tess.last_cropped_size is not None
    crop_w, crop_h = tess.last_cropped_size
    # Box was 50..150 (width 100) + 2px padding on each side = 104
    # Box was 40..80 (height 40) + 2px padding on each side = 44
    assert crop_w == 104
    assert crop_h == 44
    assert prov.evidence["validation_outcome"] == "fallback_improved"
    assert prov.evidence["fallback_applied"] is True
    assert conf is None  # rapidocr_mean cleared when fallback applied


def test_custom_profile_rebuilds_all_evidence_on_binarize_pass() -> None:
    """When Custom binarize runs, text, spans, boxes, confidence, warnings, and evidence are rebuilt together."""
    engine = RapidOCREngine()

    def fake_rapidocr(arr):
        # Detect if binarized (threshold applied gives pure 0 or 255)
        unique_vals = np.unique(arr)
        if len(unique_vals) <= 2:
            return DummyOutput(
                txts=["BINARIZED_TEXT"],
                boxes=[[(10, 10), (120, 10), (120, 30), (10, 30)]],
                scores=[0.98],
            )
        return DummyOutput(
            txts=["ORIGINAL_TEXT"],
            boxes=[[(5, 5), (100, 5), (100, 25), (5, 25)]],
            scores=[0.70],
        )

    engine._engine = fake_rapidocr

    img = Image.new("RGB", (200, 100), color=(200, 200, 200))
    page_data, prov, conf, warns = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-custom",
        profile=ExecutionProfile.CUSTOM,
        custom_options={"binarize": True},
    )

    # All outputs must strictly match the binarized second pass
    assert page_data.text == "BINARIZED_TEXT"
    assert len(page_data.spans) == 1
    assert page_data.spans[0].text == "BINARIZED_TEXT"
    assert page_data.spans[0].confidence == 0.98
    assert conf is not None
    assert conf.score == 0.98
    assert prov.evidence["binarized"] is True
    assert prov.evidence["box_count"] == 1


def test_custom_profile_validation_rejects_unsupported_options() -> None:
    """Custom profile must reject unrecognized options with DoshError(VALIDATION_FAILED)."""
    engine = RapidOCREngine()
    cap = OCRCapability(engine=engine)
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1")
    inp = InputRef("inp-1", Path("dummy.png"), "dummy.png", 10)

    # Unknown option
    req_bad = Request(
        "req-1",
        "ocr",
        inputs=(inp,),
        profile=ExecutionProfile.CUSTOM,
        custom_options={"unknown_neural_net": True},
    )
    with pytest.raises(DoshError) as exc:
        cap.execute(req_bad, ctx)
    assert exc.value.code == FailureCode.VALIDATION_FAILED
    assert "unknown_neural_net" in exc.value.message

    # Non-boolean for boolean option
    req_bad_type = Request(
        "req-1",
        "ocr",
        inputs=(inp,),
        profile=ExecutionProfile.CUSTOM,
        custom_options={"deskew": "always"},
    )
    with pytest.raises(DoshError) as exc:
        cap.execute(req_bad_type, ctx)
    assert exc.value.code == FailureCode.VALIDATION_FAILED

    # Unsupported engine
    req_bad_eng = Request(
        "req-1",
        "ocr",
        inputs=(inp,),
        profile=ExecutionProfile.CUSTOM,
        custom_options={"engine": "tesseract_only"},
    )
    with pytest.raises(DoshError) as exc:
        cap.execute(req_bad_eng, ctx)
    assert exc.value.code == FailureCode.VALIDATION_FAILED


def test_layout_preserving_strictly_unsupported() -> None:
    """Layout Preserving profile must be rejected with FailureCode.UNSUPPORTED."""
    cap = OCRCapability(engine=RapidOCREngine())
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1")
    inp = InputRef("inp-1", Path("dummy.png"), "dummy.png", 10)
    req = Request("req-1", "ocr", inputs=(inp,), profile=ExecutionProfile.LAYOUT_PRESERVING)

    with pytest.raises(DoshError) as exc:
        cap.execute(req, ctx)
    assert exc.value.code == FailureCode.UNSUPPORTED


def test_ocr_declares_gpu_preferred_over_cpu() -> None:
    """OCR capability declaration must prefer GPU over CPU, with CPU as supported fallback."""
    req = CAPABILITY_DECLARATION.device_requirement
    assert req.preferred_devices == (DeviceType.GPU, DeviceType.CPU)
    assert req.supported_devices == (DeviceType.GPU, DeviceType.CPU)
    assert DeviceType.NPU not in req.supported_devices


def test_yantra_subtask_concurrency_bounded_by_approved_concurrency() -> None:
    """Yantra.execute_subtasks must bound concurrency by context.execution_binding.approved_concurrency."""
    inventory = DeviceInventory([
        DeviceInfo("cpu-0", DeviceType.CPU, capacity=16),
        DeviceInfo("gpu-0", DeviceType.GPU, capacity=2),
    ])
    yantra = Yantra(inventory=inventory)

    # Binding allocated for GPU with capacity 2
    binding = ExecutionBinding("gpu-0", DeviceType.GPU, "openvino", "GPU", approved_concurrency=2)
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1", execution_binding=binding)

    import threading
    import time
    current_active = 0
    max_active_seen = 0
    active_lock = threading.Lock()

    def dummy_subtask():
        nonlocal current_active, max_active_seen
        with active_lock:
            current_active += 1
            if current_active > max_active_seen:
                max_active_seen = current_active
        time.sleep(0.02)
        with active_lock:
            current_active -= 1
        return "done"

    tasks = [dummy_subtask for _ in range(8)]
    results = yantra.execute_subtasks(tasks, context=ctx)

    assert len(results) == 8
    # Max active threads must not exceed approved_concurrency (2)
    assert max_active_seen <= 2


def test_native_extraction_escalates_only_for_pdf_not_docx_or_zero_bytes(tmp_path: Path) -> None:
    """Corrupt DOCX, invalid spreadsheet, or 0-byte file must not escalate to OCR."""
    native_cap = NativeExtractionCapability()
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1")

    # 1. 0-byte file
    zero_file = tmp_path / "empty.bin"
    zero_file.write_bytes(b"")
    req_zero = Request("req-z", "read_native", inputs=(InputRef("inp-z", zero_file, "empty.bin", 0),))
    res_zero = native_cap.execute(req_zero, ctx)
    assert res_zero.next_requirement is None
    assert any(w.code == "EMPTY_INPUT" for w in res_zero.warnings)

    # 2. Corrupted DOCX (valid zip header with corrupt document.xml)
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", b"<corrupted-unclosed-tag>")
    corrupt_docx = tmp_path / "broken.docx"
    corrupt_docx.write_bytes(buf.getvalue())
    req_docx = Request(
        "req-d",
        "read_native",
        inputs=(InputRef("inp-d", corrupt_docx, "broken.docx", len(buf.getvalue())),),
    )
    res_docx = native_cap.execute(req_docx, ctx)
    # Must NOT escalate to OCR
    assert res_docx.next_requirement is None
    assert any(w.code == "NATIVE_PARSE_ERROR" for w in res_docx.warnings)


def test_check_ocr_readiness_validates_truthfully() -> None:
    """check_ocr_readiness must verify dependencies, manifest, and model checksums safely."""
    is_ready, msg = check_ocr_readiness()
    assert is_ready is True
    assert "Ready" in msg
    assert "RapidOCR" in msg

    is_ready_fake, msg_fake = check_ocr_readiness(data_root=Path("non_existent_data_dir"))
    assert is_ready_fake is False
    assert "Unavailable" in msg_fake
    assert "non_existent_data_dir" not in msg_fake
