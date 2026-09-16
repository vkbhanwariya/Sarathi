"""Comprehensive regression tests for OCR wiring, profiles, resource execution, and evidence integrity.

Tests all requirements from the hardening specification:
1. Instant profile purity and no hidden fallback
2. Accurate profile preprocessed coordinate crop alignment & validation outcomes
3. Custom profile pass coherence and rejection of unsupported options
4. Concurrency bounding by allocated device capacity
5. Thread-safe concurrent engine inference without OpenVINO Infer Request collisions
6. Native extraction escalation safety (PDF only, no DOCX/0-byte escalation)
7. Strengthened OCR preflight/readiness check
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
    _resolve_target_device,
)
from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class DummyOutput:
    def __init__(self, txts=None, boxes=None, scores=None):
        self.txts = txts or []
        self.boxes = boxes or []
        self.scores = scores or []


def test_instant_profile_never_invokes_fallback() -> None:
    """Instant profile must never invoke retry, even for low-confidence spans."""
    engine = RapidOCREngine(default_lang="hi")
    retry_invoked = False

    def mock_call(arr, **kwargs):
        nonlocal retry_invoked
        if kwargs.get("use_det") is False:
            retry_invoked = True
            return DummyOutput(txts=["FALLBACK"], boxes=[], scores=[0.99])
        return DummyOutput(
            txts=["राज"],
            boxes=[[(10, 10), (80, 10), (80, 30), (10, 30)]],
            scores=[0.40],
        )

    engine._engine = mock_call

    cap = OCRCapability(engine=engine)
    img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    ctx = ExecutionContext("run-1", "req-1", "t1", "s1")
    inp = InputRef("inp-1", Path("test.png"), "test.png", len(buf.getvalue()))
    req = Request("req-1", "ocr", inputs=(inp,), profile=ExecutionProfile.INSTANT)

    orig_open = Path.open

    def fake_open(p_self, *args, **kwargs):
        if str(p_self).endswith("test.png"):
            return io.BytesIO(buf.getvalue())
        return orig_open(p_self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "open", fake_open)
        res = cap.execute(req, ctx)

    # Prove retry was bypassed
    doc = res.data if isinstance(res.data, CanonicalDocument) else res.data[0]
    page = doc.pages[0]
    assert not retry_invoked
    assert page.text == "राज"
    assert page.metadata["validation_outcome"] != "retry_improved"


def test_instant_page_does_not_materialize_unused_fallback_image() -> None:
    """Instant OCR must not allocate a PIL fallback crop image that cannot be used."""
    engine = RapidOCREngine()
    engine._engine = lambda _arr: DummyOutput(
        txts=["FAST_PATH"],
        boxes=[[(10, 10), (80, 10), (80, 30), (10, 30)]],
        scores=[0.99],
    )
    image = Image.new("RGB", (200, 100), color=(255, 255, 255))

    with patch.object(Image, "fromarray", side_effect=AssertionError("unused PIL copy created")):
        page, _, _, _ = engine.ocr_page(
            image,
            page_number=1,
            input_id="instant-no-pil-copy",
            profile=ExecutionProfile.INSTANT,
            custom_options={"preprocess": False},
        )
    assert page.text == "FAST_PATH"


def test_instant_profile_bypasses_preprocessing_when_requested() -> None:
    """Instant profile with preprocess=False does not execute any PIL/OpenCV filtering."""
    engine = RapidOCREngine()
    engine._engine = lambda _arr: DummyOutput(
        txts=["FAST_PATH"],
        boxes=[[(5, 5), (60, 5), (60, 20), (5, 20)]],
        scores=[0.90],
    )

    image = Image.new("RGB", (100, 50), color="white")

    with patch("sarathi.shakti.ocr.engine.preprocess_ocr_image") as mock_prep:
        page, prov, conf, warns = engine.ocr_page(
            image,
            page_number=1,
            input_id="instant-fast-path",
            profile=ExecutionProfile.INSTANT,
            custom_options={"preprocess": False},
        )

    assert page.text == "FAST_PATH"
    mock_prep.assert_not_called()


def test_accurate_weak_crop_retry_from_preprocessed_image_space() -> None:
    """Accurate mode weak-crop retry must crop from preprocessed image space matching RapidOCR bounding boxes."""
    engine = RapidOCREngine(default_lang="hi")
    crops_seen: list[Any] = []

    def mock_engine(arr, **kwargs):
        if kwargs.get("use_det") is False:
            crops_seen.append(arr)
            return DummyOutput(txts=["राजस्थान"], boxes=[], scores=[0.92])
        return DummyOutput(
            txts=["राज"],
            boxes=[[(50, 40), (150, 40), (150, 80), (50, 80)]],
            scores=[0.55],
        )

    engine._engine = mock_engine
    img = Image.new("RGB", (300, 150), color=(255, 255, 255))
    page_data, prov, conf, warns = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-1",
        profile=ExecutionProfile.ACCURATE,
        custom_options={"deskew": True, "clahe": False},
    )

    assert len(crops_seen) == 1
    # 50..150 (width 100) + 3px padding on each side = 106
    # 40..80 (height 40) + 3px padding on each side = 46
    assert crops_seen[0].shape[1] == 106
    assert crops_seen[0].shape[0] == 46
    assert prov.evidence["validation_outcome"] == "retry_improved"
    assert prov.evidence["retry_applied"] is True


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
        '"cls": {"filename": "cls.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"rec_devanagari": {"filename": "rec_devanagari.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"rec_v6_en": {"filename": "rec_v6_en.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}}}',
        encoding="utf-8",
    )
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "det.onnx").write_bytes(b"")
    (models_dir / "cls.onnx").write_bytes(b"")
    (models_dir / "rec_devanagari.onnx").write_bytes(b"")
    (models_dir / "rec_v6_en.onnx").write_bytes(b"")

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
        '"cls": {"filename": "cls.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"rec_devanagari": {"filename": "rec_devanagari.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"rec_v6_en": {"filename": "rec_v6_en.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}}}',
        encoding="utf-8",
    )
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "det.onnx").write_bytes(b"")
    (models_dir / "cls.onnx").write_bytes(b"")
    (models_dir / "rec_devanagari.onnx").write_bytes(b"")
    (models_dir / "rec_v6_en.onnx").write_bytes(b"")

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


def test_custom_options_extended_validation() -> None:
    """Verify extended custom options (fallback_threshold, review_threshold, use_angle_cls, preserve_layout)."""
    from sarathi.sankalpa import ExecutionContext, ExecutionProfile, InputRef, PageData, Request
    from sarathi.shakti.ocr.capability import OCRCapability

    mock_engine = MagicMock()
    mock_p = PageData(page_number=1, text="ok")
    mock_engine.ocr_page.return_value = (mock_p, None, None, ())
    cap = OCRCapability(engine=mock_engine)

    valid_req = Request(
        "req-1",
        "ocr",
        inputs=(InputRef("in-1", Path("test.png"), "image/png", 100),),
        profile=ExecutionProfile.CUSTOM,
        custom_options={
            "fallback_threshold": 0.85,
            "review_threshold": 0.70,
            "use_angle_cls": True,
            "preserve_layout": True,
        },
    )
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1")

    with patch.object(Path, "open", return_value=io.BytesIO(b"fake_image_bytes")):
        with patch("sarathi.shakti.ocr.capability.iter_images_from_bytes", return_value=[MagicMock()]):
            with patch("sarathi.shakti.ocr.capability.get_page_count_from_bytes", return_value=1):
                res = cap.execute(valid_req, ctx)
                assert res is not None

    # Test invalid float option (> 1.0)
    invalid_req_high = Request(
        "req-2",
        "ocr",
        inputs=(InputRef("in-1", Path("test.png"), "image/png", 100),),
        profile=ExecutionProfile.CUSTOM,
        custom_options={"fallback_threshold": 1.5},
    )
    with pytest.raises(DoshError) as exc_high:
        cap.execute(invalid_req_high, ctx)
    assert exc_high.value.code is FailureCode.VALIDATION_FAILED

    # Test invalid float option (boolean instead of float)
    invalid_req_bool = Request(
        "req-3",
        "ocr",
        inputs=(InputRef("in-1", Path("test.png"), "image/png", 100),),
        profile=ExecutionProfile.CUSTOM,
        custom_options={"review_threshold": True},
    )
    with pytest.raises(DoshError) as exc_bool:
        cap.execute(invalid_req_bool, ctx)
    assert exc_bool.value.code is FailureCode.VALIDATION_FAILED


def test_footer_removal_preserves_lower_body_content() -> None:
    """Verify footer detection uses actual page canvas height, preserving lower body amounts."""
    from sarathi.sankalpa import (
        ExecutionProfile,
        InputRef,
        PageData,
        Request,
        Result,
        TextSpan,
    )
    from sarathi.shakti.ocr.capability import OCRCapability

    cap = OCRCapability()

    # Document where text only goes down to y=400 on an 800px page canvas
    # The last line matches template 'Amount: <num>' on both pages
    p1 = PageData(
        page_number=1,
        text="Header Text\nBody Line 1\nAmount: 100",
        spans=(
            TextSpan("Header Text", 0.9, (50.0, 50.0, 200.0, 70.0)),
            TextSpan("Body Line 1", 0.9, (50.0, 200.0, 200.0, 220.0)),
            TextSpan("Amount: 100", 0.9, (50.0, 380.0, 200.0, 400.0)),
        ),
        metadata={"page_height": 800.0, "page_width": 600.0},
    )
    p2 = PageData(
        page_number=2,
        text="Header Text\nBody Line 2\nAmount: 200",
        spans=(
            TextSpan("Header Text", 0.9, (50.0, 50.0, 200.0, 70.0)),
            TextSpan("Body Line 2", 0.9, (50.0, 200.0, 200.0, 220.0)),
            TextSpan("Amount: 200", 0.9, (50.0, 380.0, 200.0, 400.0)),
        ),
        metadata={"page_height": 800.0, "page_width": 600.0},
    )

    req = Request(
        "req-1",
        "ocr",
        inputs=(InputRef("in-1", Path("test.png"), "image/png", 100),),
        profile=ExecutionProfile.INSTANT,
    )
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1")

    mock_engine = MagicMock()
    mock_engine.ocr_page.side_effect = [
        (p1, None, None, ()),
        (p2, None, None, ()),
    ]
    cap = OCRCapability(engine=mock_engine)

    with patch.object(Path, "read_bytes", return_value=b"fake_image_bytes"):
        with patch("sarathi.shakti.ocr.capability.iter_images_from_bytes", return_value=[MagicMock(), MagicMock()]):
            with patch("sarathi.shakti.ocr.capability.get_page_count_from_bytes", return_value=2):
                res = cap.execute(req, ctx)
                assert isinstance(res, Result)
                final_doc = res.data
                # 'Amount: 100' and 'Amount: 200' must NOT be stripped!
                assert "Amount: 100" in final_doc.pages[0].text
                assert "Amount: 200" in final_doc.pages[1].text


def test_xycut_prevents_column_interleaving() -> None:
    """Verify XY-Cut sorts two distinct columns sequentially instead of interleaving rows."""
    from sarathi.sankalpa import TextSpan
    from sarathi.shakti.ocr.engine.parser import sort_reading_order_xycut

    # Column 1 items (x: 50..200)
    c1_1 = TextSpan("Col 1 Line 1", 0.9, (50.0, 100.0, 200.0, 120.0))
    c1_2 = TextSpan("Col 1 Line 2", 0.9, (50.0, 140.0, 200.0, 160.0))
    c1_3 = TextSpan("Col 1 Line 3", 0.9, (50.0, 180.0, 200.0, 200.0))

    # Column 2 items (x: 350..500)
    c2_1 = TextSpan("Col 2 Line 1", 0.9, (350.0, 100.0, 500.0, 120.0))
    c2_2 = TextSpan("Col 2 Line 2", 0.9, (350.0, 140.0, 500.0, 160.0))
    c2_3 = TextSpan("Col 2 Line 3", 0.9, (350.0, 180.0, 500.0, 200.0))

    # Interleaved input list
    input_spans = [c1_1, c2_1, c1_2, c2_2, c1_3, c2_3]
    ordered = sort_reading_order_xycut(input_spans)

    # Must be all Column 1 items, followed by all Column 2 items
    expected_order = [c1_1, c1_2, c1_3, c2_1, c2_2, c2_3]
    assert [s.text for s in ordered] == [s.text for s in expected_order]


def test_weak_crop_retry_number_preservation_and_digit_guard() -> None:
    """Verify weak-crop retry rejects number-corrupting replacements and accepts digit-preserving ones."""
    from types import SimpleNamespace

    from PIL import Image

    from sarathi.sankalpa import ExecutionProfile
    from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine

    engine = RapidOCREngine(default_lang="hi")
    img = Image.new("RGB", (200, 200), color="white")

    # Case 1: Devanagari span with digits where retry corrupts the digits (100 -> 999)
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

    # Case 2: Devanagari span with digits where retry preserves digits (Devanagari १०० -> 100)
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
    assert p_data.spans[0].text == "रकम १००"
    assert p_data.spans[0].confidence == 0.95
    assert p_data.spans[0].metadata.get("retry_applied") is True


def test_json_export_preserves_metadata_and_tables() -> None:
    """Verify JSON export artifact preserves span metadata, language, script, and tables."""
    import json

    from sarathi.sankalpa import (
        ExecutionProfile,
        InputRef,
        PageData,
        Request,
        TableData,
        TextSpan,
    )
    from sarathi.shakti.ocr.capability import OCRCapability

    cap = OCRCapability()

    table = TableData(
        name="test_table",
        headers=("ColA", "ColB"),
        rows=(("1", "2"), ("3", "4")),
        metadata={"source": "test"},
    )
    span = TextSpan(
        text="Sample text",
        confidence=0.92,
        bounding_box=(10.0, 20.0, 100.0, 40.0),
        language="hi",
        script="Devanagari",
        metadata={"span_id": "sp-1", "custom": "meta"},
    )
    p = PageData(
        page_number=1,
        text="Sample text",
        spans=(span,),
        tables=(table,),
        metadata={"page_height": 500.0, "page_width": 400.0},
    )

    req = Request(
        "req-1",
        "ocr",
        inputs=(InputRef("in-1", Path("test.png"), "image/png", 100),),
        profile=ExecutionProfile.INSTANT,
    )
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1")

    mock_engine = MagicMock()
    mock_engine.ocr_page.return_value = (p, None, None, ())
    cap = OCRCapability(engine=mock_engine)

    with patch.object(Path, "read_bytes", return_value=b"fake_image_bytes"):
        with patch("sarathi.shakti.ocr.capability.iter_images_from_bytes", return_value=[MagicMock()]):
            with patch("sarathi.shakti.ocr.capability.get_page_count_from_bytes", return_value=1):
                res = cap.execute(req, ctx)
            json_payload = [pl for pl in res.artifact_payloads if pl.intent.media_type == "application/json"][0]
            data = json.loads(json_payload.content.decode("utf-8"))

            page_json = data["pages"][0]
            assert len(page_json["tables"]) == 1
            assert page_json["tables"][0]["name"] == "test_table"
            assert page_json["tables"][0]["headers"] == ["ColA", "ColB"]

            span_json = page_json["spans"][0]
            assert span_json["text"] == "Sample text"
            assert span_json["language"] == "hi"
            assert span_json["script"] == "Devanagari"
            assert span_json["metadata"]["span_id"] == "sp-1"
            assert span_json["metadata"]["custom"] == "meta"


def test_factory_sets_rec_text_score_zero(tmp_path: Path) -> None:
    """Verify that build_rapidocr_instance configures Rec.text_score to 0.0."""
    from sarathi.shakti.ocr.engine.factory import build_rapidocr_instance

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        '{"models": {"det": {"filename": "det.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"cls": {"filename": "cls.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"rec_devanagari": {"filename": "rec_devanagari.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}, '
        '"rec_v6_en": {"filename": "rec_v6_en.onnx", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}}}',
        encoding="utf-8",
    )
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "det.onnx").write_bytes(b"")
    (models_dir / "cls.onnx").write_bytes(b"")
    (models_dir / "rec_devanagari.onnx").write_bytes(b"")
    (models_dir / "rec_v6_en.onnx").write_bytes(b"")

    captured_params = {}

    def mock_init(params=None):
        nonlocal captured_params
        captured_params = params or {}
        return MagicMock()

    with patch("rapidocr.RapidOCR", side_effect=mock_init):
        inst, _, _, _ = build_rapidocr_instance(
            data_root=tmp_path,
            lang="en",
            target_device="CPU",
            verified_model_paths={},
        )
        assert inst is not None
        assert captured_params.get("Rec.text_score") == 0.0


def test_openvino_and_ocr_zero_network_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that checking OCR readiness and importing OpenVINO makes zero outbound socket connections."""
    import socket

    from sarathi.shakti.ocr.engine import check_ocr_readiness

    def denied_connect(self, *args, **kwargs):
        raise RuntimeError("NETWORK_ACCESS_DENIED: Socket connection forbidden by Kavacha/local policy.")

    monkeypatch.setattr(socket.socket, "connect", denied_connect)

    is_ready, reason = check_ocr_readiness()
    try:
        import openvino as ov

        core = ov.Core()
        _ = core.available_devices
    except ImportError:
        pass


def test_ocr_coordinator_serializes_concurrent_inference_calls() -> None:
    """Verify coordinator._infer_lock serializes concurrent inference calls to prevent Infer Request collision."""
    import threading

    import numpy as np
    from PIL import Image

    from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine

    coordinator = RapidOCREngine()

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

        time.sleep(0.01)

        with call_lock:
            active_calls -= 1

        res = MagicMock()
        res.boxes = np.array([[[10, 10], [50, 10], [50, 20], [10, 20]]])
        res.txts = ["Test"]
        res.scores = [0.95]
        return res

    coordinator._engine = mock_engine

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
