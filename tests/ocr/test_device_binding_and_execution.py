"""Unit and integration tests for OCR engine device binding and Yantra execution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from sarathi.sankalpa import (
    CapabilityDeclaration,
    DeviceRequirement,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
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
        engine._engines["en:GPU"] = mock_rapidocr
        engine._model_labels["en:GPU"] = "PP-OCRv5"

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

    def test_engine_defaults_to_cpu_when_no_binding(self) -> None:
        mock_rapidocr = MagicMock()
        mock_output = MagicMock()
        mock_output.txts = ["Account 999"]
        mock_output.boxes = [[[0, 0], [50, 0], [50, 10], [0, 10]]]
        mock_output.scores = [0.95]
        mock_rapidocr.return_value = mock_output

        engine = RapidOCREngine()
        engine._engines["en:CPU"] = mock_rapidocr
        engine._model_labels["en:CPU"] = "PP-OCRv5"

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
                ProvenanceRecord(source_input_id=input_id, stage="ocr", plugin_id="shakti.ocr", capability_id="ocr", page_number=page_num, evidence={}),
                None,
                (),
            )

        mock_engine.ocr_page.side_effect = mock_ocr

        cap = OCRCapability(engine=mock_engine, yantra=yantra)

        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy content")

        img1 = Image.new("RGB", (50, 50), color="white")
        img2 = Image.new("RGB", (50, 50), color="white")

        with patch("sarathi.shakti.ocr.capability.extract_images_from_bytes", return_value=[img1, img2]):
            req = Request(
                request_id="req-multi",
                requirement="ocr",
                inputs=(InputRef(input_id="in-pdf", source_path=pdf_path, display_name="doc.pdf", size_bytes=100, media_type="application/pdf"),),
            )
            ctx = ExecutionContext(run_id="r1", request_id="req-multi", trace_id="t1", span_id="s1")

            with patch.object(yantra, "execute_subtasks", wraps=yantra.execute_subtasks) as spy_subtasks:
                res = cap.execute(req, ctx)
                assert spy_subtasks.call_count == 1
                assert len(spy_subtasks.call_args[0][0]) == 2

            assert res.data is not None
            doc = res.data
            assert len(doc.pages) == 2
            assert doc.pages[0].page_number == 1
            assert doc.pages[1].page_number == 2

    def test_no_threadpoolexecutor_in_ocr_capability(self) -> None:
        import inspect
        import sarathi.shakti.ocr.capability as cap_module

        src = inspect.getsource(cap_module)
        assert "ThreadPoolExecutor" not in src, "OCRCapability must not create or import ThreadPoolExecutor"
