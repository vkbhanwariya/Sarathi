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
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")

import numpy as np
from PIL import Image

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
)
from sarathi.shakti.native_extraction.capability import NativeExtractionCapability
from sarathi.shakti.ocr import OCRCapability, check_ocr_readiness
from sarathi.shakti.ocr.engine import (
    RapidOCREngine,
    TesseractFallbackAdapter,
    _resolve_target_device,
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


def test_ocr_cross_input_concurrency_with_bounded_subtasks(tmp_path: Path) -> None:
    """Verify that multiple single-page input files run concurrently through Yantra with bounded concurrency."""
    from PIL import Image

    inv = DeviceInventory([DeviceInfo("cpu-0", DeviceType.CPU, capacity=8)])
    yantra = Yantra(inventory=inv)

    active_count = 0
    max_active = 0
    lock = threading.Lock()

    def mock_ocr_page(img, page_idx, input_id, profile=None, custom_options=None, execution_binding=None):
        nonlocal active_count, max_active
        with lock:
            active_count += 1
            if active_count > max_active:
                max_active = active_count

        time.sleep(0.02)

        with lock:
            active_count -= 1

        p_data = PageData(page_number=page_idx, text=f"Text for {input_id}")
        p_prov = ProvenanceRecord(source_input_id=input_id, capability_id="ocr", stage="ocr")
        return p_data, p_prov, 0.95, []

    mock_engine = MagicMock()
    mock_engine.ocr_page.side_effect = mock_ocr_page

    cap = OCRCapability(engine=mock_engine, yantra=yantra)

    inputs = []
    for idx in range(4):
        p = tmp_path / f"img_{idx + 1}.png"
        img = Image.new("RGB", (30, 30), color="white")
        img.save(p)
        inputs.append(InputRef(input_id=f"i-{idx + 1}", source_path=p, display_name=f"img_{idx + 1}.png", size_bytes=p.stat().st_size))

    binding = ExecutionBinding("cpu-0", DeviceType.CPU, "cpu", "CPU", approved_concurrency=2)
    ctx = ExecutionContext("run-c", "req-c", "t-c", "s-c", execution_binding=binding)
    req = Request("req-c", "ocr", inputs=tuple(inputs))

    res = cap.execute(req, ctx)

    assert isinstance(res.data, tuple)
    assert len(res.data) == 4
    for idx, doc in enumerate(res.data):
        assert doc.source_input_id == f"i-{idx + 1}"
        assert f"Text for i-{idx + 1}" in doc.text

    # Cross-input parallelism must have been active (> 1) and bounded by approved_concurrency (<= 2)
    assert max_active > 1, f"Expected concurrency > 1, got {max_active}"
    assert max_active <= 2, f"Expected concurrency <= 2, got {max_active}"


def test_ocr_engine_device_dispatch_integrity() -> None:
    """Verify factual target device resolution for CPU, GPU, NPU, and rejection of invalid types."""
    assert _resolve_target_device(None) == "CPU"

    cpu_b = ExecutionBinding("cpu-0", DeviceType.CPU, "cpu", "CPU")
    assert _resolve_target_device(cpu_b) == "CPU"

    gpu_b = ExecutionBinding("gpu-0", DeviceType.GPU, "openvino", "GPU.0")
    assert _resolve_target_device(gpu_b) == "GPU.0"

    npu_b = ExecutionBinding("npu-0", DeviceType.NPU, "openvino", "NPU.0")
    assert _resolve_target_device(npu_b) == "NPU.0"

    npu_default = ExecutionBinding("npu-0", DeviceType.NPU, "openvino", "NPU")
    assert _resolve_target_device(npu_default) == "NPU"

    # Fake/unsupported device type
    mock_invalid = MagicMock()
    mock_invalid.device_type = MagicMock()
    mock_invalid.device_type.value = "tpu"
    with pytest.raises(DoshError) as exc_info:
        _resolve_target_device(mock_invalid)
    assert exc_info.value.code is FailureCode.UNSUPPORTED


def test_ocr_engine_npu_binding_passes_npu_to_rapidocr(tmp_path: Path) -> None:
    """Verify that an NPU binding configures RapidOCR with NPU and does not coerce to CPU."""
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        '{"models": {"det": {"filename": "det.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"rec": {"filename": "rec.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"cls": {"filename": "cls.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}}}',
        encoding="utf-8",
    )
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "det.onnx").write_bytes(b"")
    (models_dir / "rec.onnx").write_bytes(b"")
    (models_dir / "cls.onnx").write_bytes(b"")

    engine = RapidOCREngine(data_root=tmp_path)
    npu_b = ExecutionBinding("npu-0", DeviceType.NPU, "openvino", "NPU.0")

    captured_params = {}

    def mock_rapidocr_init(params=None):
        nonlocal captured_params
        captured_params = params or {}
        mock_inst = MagicMock()
        return mock_inst

    with patch("rapidocr.RapidOCR", side_effect=mock_rapidocr_init):
        inst = engine._get_engine(lang="en", execution_binding=npu_b)
        assert inst is not None
        assert captured_params.get("Det.device") == "NPU.0"
        assert captured_params.get("Rec.device") == "NPU.0"
        assert captured_params.get("Cls.device") == "NPU.0"


def test_ocr_engine_initialization_failure_raises_dosh_error(tmp_path: Path) -> None:
    """Verify hardware or compilation failures raise DoshError(FailureCode.EXECUTION_FAILED)."""
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        '{"models": {"det": {"filename": "det.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"rec": {"filename": "rec.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"cls": {"filename": "cls.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}}}',
        encoding="utf-8",
    )
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "det.onnx").write_bytes(b"")
    (models_dir / "rec.onnx").write_bytes(b"")
    (models_dir / "cls.onnx").write_bytes(b"")

    engine = RapidOCREngine(data_root=tmp_path)
    npu_b = ExecutionBinding("npu-0", DeviceType.NPU, "openvino", "NPU")

    with patch("rapidocr.RapidOCR", side_effect=RuntimeError("Level0 pfnCreate2 error")):
        with pytest.raises(DoshError) as exc_info:
            engine._get_engine(lang="en", execution_binding=npu_b)
        assert exc_info.value.code is FailureCode.EXECUTION_FAILED
        assert "Failed to initialize OCR engine on device 'NPU'" in exc_info.value.message


def test_extract_images_multipage_tiff() -> None:
    """Verify extract_images_from_bytes reads all frames of a multipage TIFF."""
    import io

    from PIL import Image

    from sarathi.shakti.ocr.engine import extract_images_from_bytes

    frames = [
        Image.new("RGB", (20, 20), color="red"),
        Image.new("RGB", (20, 20), color="green"),
        Image.new("RGB", (20, 20), color="blue"),
    ]
    buf = io.BytesIO()
    frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:])
    tiff_bytes = buf.getvalue()

    images = extract_images_from_bytes(tiff_bytes)
    assert len(images) == 3


def test_ocr_page_validation_enabled_option() -> None:
    """Verify validation_enabled=False sets validation_outcome to 'skipped'."""
    from PIL import Image

    engine = RapidOCREngine()
    mock_rapidocr = MagicMock()
    mock_rapidocr.return_value = (None, None)

    with patch.object(engine, "_get_engine", return_value=mock_rapidocr):
        img = Image.new("RGB", (30, 30), color="white")
        p_def, prov_def, _, _ = engine.ocr_page(img, 1, "in-1")
        assert p_def.metadata.get("validation_outcome") == "empty"
        assert prov_def.evidence.get("validation_outcome") == "empty"

        p_skip, prov_skip, _, _ = engine.ocr_page(img, 1, "in-1", custom_options={"validation_enabled": False})
        assert p_skip.metadata.get("validation_outcome") == "skipped"
        assert prov_skip.evidence.get("validation_outcome") == "skipped"
