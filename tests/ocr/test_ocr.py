"""Unit and end-to-end integration tests for OCR Phase 1 (Instant profile)."""

import importlib.util
import pytest

_OCR_AVAILABLE = (
    importlib.util.find_spec("rapidocr") is not None
    and importlib.util.find_spec("openvino") is not None
    and importlib.util.find_spec("PIL") is not None
)

if not _OCR_AVAILABLE:
    pytest.skip(
        "OCR optional dependencies (rapidocr, openvino, pillow) not installed. Run with --extra ocr to enable.",
        allow_module_level=True,
    )

import json
from pathlib import Path
import shutil
from unittest.mock import MagicMock, patch
from PIL import Image, ImageDraw
import pymupdf

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import Kosh, Manthan, Pravaha
from sarathi.sankalpa import (
    CanonicalDocument,
    DeviceType,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
    TextSpan,
    WarningRecord,
)
from sarathi.shakti.native_extraction import (
    CAPABILITY_DECLARATION as NATIVE_DECLARATION,
    NativeExtractionCapability,
    PLUGIN_INFO as NATIVE_PLUGIN,
)
from sarathi.shakti.ocr import (
    CAPABILITY_DECLARATION as OCR_DECLARATION,
    OCRCapability,
    PLUGIN_INFO as OCR_PLUGIN,
    RapidOCREngine,
)
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


@pytest.fixture
def ocr_capability() -> OCRCapability:
    return OCRCapability()


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-ocr-1",
        request_id="req-ocr-1",
        trace_id="tr-ocr-1",
        span_id="sp-ocr-1",
        profile=ExecutionProfile.INSTANT,
    )


def _create_sample_image(text: str, path: Path) -> Path:
    """Create a high-contrast sample image with text for real OCR."""
    img = Image.new("RGB", (320, 80), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((15, 25), text, fill=(0, 0, 0))
    img.save(str(path))
    return path


def _create_scanned_pdf(text: str, path: Path) -> Path:
    """Create a PDF containing a rendered image page (no text stream)."""
    img_path = path.with_suffix(".png")
    _create_sample_image(text, img_path)

    doc = pymupdf.open()
    img_doc = pymupdf.open(str(img_path))
    rect = img_doc[0].rect
    pdf_bytes = img_doc.convert_to_pdf()
    img_doc.close()

    img_pdf = pymupdf.open("pdf", pdf_bytes)
    page = doc.new_page(width=rect.width, height=rect.height)
    page.show_pdf_page(rect, img_pdf, 0)
    img_pdf.close()

    doc.save(str(path))
    doc.close()
    if img_path.exists():
        img_path.unlink()
    return path


class TestOCRPhase1Instant:
    def test_plugin_and_capability_declarations(self) -> None:
        assert OCR_PLUGIN.plugin_id == "shakti.ocr"
        assert "ocr" in OCR_PLUGIN.capabilities
        assert OCR_DECLARATION.capability_id == "ocr"
        assert OCR_DECLARATION.plugin_id == "shakti.ocr"
        assert OCR_DECLARATION.supported_profiles == (ExecutionProfile.INSTANT,)

    def test_real_image_ocr_execution(
        self, ocr_capability: OCRCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        img_path = tmp_path / "invoice.png"
        _create_sample_image("INVOICE-98765", img_path)

        req = Request(
            request_id="req-img",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-img",
                    source_path=img_path,
                    display_name="invoice.png",
                    size_bytes=img_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        res = ocr_capability.execute(req, context)

        assert isinstance(res, Result)
        assert res.next_requirement is None

        doc = res.data
        assert isinstance(doc, CanonicalDocument)
        assert doc.source_input_id == "inp-img"
        assert doc.detected_type == "ocr_document"
        assert len(doc.pages) == 1
        assert "INVOICE-98765" in doc.pages[0].text
        assert len(doc.pages[0].spans) > 0

        span = doc.pages[0].spans[0]
        assert "INVOICE" in span.text
        assert span.confidence is not None
        assert 0.0 <= span.confidence <= 1.0

        # Factual overall confidence
        assert res.confidence is not None
        assert res.confidence.method == "rapidocr_mean"
        assert res.confidence.evidence["engine"] == "rapidocr"
        assert res.confidence.evidence["backend"] == "openvino"
        assert res.confidence.evidence["model"] == "PP-OCRv5"

        # Provenance verification
        assert len(res.provenance) == 1
        prov = res.provenance[0]
        assert prov.source_input_id == "inp-img"
        assert prov.stage == "ocr"
        assert prov.capability_id == "ocr"
        assert prov.page_number == 1
        assert prov.evidence["engine"] == "rapidocr"
        assert prov.evidence["backend"] == "openvino"
        assert prov.evidence["model"] == "PP-OCRv5"
        assert prov.evidence["profile"] == "instant"
        assert prov.source_file is None

    def test_explicit_injected_data_root(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        canonical_src = Path(__file__).resolve().parents[2] / "data" / "ocr"
        custom_data_dir = tmp_path / "custom_data_root"
        shutil.copytree(canonical_src, custom_data_dir)

        cap = OCRCapability(data_root=custom_data_dir)

        img_path = tmp_path / "invoice_injected.png"
        _create_sample_image("INJECTED-ROOT-123", img_path)
        req = Request(
            request_id="req-inj",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-inj", source_path=img_path, display_name="invoice.png", size_bytes=img_path.stat().st_size),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        res = cap.execute(req, context)
        assert isinstance(res, Result)
        assert "INJECTED-ROOT-123" in res.data.pages[0].text

    def test_missing_local_model_asset_raises_safe_dosherror(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        empty_data_dir = tmp_path / "empty_ocr_data"
        empty_data_dir.mkdir()
        (empty_data_dir / "models").mkdir()
        manifest_file = empty_data_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps({
                "models": {
                    "det": {"filename": "ch_PP-OCRv5_det_mobile.onnx", "sha256": "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"},
                    "rec": {"filename": "ch_PP-OCRv5_rec_mobile.onnx", "sha256": "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5"},
                    "cls": {"filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"},
                }
            }),
            encoding="utf-8",
        )

        engine = RapidOCREngine(data_root=empty_data_dir)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-missing-model",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            with pytest.raises(DoshError) as exc_info:
                cap.execute(req, context)
            mock_rapidocr.assert_not_called()

        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "is missing" in err.message
        assert str(empty_data_dir) not in err.message

    def test_altered_model_checksum_is_rejected_before_engine_creation(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        src_data = Path(__file__).resolve().parents[2] / "data" / "ocr"
        tampered_data = tmp_path / "tampered_ocr_data"
        shutil.copytree(src_data, tampered_data)

        # Tamper with det model
        det_file = tampered_data / "models" / "ch_PP-OCRv5_det_mobile.onnx"
        det_file.write_bytes(b"tampered_corrupt_content")

        engine = RapidOCREngine(data_root=tampered_data)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-tampered-model",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            with pytest.raises(DoshError) as exc_info:
                cap.execute(req, context)
            mock_rapidocr.assert_not_called()

        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "invalid checksum" in err.message
        assert str(tampered_data) not in err.message

    def test_traversal_filename_in_manifest_rejected_safely(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "traversal_ocr_data"
        data_dir.mkdir()
        (data_dir / "models").mkdir()
        manifest_file = data_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps({
                "models": {
                    "det": {"filename": "../secret_file.onnx", "sha256": "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"},
                    "rec": {"filename": "ch_PP-OCRv5_rec_mobile.onnx", "sha256": "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5"},
                    "cls": {"filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"},
                }
            }),
            encoding="utf-8",
        )

        cap = OCRCapability(data_root=data_dir)
        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-trav",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, context)
        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "contains invalid model entry" in err.message
        assert "../secret_file.onnx" not in err.message
        assert str(data_dir) not in err.message

    def test_absolute_filename_in_manifest_rejected_safely(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "abs_ocr_data"
        data_dir.mkdir()
        (data_dir / "models").mkdir()
        manifest_file = data_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps({
                "models": {
                    "det": {"filename": "/etc/shadow.onnx", "sha256": "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"},
                    "rec": {"filename": "ch_PP-OCRv5_rec_mobile.onnx", "sha256": "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5"},
                    "cls": {"filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"},
                }
            }),
            encoding="utf-8",
        )

        cap = OCRCapability(data_root=data_dir)
        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-abs",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, context)
        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "contains invalid model entry" in err.message
        assert "/etc/shadow.onnx" not in err.message

    def test_invalid_checksum_format_in_manifest_rejected_safely(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "checksum_ocr_data"
        data_dir.mkdir()
        (data_dir / "models").mkdir()
        manifest_file = data_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps({
                "models": {
                    "det": {"filename": "ch_PP-OCRv5_det_mobile.onnx", "sha256": "INVALID_CHECKSUM_NOT_64_HEX"},
                    "rec": {"filename": "ch_PP-OCRv5_rec_mobile.onnx", "sha256": "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5"},
                    "cls": {"filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"},
                }
            }),
            encoding="utf-8",
        )

        cap = OCRCapability(data_root=data_dir)
        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-chk",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, context)
        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "contains invalid model entry" in err.message
        assert "INVALID_CHECKSUM_NOT_64_HEX" not in err.message

    def test_malformed_geometry_yields_factual_warning(
        self, ocr_capability: OCRCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        img_path = tmp_path / "test.png"
        _create_sample_image("GEOM-TEXT", img_path)

        req = Request(
            request_id="req-geom",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        # Mock engine output returning malformed box with fewer than 4 points
        mock_output = MagicMock()
        mock_output.txts = ("GEOM-TEXT",)
        mock_output.boxes = ([ [10.0, 10.0] ],) # Only 1 point instead of 4
        mock_output.scores = (0.95,)

        mock_rapidocr = MagicMock()
        mock_rapidocr.return_value = mock_output
        ocr_capability._engine._engine = mock_rapidocr

        res = ocr_capability.execute(req, context)
        assert res.next_requirement is None
        doc = res.data
        assert isinstance(doc, CanonicalDocument)
        assert len(doc.pages[0].spans) == 1
        assert doc.pages[0].spans[0].bounding_box is None
        assert any(w.code == "OCR_INVALID_GEOMETRY" for w in res.warnings)

    def test_real_scanned_pdf_ocr_execution(
        self, ocr_capability: OCRCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        pdf_path = tmp_path / "scanned_doc.pdf"
        _create_scanned_pdf("BALANCE-54321", pdf_path)

        req = Request(
            request_id="req-pdf",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-pdf",
                    source_path=pdf_path,
                    display_name="scanned_doc.pdf",
                    size_bytes=pdf_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        res = ocr_capability.execute(req, context)
        assert res.next_requirement is None

        doc = res.data
        assert isinstance(doc, CanonicalDocument)
        assert len(doc.pages) == 1
        assert "BALANCE-54321" in doc.pages[0].text

    def test_mixed_input_run_preserves_native_output_and_ocrs_scanned_input(
        self, ocr_capability: OCRCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        # Native readable doc already extracted by Shruti
        native_doc = CanonicalDocument(
            document_id="doc-native",
            source_input_id="inp-native",
            pages=(PageData(page_number=1, text="Native Statement Line"),),
            text="Native Statement Line",
            detected_type="pdf",
        )
        native_prov = ProvenanceRecord(
            source_input_id="inp-native",
            stage="read_native",
            plugin_id="shakti.native_extraction",
            capability_id="read_native",
            evidence={"reader": "pymupdf"},
        )
        prior_result = Result(
            data=(native_doc, CanonicalDocument(document_id="doc-scan", source_input_id="inp-scan")),
            provenance=(native_prov,),
            warnings=(),
            next_requirement="ocr",
        )

        scanned_pdf_path = tmp_path / "scan.pdf"
        _create_scanned_pdf("OCR-FILL-TEXT", scanned_pdf_path)

        dummy_native_path = tmp_path / "native.pdf"
        dummy_native_path.write_bytes(b"dummy")

        req = Request(
            request_id="req-mixed",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-native",
                    source_path=dummy_native_path,
                    display_name="native.pdf",
                    size_bytes=5,
                ),
                InputRef(
                    input_id="inp-scan",
                    source_path=scanned_pdf_path,
                    display_name="scan.pdf",
                    size_bytes=scanned_pdf_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        res = ocr_capability.execute(req, context, prior_result=prior_result)
        assert isinstance(res.data, tuple)
        assert len(res.data) == 2

        doc1, doc2 = res.data
        # Input 1: Native document was preserved unchanged
        assert doc1.source_input_id == "inp-native"
        assert doc1.text == "Native Statement Line"
        assert doc1.detected_type == "pdf"

        # Input 2: Scanned document was OCR filled
        assert doc2.source_input_id == "inp-scan"
        assert "OCR-FILL-TEXT" in doc2.pages[0].text
        assert doc2.detected_type == "ocr_document"

        # Provenances for both inputs are present
        prov_inputs = [p.source_input_id for p in res.provenance]
        assert "inp-native" in prov_inputs
        assert "inp-scan" in prov_inputs

    def test_unsupported_profiles_rejected_at_resolution_and_execution(
        self, ocr_capability: OCRCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)

        # 1. Kosh resolution rejection
        kosh = Kosh()
        kosh.register_plugin(OCR_PLUGIN)
        kosh.register_capability(OCR_DECLARATION)
        manthan = Manthan(kosh)

        accurate_req = Request(
            request_id="req-acc",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.ACCURATE,
        )

        with pytest.raises(DoshError) as exc_info:
            manthan.resolve(accurate_req)
        assert exc_info.value.code is FailureCode.UNSUPPORTED

        # 2. Direct capability execute rejection
        with pytest.raises(DoshError) as exc_info_exec:
            ocr_capability.execute(accurate_req, context)
        assert exc_info_exec.value.code is FailureCode.UNSUPPORTED

    def test_privacy_zero_raw_filesystem_path_leakage(
        self, ocr_capability: OCRCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        secret_dir = tmp_path / "confidential_ocr_data"
        secret_dir.mkdir()
        img_path = secret_dir / "secret_card.png"
        _create_sample_image("CARD-4321", img_path)
        raw_path_str = str(img_path)

        req = Request(
            request_id="req-priv",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-priv",
                    source_path=img_path,
                    display_name="secret_card.png",
                    size_bytes=img_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        res = ocr_capability.execute(req, context)
        for prov in res.provenance:
            assert prov.source_file is None
            assert raw_path_str not in str(prov.evidence)
            assert str(secret_dir) not in str(prov.evidence)

        # Verify missing file error does not leak path
        missing_req = Request(
            request_id="req-missing",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-missing",
                    source_path=secret_dir / "non_existent.png",
                    display_name="non_existent.png",
                    size_bytes=10,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )
        with pytest.raises(DoshError) as exc_info:
            ocr_capability.execute(missing_req, context)
        assert raw_path_str not in exc_info.value.message
        assert str(secret_dir) not in exc_info.value.message

    def test_unsupported_binary_content_returns_controlled_error(
        self, ocr_capability: OCRCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        bin_path = tmp_path / "data.bin"
        bin_path.write_bytes(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00")

        req = Request(
            request_id="req-bin",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-bin",
                    source_path=bin_path,
                    display_name="data.bin",
                    size_bytes=bin_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            ocr_capability.execute(req, context)
        assert exc_info.value.code is FailureCode.UNSUPPORTED

    def test_end_to_end_shruti_to_ocr_pipeline_flow(
        self, tmp_path: Path
    ) -> None:
        # Create a scanned PDF (no native text)
        scanned_path = tmp_path / "scanned_invoice.pdf"
        _create_scanned_pdf("TOTAL-DUE-9999", scanned_path)

        # Wire canonical Kosh, Manthan, Yantra, Pravaha
        kosh = Kosh()
        kosh.register_plugin(NATIVE_PLUGIN)
        kosh.register_capability(NATIVE_DECLARATION)
        kosh.register_plugin(OCR_PLUGIN)
        kosh.register_capability(OCR_DECLARATION)

        manthan = Manthan(kosh)
        inv = DeviceInventory([
            DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
        ])
        yantra = Yantra(inv)
        capabilities = {
            "read_native": NativeExtractionCapability(),
            "ocr": OCRCapability(),
        }
        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities=capabilities)

        req = Request(
            request_id="req-e2e",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-scan",
                    source_path=scanned_path,
                    display_name="scanned_invoice.pdf",
                    size_bytes=scanned_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )
        context = ExecutionContext(
            run_id="run-e2e",
            request_id="req-e2e",
            trace_id="tr-e2e",
            span_id="sp-e2e",
            profile=ExecutionProfile.INSTANT,
        )

        initial_plan = manthan.resolve(req)
        assert initial_plan.capability_ids == ("read_native",)

        # Execute pipeline: Shruti discovers no native text -> escalates to OCR -> Pravaha invokes OCR
        final_result = pravaha.execute(plan=initial_plan, request=req, context=context)

        assert isinstance(final_result, Result)
        assert final_result.next_requirement is None

        doc = final_result.data
        assert isinstance(doc, CanonicalDocument)
        assert doc.source_input_id == "inp-scan"
        assert "TOTAL-DUE-9999" in doc.pages[0].text

        # Verify provenance has both read_native and ocr stages
        stages = [p.stage for p in final_result.provenance]
        assert "read_native" in stages
        assert "ocr" in stages
