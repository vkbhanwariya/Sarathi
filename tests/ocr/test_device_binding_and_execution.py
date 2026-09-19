"""Unit and integration tests for OCR engine device binding and Yantra execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from sarathi.sankalpa import (
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
)
from sarathi.shakti.ocr.capability import OCRCapability
from sarathi.shakti.ocr.engine import RapidOCREngine
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class TestOCREngineDeviceBinding:
    def test_engine_passes_target_device_and_records_provenance(self) -> None:
        mock_rapidocr = MagicMock()
        mock_output = MagicMock()
        mock_output.txts = ["Invoice 12345"]
        mock_output.boxes = [[[0, 0], [100, 0], [100, 20], [0, 20]]]
        mock_output.scores = [0.98]
        mock_rapidocr.return_value = mock_output

        engine = RapidOCREngine()
        # Pre-populate engine cache with mock for GPU
        binding_gpu = ExecutionBinding(
            device_id="gpu-0",
            device_type=DeviceType.GPU,
            backend="openvino",
            backend_device_id="GPU",
        )
        engine._engines["devanagari:GPU"] = mock_rapidocr
        engine._model_labels["devanagari:GPU"] = "PP-OCRv5-Devanagari"

        img = Image.new("RGB", (200, 50), color="white")
        page_data, prov, conf, warns = engine.ocr_page(
            img,
            page_number=1,
            input_id="in-1",
            execution_binding=binding_gpu,
        )

        assert page_data.text == "Invoice 12345"
        assert prov.evidence["device"] == "GPU"
        assert prov.evidence["backend"] == "openvino"
        assert conf is not None
        assert conf.evidence["device"] == "GPU"

    def test_engine_cache_strictly_isolated_between_cpu_and_gpu(self) -> None:
        mock_gpu = MagicMock()
        mock_cpu = MagicMock()
        mock_gpu.return_value = MagicMock(
            txts=["GPU Text"], boxes=[[[0, 0], [10, 0], [10, 10], [0, 10]]], scores=[0.99]
        )
        mock_cpu.return_value = MagicMock(
            txts=["CPU Text"], boxes=[[[0, 0], [10, 0], [10, 10], [0, 10]]], scores=[0.95]
        )

        engine = RapidOCREngine()
        engine._engines["v6_en:GPU"] = mock_gpu
        engine._model_labels["v6_en:GPU"] = "PP-OCRv6-GPU"
        engine._engines["v6_en:CPU"] = mock_cpu
        engine._model_labels["v6_en:CPU"] = "PP-OCRv6-CPU"

        img = Image.new("RGB", (100, 40), color="white")
        binding_cpu = ExecutionBinding(
            device_id="cpu-0",
            device_type=DeviceType.CPU,
            backend="openvino",
            backend_device_id="CPU",
        )
        binding_gpu = ExecutionBinding(
            device_id="gpu-0",
            device_type=DeviceType.GPU,
            backend="openvino",
            backend_device_id="GPU",
        )

        p_cpu, prov_cpu, _, _ = engine.ocr_page(
            img, 1, "in-1", custom_options={"lang": "en"}, execution_binding=binding_cpu
        )
        assert p_cpu.text == "CPU Text"
        assert prov_cpu.evidence["device"] == "CPU"

        p_gpu, prov_gpu, _, _ = engine.ocr_page(
            img, 1, "in-1", custom_options={"lang": "en"}, execution_binding=binding_gpu
        )
        assert p_gpu.text == "GPU Text"
        assert prov_gpu.evidence["device"] == "GPU"

    def test_gpu_dual_stream_pool_concurrency(self) -> None:
        import queue

        mock_slot0 = MagicMock()
        mock_slot1 = MagicMock()
        mock_slot0.return_value = MagicMock(
            txts=["Slot 0 Output"], boxes=[[[0, 0], [10, 0], [10, 10], [0, 10]]], scores=[0.99]
        )
        mock_slot1.return_value = MagicMock(
            txts=["Slot 1 Output"], boxes=[[[0, 0], [10, 0], [10, 10], [0, 10]]], scores=[0.98]
        )

        engine = RapidOCREngine()
        cache_key = "v6_en:GPU"
        q: queue.Queue[int] = queue.Queue()
        q.put(0)
        q.put(1)
        engine._engines[cache_key] = mock_slot0
        engine._gpu_pools[cache_key] = q
        engine._gpu_engines[cache_key] = [mock_slot0, mock_slot1]
        engine._model_labels[cache_key] = "PP-OCRv6"

        img = Image.new("RGB", (100, 40), color="white")
        binding_gpu = ExecutionBinding(
            device_id="gpu-0",
            device_type=DeviceType.GPU,
            backend="openvino",
            backend_device_id="GPU",
        )

        p1, _, _, _ = engine.ocr_page(img, 1, "in-1", custom_options={"lang": "en"}, execution_binding=binding_gpu)
        p2, _, _, _ = engine.ocr_page(img, 2, "in-1", custom_options={"lang": "en"}, execution_binding=binding_gpu)

        assert p1.text == "Slot 0 Output"
        assert p2.text == "Slot 1 Output"
        assert engine._gpu_pools[cache_key].qsize() == 2

    def test_engine_defaults_to_cpu_when_no_binding(self) -> None:
        mock_rapidocr = MagicMock()
        mock_output = MagicMock()
        mock_output.txts = ["Account 999"]
        mock_output.boxes = [[[0, 0], [50, 0], [50, 10], [0, 10]]]
        mock_output.scores = [0.95]
        mock_rapidocr.return_value = mock_output

        engine = RapidOCREngine()
        engine._engines["devanagari:CPU"] = mock_rapidocr
        engine._model_labels["devanagari:CPU"] = "PP-OCRv5-Devanagari"

        img = Image.new("RGB", (100, 30), color="white")
        page_data, prov, conf, warns = engine.ocr_page(
            img,
            page_number=1,
            input_id="in-1",
            execution_binding=None,
        )

        assert page_data.text == "Account 999"
        assert prov.evidence["device"] == "CPU"
        assert conf is not None
        assert conf.evidence["device"] == "CPU"


class TestOCRCapabilityYantraIntegration:
    def test_capability_routes_multipage_through_yantra_subtasks(self, tmp_path) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2)])
        yantra = Yantra(inventory)

        mock_engine = MagicMock(spec=RapidOCREngine)
        mock_engine._engine = None

        def mock_ocr(img, page_num, input_id, **kwargs):
            return (
                PageData(page_number=page_num, text=f"Page {page_num} Text"),
                ProvenanceRecord(
                    source_input_id=input_id,
                    stage="ocr",
                    plugin_id="shakti.ocr",
                    capability_id="ocr",
                    page_number=page_num,
                    evidence={},
                ),
                None,
                (),
            )

        mock_engine.ocr_page.side_effect = mock_ocr

        cap = OCRCapability(engine=mock_engine, yantra=yantra)

        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy content")

        img1 = Image.new("RGB", (50, 50), color="white")
        img2 = Image.new("RGB", (50, 50), color="white")

        mock_rasterizer = MagicMock()
        mock_rasterizer.get_page.side_effect = [img1, img2]
        with (
            patch("sarathi.shakti.ocr.capability.get_page_count_from_bytes", return_value=2),
            patch("sarathi.shakti.ocr.capability.BoundedPageRasterizer", return_value=mock_rasterizer),
        ):
            req = Request(
                request_id="req-multi",
                requirement="ocr",
                inputs=(
                    InputRef(
                        input_id="in-pdf",
                        source_path=pdf_path,
                        display_name="doc.pdf",
                        size_bytes=100,
                        media_type="application/pdf",
                    ),
                ),
            )
            ctx = ExecutionContext(run_id="r1", request_id="req-multi", trace_id="t1", span_id="s1")

            with patch.object(yantra, "execute_subtasks", wraps=yantra.execute_subtasks) as spy_subtasks:
                res = cap.execute(req, ctx)
                assert spy_subtasks.call_count == 1
                assert len(spy_subtasks.call_args[0][0]) == 2
                assert spy_subtasks.call_args.kwargs == {"context": ctx}

            assert res.data is not None
            doc = res.data
            assert len(doc.pages) == 2
            assert doc.pages[0].page_number == 1
            assert doc.pages[1].page_number == 2

    def test_capability_does_not_own_hardware_or_thread_policy(self) -> None:
        import inspect

        import sarathi.shakti.ocr.capability as cap_module

        src = inspect.getsource(cap_module)
        forbidden = (
            "ThreadPoolExecutor",
            "DeviceSlotPool",
            "create_hybrid_device_pool",
            "hardware_ocr_hybrid_page_threshold",
            "hybrid_device",
            "load_settings",
        )
        for token in forbidden:
            assert token not in src, f"OCRCapability must not own execution-policy detail {token!r}"

    def test_ocr_declares_gpu_preferred_over_cpu(self) -> None:
        """OCR capability declaration must prefer GPU over CPU, with CPU as supported fallback."""
        from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION

        req = CAPABILITY_DECLARATION.device_requirement
        assert req.preferred_devices == (DeviceType.GPU, DeviceType.CPU)
        assert req.supported_devices == (DeviceType.GPU, DeviceType.CPU)
        assert DeviceType.NPU not in req.supported_devices

    def test_ocr_engine_device_dispatch_integrity(self) -> None:
        """Verify factual target device resolution for CPU, GPU, NPU, and rejection of invalid types."""
        from sarathi.dosh import DoshError, FailureCode
        from sarathi.shakti.ocr.engine import _resolve_target_device

        assert _resolve_target_device(None) == "CPU"

        cpu_b = ExecutionBinding("cpu-0", DeviceType.CPU, "cpu", "CPU")
        assert _resolve_target_device(cpu_b) == "CPU"

        gpu_b = ExecutionBinding("gpu-0", DeviceType.GPU, "openvino", "GPU.0")
        assert _resolve_target_device(gpu_b) == "GPU.0"

        npu_b = ExecutionBinding("npu-0", DeviceType.NPU, "openvino", "NPU.0")
        assert _resolve_target_device(npu_b) == "NPU.0"

        npu_default = ExecutionBinding("npu-0", DeviceType.NPU, "openvino", "NPU")
        assert _resolve_target_device(npu_default) == "NPU"

        mock_invalid = MagicMock()
        mock_invalid.device_type = MagicMock()
        mock_invalid.device_type.value = "tpu"
        with pytest.raises(DoshError) as exc_info:
            _resolve_target_device(mock_invalid)
        assert exc_info.value.code is FailureCode.UNSUPPORTED

    def test_ocr_engine_npu_binding_passes_npu_to_rapidocr(self, tmp_path: Path) -> None:
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

    def test_ocr_engine_initialization_failure_raises_dosh_error(self, tmp_path: Path) -> None:
        """Verify hardware or compilation failures raise DoshError(FailureCode.EXECUTION_FAILED)."""
        from sarathi.dosh import DoshError, FailureCode

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

    def test_openvino_and_ocr_zero_network_isolation(self, monkeypatch: pytest.MonkeyPatch) -> None:
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

    def test_ocr_coordinator_serializes_concurrent_inference_calls(self) -> None:
        """Verify coordinator._infer_lock serializes concurrent inference calls to prevent Infer Request collision."""
        import threading
        import time

        import numpy as np
        from PIL import Image

        from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine

        coordinator = RapidOCREngine()

        active_calls = 0
        max_concurrent_seen = 0
        call_lock = threading.Lock()

        def mock_engine(img: Any, use_cls: bool = True, **_kwargs: Any) -> MagicMock:
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

    def test_openvino_device_properties_and_caching(self, tmp_path: Path) -> None:
        """Verify OpenVINO core properties and device patching configure 2026.4 performance hints."""
        from sarathi.shakti.ocr.engine.openvino import get_shared_openvino_core, patch_rapidocr_openvino_device

        cache_dir = tmp_path / "ov_cache"
        core = get_shared_openvino_core(cache_dir=cache_dir)
        assert core is not None

        patch_rapidocr_openvino_device(cache_dir=cache_dir)
        try:
            import rapidocr.inference_engine.openvino.main as ov_main

            assert getattr(ov_main.OpenVINOInferSession, "_sarathi_device_patched", False) is True
        except ImportError:
            pass
