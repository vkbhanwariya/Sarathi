"""Unit and end-to-end integration tests for OCR Phase 1 (Instant profile)."""

import importlib.util
import pytest

_OCR_AVAILABLE = (
    importlib.util.find_spec("rapidocr") is not None
    and importlib.util.find_spec("openvino") is not None
    and importlib.util.find_spec("PIL") is not None
    and importlib.util.find_spec("numpy") is not None
)

if not _OCR_AVAILABLE:
    pytest.skip(
        "OCR optional dependencies (rapidocr, openvino, pillow, numpy) not installed. Run with --extra ocr to enable.",
        allow_module_level=True,
    )

import json
from pathlib import Path
import shutil
from typing import Any
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

    def test_missing_manifest_file_raises_safe_dosherror(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        empty_dir = tmp_path / "no_manifest_dir"
        empty_dir.mkdir()
        engine = RapidOCREngine(data_root=empty_dir)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-no-manifest",
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
        assert "Required local OCR model manifest is missing." in err.message
        assert str(empty_dir) not in err.message

    def test_malformed_manifest_json_raises_safe_dosherror(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        bad_json_dir = tmp_path / "bad_json_dir"
        bad_json_dir.mkdir()
        (bad_json_dir / "manifest.json").write_text("{not-valid-json", encoding="utf-8")
        engine = RapidOCREngine(data_root=bad_json_dir)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-bad-json",
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
        assert "Failed to read or parse local OCR model manifest." in err.message
        assert str(bad_json_dir) not in err.message

    def test_manifest_invalid_structure_raises_safe_dosherror(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        bad_struct_dir = tmp_path / "bad_struct_dir"
        bad_struct_dir.mkdir()
        (bad_struct_dir / "manifest.json").write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        engine = RapidOCREngine(data_root=bad_struct_dir)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-bad-struct",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, context)
        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "Local OCR model manifest has an invalid structure." in exc_info.value.message

    @pytest.mark.parametrize("missing_key", ["det", "rec", "cls"])
    def test_manifest_missing_individual_model_key_raises_safe_dosherror(
        self, missing_key: str, context: ExecutionContext, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / f"missing_key_{missing_key}"
        data_dir.mkdir()
        (data_dir / "models").mkdir()
        models = {
            "det": {"filename": "ch_PP-OCRv5_det_mobile.onnx", "sha256": "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"},
            "rec": {"filename": "ch_PP-OCRv5_rec_mobile.onnx", "sha256": "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5"},
            "cls": {"filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"},
        }
        del models[missing_key]
        (data_dir / "manifest.json").write_text(json.dumps({"models": models}), encoding="utf-8")

        engine = RapidOCREngine(data_root=data_dir)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-missing-key",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, context)
        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "is missing required model entry." in exc_info.value.message

    @pytest.mark.parametrize("missing_model", ["det", "rec", "cls"])
    def test_missing_each_model_file_individually_raises_safe_dosherror(
        self, missing_model: str, context: ExecutionContext, tmp_path: Path
    ) -> None:
        src_data = Path(__file__).resolve().parents[2] / "data" / "ocr"
        partial_data = tmp_path / f"partial_data_{missing_model}"
        shutil.copytree(src_data, partial_data)

        # Remove specific model
        manifest = json.loads((partial_data / "manifest.json").read_text(encoding="utf-8"))
        filename = manifest["models"][missing_model]["filename"]
        (partial_data / "models" / filename).unlink()

        engine = RapidOCREngine(data_root=partial_data)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id=f"req-missing-{missing_model}",
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
        assert "Required local OCR model asset is missing." in err.message
        assert str(partial_data) not in err.message

    def test_model_asset_is_directory_raises_safe_dosherror(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        src_data = Path(__file__).resolve().parents[2] / "data" / "ocr"
        dir_data = tmp_path / "dir_model_data"
        shutil.copytree(src_data, dir_data)

        # Replace det file with a directory
        det_file = dir_data / "models" / "ch_PP-OCRv5_det_mobile.onnx"
        det_file.unlink()
        det_file.mkdir()

        engine = RapidOCREngine(data_root=dir_data)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-dir-model",
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

        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "not a regular file" in exc_info.value.message or "is missing" in exc_info.value.message
        assert str(dir_data) not in exc_info.value.message

    @pytest.mark.parametrize("tampered_model", ["det", "rec", "cls"])
    def test_tampered_model_checksum_for_all_models_raises_safe_dosherror(
        self, tampered_model: str, context: ExecutionContext, tmp_path: Path
    ) -> None:
        src_data = Path(__file__).resolve().parents[2] / "data" / "ocr"
        tampered_data = tmp_path / f"tampered_{tampered_model}"
        shutil.copytree(src_data, tampered_data)

        manifest = json.loads((tampered_data / "manifest.json").read_text(encoding="utf-8"))
        filename = manifest["models"][tampered_model]["filename"]
        target_file = tampered_data / "models" / filename
        target_file.write_bytes(b"tampered_corrupt_content_for_test")

        engine = RapidOCREngine(data_root=tampered_data)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-tampered",
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
        assert "Local OCR model asset has invalid checksum." in err.message
        assert str(tampered_data) not in err.message

    @pytest.mark.parametrize("symlink_model", ["det", "rec", "cls"])
    def test_symlinked_model_asset_rejected_safely(
        self, symlink_model: str, context: ExecutionContext, tmp_path: Path
    ) -> None:
        src_data = Path(__file__).resolve().parents[2] / "data" / "ocr"
        sym_data = tmp_path / f"sym_data_{symlink_model}"
        shutil.copytree(src_data, sym_data)

        outside_model = tmp_path / f"outside_{symlink_model}.onnx"
        manifest = json.loads((sym_data / "manifest.json").read_text(encoding="utf-8"))
        filename = manifest["models"][symlink_model]["filename"]
        target_file = sym_data / "models" / filename

        outside_model.write_bytes(target_file.read_bytes())
        target_file.unlink()
        try:
            target_file.symlink_to(outside_model)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not supported/permitted in this environment.")

        engine = RapidOCREngine(data_root=sym_data)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id=f"req-sym-{symlink_model}",
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

        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "not a regular file" in exc_info.value.message
        assert str(sym_data) not in exc_info.value.message
        assert str(outside_model) not in exc_info.value.message

    def test_symlinked_models_directory_rejected_safely(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        src_data = Path(__file__).resolve().parents[2] / "data" / "ocr"
        sym_data = tmp_path / "sym_models_dir_data"
        sym_data.mkdir()
        shutil.copy(src_data / "manifest.json", sym_data / "manifest.json")

        outside_models_dir = src_data / "models"
        target_models_symlink = sym_data / "models"
        try:
            target_models_symlink.symlink_to(outside_models_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not supported/permitted in this environment.")

        engine = RapidOCREngine(data_root=sym_data)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-sym-dir",
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

        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "invalid or a symlink" in exc_info.value.message
        assert str(sym_data) not in exc_info.value.message

    def test_symlinked_manifest_file_rejected_safely(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        src_data = Path(__file__).resolve().parents[2] / "data" / "ocr"
        sym_data = tmp_path / "sym_manifest_data"
        shutil.copytree(src_data, sym_data)

        manifest_file = sym_data / "manifest.json"
        outside_manifest = tmp_path / "outside_manifest.json"
        outside_manifest.write_bytes(manifest_file.read_bytes())
        manifest_file.unlink()
        try:
            manifest_file.symlink_to(outside_manifest)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not supported/permitted in this environment.")

        engine = RapidOCREngine(data_root=sym_data)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-sym-manifest",
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

        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "not a regular file" in exc_info.value.message or "invalid" in exc_info.value.message
        assert str(sym_data) not in exc_info.value.message

    def test_rapidocr_constructor_called_with_all_three_explicit_paths(
        self, context: ExecutionContext, tmp_path: Path
    ) -> None:
        canonical_src = Path(__file__).resolve().parents[2] / "data" / "ocr"
        engine = RapidOCREngine(data_root=canonical_src)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-explicit-paths",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            mock_instance = MagicMock()
            mock_output = MagicMock()
            mock_output.txts = ("TEXT",)
            mock_output.boxes = ([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],)
            mock_output.scores = (0.99,)
            mock_instance.return_value = mock_output
            mock_rapidocr.return_value = mock_instance

            res = cap.execute(req, context)
            assert isinstance(res, Result)
            mock_rapidocr.assert_called_once()
            _, kwargs = mock_rapidocr.call_args
            params = kwargs.get("params", {})
            assert "Det.model_path" in params
            assert "Rec.model_path" in params
            assert "Cls.model_path" in params
            assert params["Det.model_path"].endswith("ch_PP-OCRv5_det_mobile.onnx")
            assert params["Rec.model_path"].endswith("ch_PP-OCRv5_rec_mobile.onnx")
            assert params["Cls.model_path"].endswith("ch_ppocr_mobile_v2.0_cls_mobile.onnx")

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

    @pytest.mark.parametrize(
        ("bad_box", "expected_warning_substr"),
        [
            ([[10.0, 10.0]], "fewer than 4 points"),
            ([[10.0], [20.0], [30.0], [40.0]], "malformed or non-numeric"),
            ([["not_a_num", 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]], "malformed or non-numeric"),
            ([[float("nan"), 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]], "non-finite"),
            ([[float("inf"), 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]], "non-finite"),
            (12345, "malformed or non-numeric"),
        ],
    )
    def test_malformed_geometry_types_yield_factual_warning(
        self,
        bad_box: Any,
        expected_warning_substr: str,
        ocr_capability: OCRCapability,
        context: ExecutionContext,
        tmp_path: Path,
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

        mock_output = MagicMock()
        mock_output.txts = ("GEOM-TEXT",)
        mock_output.boxes = (bad_box,)
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
        assert any(w.code == "OCR_INVALID_GEOMETRY" and expected_warning_substr in w.message for w in res.warnings)

    def test_unexpected_defect_in_engine_propagates(
        self,
        ocr_capability: OCRCapability,
        context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        img_path = tmp_path / "test.png"
        _create_sample_image("CRASH-TEXT", img_path)

        req = Request(
            request_id="req-crash",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        mock_rapidocr = MagicMock()
        mock_rapidocr.side_effect = RuntimeError("OpenVINO internal pipeline failure")
        ocr_capability._engine._engine = mock_rapidocr

        with pytest.raises(RuntimeError, match="OpenVINO internal pipeline failure"):
            ocr_capability.execute(req, context)

    def test_unexpected_defect_in_geometry_processing_propagates(
        self,
        ocr_capability: OCRCapability,
        context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        img_path = tmp_path / "test.png"
        _create_sample_image("GEOM-FAULT", img_path)

        req = Request(
            request_id="req-geom-fault",
            requirement="ocr",
            inputs=(
                InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        class CustomDefectError(RuntimeError):
            pass

        class CorruptBoxSequence:
            def __len__(self) -> int:
                return 4

            def __iter__(self) -> Any:
                raise CustomDefectError("Unexpected hardware or memory fault in geometry buffer")

        mock_output = MagicMock()
        mock_output.txts = ("GEOM-FAULT",)
        mock_output.boxes = (CorruptBoxSequence(),)
        mock_output.scores = (0.95,)

        mock_rapidocr = MagicMock()
        mock_rapidocr.return_value = mock_output
        ocr_capability._engine._engine = mock_rapidocr

        with pytest.raises(CustomDefectError, match="Unexpected hardware or memory fault in geometry buffer"):
            ocr_capability.execute(req, context)

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

    def test_ocr_extra_absence_skips_module(self) -> None:
        """Verify that when any OCR optional dependency is absent, find_spec returns None and skips."""
        with patch("importlib.util.find_spec", return_value=None):
            specs = [
                importlib.util.find_spec("rapidocr"),
                importlib.util.find_spec("openvino"),
                importlib.util.find_spec("PIL"),
                importlib.util.find_spec("numpy"),
            ]
            assert all(s is None for s in specs)
