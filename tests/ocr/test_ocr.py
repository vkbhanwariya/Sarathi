"""Unit and end-to-end integration tests for OCR Phase 1 (Instant profile)."""

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pymupdf
import pytest
from PIL import Image, ImageDraw

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import Kosh, Manthan, Pravaha
from sarathi.sankalpa import (
    CanonicalDocument,
    CapabilityDeclaration,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
    TableData,
    TextSpan,
)
from sarathi.shakti.native_extraction import (
    CAPABILITY_DECLARATION as NATIVE_DECLARATION,
)
from sarathi.shakti.native_extraction import (
    PLUGIN_INFO as NATIVE_PLUGIN,
)
from sarathi.shakti.native_extraction import (
    NativeExtractionCapability,
)
from sarathi.shakti.ocr import (
    CAPABILITY_DECLARATION as OCR_DECLARATION,
)
from sarathi.shakti.ocr import (
    PLUGIN_INFO as OCR_PLUGIN,
)
from sarathi.shakti.ocr import (
    OCRCapability,
    RapidOCREngine,
)
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra

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


class DummyOutput:
    def __init__(self, txts=None, boxes=None, scores=None):
        self.txts = txts or []
        self.boxes = boxes or []
        self.scores = scores or []


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


class TestOCRDeclarations:
    def test_plugin_and_capability_declarations(self) -> None:
        assert OCR_PLUGIN.plugin_id == "shakti.ocr"
        assert "ocr" in OCR_PLUGIN.capabilities
        assert OCR_DECLARATION.capability_id == "ocr"
        assert OCR_DECLARATION.plugin_id == "shakti.ocr"
        assert OCR_DECLARATION.device_requirement.parallelizable is True
        assert OCR_DECLARATION.supported_profiles == (
            ExecutionProfile.INSTANT,
            ExecutionProfile.ACCURATE,
            ExecutionProfile.LAYOUT_PRESERVING,
            ExecutionProfile.CUSTOM,
        )

    @pytest.mark.real_model
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

        # Confirmed artifact payloads (default: clean output without .json)
        assert len(res.artifact_payloads) == 2
        names = [p.intent.name for p in res.artifact_payloads]
        assert "invoice_ocr.txt" in names
        assert "invoice_ocr.docx" in names
        assert "invoice_ocr.json" not in names
        txt_payload = next(p for p in res.artifact_payloads if p.intent.name == "invoice_ocr.txt")
        assert b"INVOICE-98765" in txt_payload.content
        assert res.confidence.evidence["model"] == "PP-OCRv5-Devanagari"

        # Explicit export_json=True produces .json as well
        req_with_json = Request(
            request_id="req-json",
            requirement="ocr",
            inputs=req.inputs,
            profile=req.profile,
            custom_options={"export_json": True},
        )
        res_with_json = ocr_capability.execute(req_with_json, context)
        assert len(res_with_json.artifact_payloads) == 3
        json_names = [p.intent.name for p in res_with_json.artifact_payloads]
        assert "invoice_ocr.json" in json_names

        # Provenance verification
        assert len(res.provenance) == 1
        prov = res.provenance[0]
        assert prov.source_input_id == "inp-img"
        assert prov.stage == "ocr"
        assert prov.capability_id == "ocr"
        assert prov.page_number == 1
        assert prov.evidence["engine"] == "rapidocr"
        assert prov.evidence["backend"] == "openvino"
        assert prov.evidence["model"] == "PP-OCRv5-Devanagari"
        assert prov.evidence["profile"] == "instant"
        assert prov.source_file is None

    @pytest.mark.real_model
    def test_explicit_injected_data_root(self, context: ExecutionContext, tmp_path: Path) -> None:
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
                InputRef(
                    input_id="inp-inj",
                    source_path=img_path,
                    display_name="invoice.png",
                    size_bytes=img_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        res = cap.execute(req, context)
        assert isinstance(res, Result)
        assert "INJECTED-ROOT-123" in res.data.pages[0].text

    def test_missing_manifest_file_raises_safe_dosherror(self, context: ExecutionContext, tmp_path: Path) -> None:
        empty_dir = tmp_path / "no_manifest_dir"
        empty_dir.mkdir()
        engine = RapidOCREngine(data_root=empty_dir)
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-no-manifest",
            requirement="ocr",
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, context)
        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "Required local OCR model manifest is missing." in err.message
        assert str(empty_dir) not in err.message

    def test_malformed_manifest_json_raises_safe_dosherror(self, context: ExecutionContext, tmp_path: Path) -> None:
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, context)
        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "Failed to read or parse local OCR model manifest." in err.message
        assert str(bad_json_dir) not in err.message

    def test_manifest_invalid_structure_raises_safe_dosherror(self, context: ExecutionContext, tmp_path: Path) -> None:
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, context)
        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "Local OCR model manifest has an invalid structure." in exc_info.value.message

    @pytest.mark.parametrize("missing_key", ["det", "rec_v6_en", "rec_devanagari", "cls"])
    def test_manifest_missing_individual_model_key_raises_safe_dosherror(
        self, missing_key: str, context: ExecutionContext, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / f"missing_key_{missing_key}"
        data_dir.mkdir()
        (data_dir / "models").mkdir()
        models = {
            "det": {
                "filename": "ch_PP-OCRv5_det_mobile.onnx",
                "sha256": "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae",
            },
            "rec_v6_en": {
                "filename": "PP-OCRv6_rec_small.onnx",
                "sha256": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
            },
            "rec_devanagari": {
                "filename": "devanagari_PP-OCRv5_rec_mobile.onnx",
                "sha256": "d6f0a906580e3fa6b324a318718f1f31f268b6ea8ef985f91c2012a37f52c91e",
            },
            "cls": {
                "filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
            },
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, context)
        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "is missing required model entry" in exc_info.value.message

    @pytest.mark.parametrize(
        ("missing_model", "custom_options"),
        [
            ("det", {}),
            ("rec_devanagari", {}),
            ("rec_v6_en", {"lang": "en"}),
            ("cls", {}),
        ],
    )
    def test_missing_each_model_file_individually_raises_safe_dosherror(
        self, missing_model: str, custom_options: dict[str, str] | None, context: ExecutionContext, tmp_path: Path
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.INSTANT,
            custom_options=custom_options,
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            with pytest.raises(DoshError) as exc_info:
                cap.execute(req, context)
            mock_rapidocr.assert_not_called()

        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "Required local OCR model asset is missing." in err.message
        assert str(partial_data) not in err.message

    def test_model_asset_is_directory_raises_safe_dosherror(self, context: ExecutionContext, tmp_path: Path) -> None:
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.INSTANT,
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            with pytest.raises(DoshError) as exc_info:
                cap.execute(req, context)
            mock_rapidocr.assert_not_called()

        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "not a regular file" in exc_info.value.message or "is missing" in exc_info.value.message
        assert str(dir_data) not in exc_info.value.message

    @pytest.mark.parametrize(
        ("tampered_model", "custom_options"),
        [
            ("det", {}),
            ("rec_devanagari", {}),
            ("rec_v6_en", {"lang": "en"}),
            ("cls", {}),
        ],
    )
    def test_tampered_model_checksum_for_all_models_raises_safe_dosherror(
        self, tampered_model: str, custom_options: dict[str, str] | None, context: ExecutionContext, tmp_path: Path
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.INSTANT,
            custom_options=custom_options,
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            with pytest.raises(DoshError) as exc_info:
                cap.execute(req, context)
            mock_rapidocr.assert_not_called()

        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "Local OCR model asset has invalid checksum." in err.message
        assert str(tampered_data) not in err.message

    @pytest.mark.parametrize(
        ("symlink_model", "custom_options"),
        [
            ("det", {}),
            ("rec_devanagari", {}),
            ("rec_v6_en", {"lang": "en"}),
            ("cls", {}),
        ],
    )
    def test_symlinked_model_asset_rejected_safely(
        self, symlink_model: str, custom_options: dict[str, str] | None, context: ExecutionContext, tmp_path: Path
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.INSTANT,
            custom_options=custom_options,
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            with pytest.raises(DoshError) as exc_info:
                cap.execute(req, context)
            mock_rapidocr.assert_not_called()

        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "not a regular file" in exc_info.value.message
        assert str(sym_data) not in exc_info.value.message
        assert str(outside_model) not in exc_info.value.message

    def test_symlinked_models_directory_rejected_safely(self, context: ExecutionContext, tmp_path: Path) -> None:
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.INSTANT,
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            with pytest.raises(DoshError) as exc_info:
                cap.execute(req, context)
            mock_rapidocr.assert_not_called()

        assert exc_info.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "invalid or a symlink" in exc_info.value.message
        assert str(sym_data) not in exc_info.value.message

    def test_symlinked_manifest_file_rejected_safely(self, context: ExecutionContext, tmp_path: Path) -> None:
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
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
            assert params["Rec.model_path"].endswith("devanagari_PP-OCRv5_rec_mobile.onnx")
            assert params["Cls.model_path"].endswith("ch_ppocr_mobile_v2.0_cls_mobile.onnx")

    def test_traversal_filename_in_manifest_rejected_safely(self, context: ExecutionContext, tmp_path: Path) -> None:
        data_dir = tmp_path / "traversal_ocr_data"
        data_dir.mkdir()
        (data_dir / "models").mkdir()
        manifest_file = data_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps(
                {
                    "models": {
                        "det": {
                            "filename": "../secret_file.onnx",
                            "sha256": "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae",
                        },
                        "rec_v6_en": {
                            "filename": "PP-OCRv6_rec_small.onnx",
                            "sha256": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
                        },
                        "rec_devanagari": {
                            "filename": "devanagari_PP-OCRv5_rec_mobile.onnx",
                            "sha256": "d6f0a906580e3fa6b324a318718f1f31f268b6ea8ef985f91c2012a37f52c91e",
                        },
                        "cls": {
                            "filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                            "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

        cap = OCRCapability(data_root=data_dir)
        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-trav",
            requirement="ocr",
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, context)
        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "contains invalid model entry" in err.message
        assert "../secret_file.onnx" not in err.message
        assert str(data_dir) not in err.message

    def test_absolute_filename_in_manifest_rejected_safely(self, context: ExecutionContext, tmp_path: Path) -> None:
        data_dir = tmp_path / "abs_ocr_data"
        data_dir.mkdir()
        (data_dir / "models").mkdir()
        manifest_file = data_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps(
                {
                    "models": {
                        "det": {
                            "filename": "/etc/shadow.onnx",
                            "sha256": "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae",
                        },
                        "rec_v6_en": {
                            "filename": "PP-OCRv6_rec_small.onnx",
                            "sha256": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
                        },
                        "rec_devanagari": {
                            "filename": "devanagari_PP-OCRv5_rec_mobile.onnx",
                            "sha256": "d6f0a906580e3fa6b324a318718f1f31f268b6ea8ef985f91c2012a37f52c91e",
                        },
                        "cls": {
                            "filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                            "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

        cap = OCRCapability(data_root=data_dir)
        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-abs",
            requirement="ocr",
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
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
            json.dumps(
                {
                    "models": {
                        "det": {"filename": "ch_PP-OCRv5_det_mobile.onnx", "sha256": "INVALID_CHECKSUM_NOT_64_HEX"},
                        "rec_v6_en": {
                            "filename": "PP-OCRv6_rec_small.onnx",
                            "sha256": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
                        },
                        "rec_devanagari": {
                            "filename": "devanagari_PP-OCRv5_rec_mobile.onnx",
                            "sha256": "d6f0a906580e3fa6b324a318718f1f31f268b6ea8ef985f91c2012a37f52c91e",
                        },
                        "cls": {
                            "filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                            "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

        cap = OCRCapability(data_root=data_dir)
        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)
        req = Request(
            request_id="req-chk",
            requirement="ocr",
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
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
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
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

    @pytest.mark.real_model
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

    @pytest.mark.real_model
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

    @pytest.mark.real_model
    def test_partial_native_document_preserves_extracted_pages_and_ocrs_remaining(
        self, ocr_capability: OCRCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        """R04 Fix: Partially extracted native document preserves native pages and runs OCR only on blank pages."""
        img_path = tmp_path / "p2.png"
        _create_sample_image("OCR-PAGE-TWO", img_path)

        pdf_path = tmp_path / "mixed_pages.pdf"
        doc = pymupdf.open()
        p1 = doc.new_page(width=300, height=200)
        p1.insert_text((50, 50), "Native Page One")

        img_doc = pymupdf.open(str(img_path))
        rect = img_doc[0].rect
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
        img_pdf = pymupdf.open("pdf", pdf_bytes)
        p2 = doc.new_page(width=rect.width, height=rect.height)
        p2.show_pdf_page(rect, img_pdf, 0)
        img_pdf.close()
        doc.save(str(pdf_path))
        doc.close()
        if img_path.exists():
            img_path.unlink()

        prior_doc = CanonicalDocument(
            document_id="doc-part",
            source_input_id="inp-part",
            detected_type="pdf",
            pages=(
                PageData(page_number=1, text="Native Page One"),
                PageData(page_number=2, text=""),
            ),
            text="Native Page One",
        )
        prior_prov = ProvenanceRecord(
            source_input_id="inp-part",
            stage="native_extraction",
            plugin_id="shakti.native_extraction",
            capability_id="read_native",
        )
        prior_result = Result(
            data=prior_doc,
            provenance=(prior_prov,),
            warnings=(),
            next_requirement="ocr",
        )

        req = Request(
            request_id="req-part",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-part",
                    source_path=pdf_path,
                    display_name="mixed_pages.pdf",
                    size_bytes=pdf_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        res = ocr_capability.execute(req, context, prior_result=prior_result)
        assert isinstance(res.data, CanonicalDocument)
        assert len(res.data.pages) == 2

        # Page 1 preserved native text
        assert res.data.pages[0].page_number == 1
        assert res.data.pages[0].text == "Native Page One"

        # Page 2 filled by OCR
        assert res.data.pages[1].page_number == 2
        assert any(tok in res.data.pages[1].text for tok in ("OCR-PAGE-TWO", "CCR-PAGE-TWO"))

    def test_unsupported_profiles_rejected_at_resolution_and_execution(
        self, ocr_capability: OCRCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        img_path = tmp_path / "test.png"
        _create_sample_image("TEXT", img_path)

        # 1. Kosh resolution rejection with restricted declaration
        restricted_decl = CapabilityDeclaration(
            capability_id="ocr",
            plugin_id="shakti.ocr",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        kosh = Kosh()
        kosh.register_plugin(OCR_PLUGIN)
        kosh.register_capability(restricted_decl)
        manthan = Manthan(kosh)

        accurate_req = Request(
            request_id="req-acc",
            requirement="ocr",
            inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=10),),
            profile=ExecutionProfile.ACCURATE,
        )

        with pytest.raises(DoshError) as exc_info:
            manthan.resolve(accurate_req)
        assert exc_info.value.code is FailureCode.UNSUPPORTED

        # 2. Direct capability execute rejection with restricted capability
        restricted_cap = OCRCapability(declaration=restricted_decl)
        with pytest.raises(DoshError) as exc_info_exec:
            restricted_cap.execute(accurate_req, context)
        assert exc_info_exec.value.code is FailureCode.UNSUPPORTED

    @pytest.mark.real_model
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

    @pytest.mark.real_model
    def test_end_to_end_shruti_to_ocr_pipeline_flow(self, tmp_path: Path) -> None:
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
        inv = DeviceInventory(
            [
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
            ]
        )
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

    def test_ocr_dependency_absence_reports_unavailable(self) -> None:
        """Verify that when an OCR dependency is absent, check_ocr_readiness reports unavailable."""
        from sarathi.shakti.ocr.engine.readiness import check_ocr_readiness

        with patch("importlib.util.find_spec", return_value=None):
            is_ready, reason = check_ocr_readiness()
            assert is_ready is False
            assert "Missing required OCR Python libraries" in reason

    def test_ocr_multi_page_demarcation_and_progress(self, context: ExecutionContext, tmp_path: Path) -> None:
        """Verify multi-page OCR creates page demarcations and invokes progress_callback."""
        engine = RapidOCREngine()
        cap = OCRCapability(engine=engine)

        pdf_path = tmp_path / "multi_ocr.pdf"
        import fitz

        doc = fitz.open()
        for i in range(2):
            page = doc.new_page()
            page.insert_text((50, 50), f"Page content {i + 1}")
        doc.save(str(pdf_path))
        doc.close()

        progress_calls = []

        def _on_prog(**kwargs: Any) -> None:
            progress_calls.append(kwargs)

        req = Request(
            request_id="req-multi-ocr",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-multi",
                    source_path=pdf_path,
                    display_name="multi_ocr.pdf",
                    size_bytes=pdf_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
            custom_options={"progress_callback": _on_prog},
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            mock_instance = MagicMock()
            mock_output = MagicMock()
            mock_output.txts = ("Sample Line",)
            mock_output.boxes = ([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],)
            mock_output.scores = (0.95,)
            mock_instance.return_value = mock_output
            mock_rapidocr.return_value = mock_instance

            res = cap.execute(req, context)
            assert isinstance(res, Result)
            assert isinstance(res.data, CanonicalDocument)
            # Demarcation check
            assert "--- Page 1 ---" in res.data.text
            assert "--- Page 2 ---" in res.data.text
            # Artifact check
            ocr_txt_payload = next(p for p in res.artifact_payloads if p.intent.name == "multi_ocr_ocr.txt")
            txt_str = ocr_txt_payload.content.decode("utf-8")
            assert "--- Page 1 ---" in txt_str
            assert "--- Page 2 ---" in txt_str
            # Progress calls check
            assert len(progress_calls) >= 2
            assert progress_calls[0]["page_number"] == 1
            assert progress_calls[0]["total_pages"] == 2
            assert progress_calls[1]["page_number"] == 2

    def test_ocr_accurate_mode_none_stdout_graceful_handling(self, context: ExecutionContext, tmp_path: Path) -> None:
        canonical_src = Path(__file__).resolve().parents[2] / "data" / "ocr"
        engine = RapidOCREngine(data_root=canonical_src, default_lang="hi")
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test_weak.png"
        _create_sample_image("कमजोर", img_path)

        req = Request(
            request_id="req-accurate",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-weak",
                    source_path=img_path,
                    display_name="test_weak.png",
                    size_bytes=img_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.ACCURATE,
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            mock_instance = MagicMock()
            mock_output = MagicMock()
            mock_output.txts = ("कमजोर",)
            mock_output.boxes = ([[0.0, 0.0], [50.0, 0.0], [50.0, 20.0], [0.0, 20.0]],)
            mock_output.scores = (0.50,)  # Weak confidence (< 0.65) triggers retry

            def side_effect(*args, **kwargs):
                if kwargs.get("use_det") is False:
                    # Retry recognizer fails unexpectedly
                    raise RuntimeError("Weak crop recognizer error")
                return mock_output

            mock_instance.side_effect = side_effect
            mock_rapidocr.return_value = mock_instance

            res = cap.execute(req, context)
            assert isinstance(res, Result)
            assert "कमजोर" in res.data.text

    def test_ocr_layout_preserving_profile_triggers_accurate_fallback(self, tmp_path: Path, monkeypatch) -> None:
        """Verify LAYOUT_PRESERVING profile triggers same-engine weak crop retry."""
        from sarathi.sankalpa import ExecutionProfile, InputRef, Request, Result
        from sarathi.shakti.ocr.capability import OCRCapability
        from sarathi.shakti.ocr.engine import RapidOCREngine

        context = ExecutionContext(
            run_id="test-run-lp",
            request_id="test-req-lp",
            trace_id="test-trace-lp",
            span_id="test-span-lp",
        )

        canonical_src = Path(__file__).resolve().parents[2] / "data" / "ocr"
        engine = RapidOCREngine(data_root=canonical_src, default_lang="hi")
        cap = OCRCapability(engine=engine)

        img_path = tmp_path / "test_lp.png"
        _create_sample_image("कमजोर", img_path)

        req = Request(
            request_id="req-lp",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-lp",
                    source_path=img_path,
                    display_name="test_lp.png",
                    size_bytes=img_path.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.LAYOUT_PRESERVING,
        )

        with patch("rapidocr.RapidOCR") as mock_rapidocr:
            mock_instance = MagicMock()
            mock_output = MagicMock()
            mock_output.txts = ("कमजोर",)
            mock_output.boxes = ([[0.0, 0.0], [50.0, 0.0], [50.0, 20.0], [0.0, 20.0]],)
            mock_output.scores = (0.50,)

            retry_output = MagicMock()
            retry_output.txts = ("सुधरा",)
            retry_output.scores = (0.92,)

            def side_effect(*args, **kwargs):
                if kwargs.get("use_det") is False:
                    return retry_output
                return mock_output

            mock_instance.side_effect = side_effect
            mock_rapidocr.return_value = mock_instance

            res = cap.execute(req, context)
            assert isinstance(res, Result)
            assert "सुधरा" in res.data.text


def test_recursive_xycut_multi_column_reading_order() -> None:
    """Proves XY-Cut partitions multi-column documents into natural reading order."""
    from sarathi.shakti.ocr.engine.parser import _parse_rapidocr_output

    class DummyOutput:
        pass

    out = DummyOutput()
    # Interleaved inputs (mimicking naive vertical scan across 2 columns + header at end)
    out.txts = ["Left Line 1", "Right Line 1", "Left Line 2", "Right Line 2", "DOCUMENT TITLE"]
    out.scores = [0.95, 0.94, 0.93, 0.92, 0.98]
    out.boxes = [
        [[50.0, 80.0], [240.0, 80.0], [240.0, 100.0], [50.0, 100.0]],  # Left Line 1
        [[280.0, 80.0], [480.0, 80.0], [480.0, 100.0], [280.0, 100.0]],  # Right Line 1
        [[50.0, 110.0], [240.0, 110.0], [240.0, 130.0], [50.0, 130.0]],  # Left Line 2
        [[280.0, 110.0], [480.0, 110.0], [480.0, 130.0], [280.0, 130.0]],  # Right Line 2
        [[50.0, 20.0], [480.0, 20.0], [480.0, 50.0], [50.0, 50.0]],  # DOCUMENT TITLE (top banner)
    ]

    lines, spans, scores, warnings, _, _ = _parse_rapidocr_output(out, filter_opt=False)

    expected_order = [
        "DOCUMENT TITLE",
        "Left Line 1",
        "Left Line 2",
        "Right Line 1",
        "Right Line 2",
    ]
    assert lines == expected_order
    assert [s.text for s in spans] == expected_order
    assert len(scores) == 5


def test_ocr_page_guarantees_use_det_true_after_crop_retry() -> None:
    """Proves engine.ocr_page always requests text detection (use_det=True) to prevent blank pages."""
    from unittest.mock import MagicMock

    from PIL import Image

    from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine

    engine = RapidOCREngine()
    mock_raw = MagicMock()
    mock_output = MagicMock()
    mock_output.txts = ["Detected text"]
    mock_output.scores = [0.95]
    mock_output.boxes = [[[0.0, 0.0], [50.0, 0.0], [50.0, 20.0], [0.0, 20.0]]]
    mock_raw.return_value = mock_output
    engine._engine = mock_raw

    # 1. Simulate a prior crop recognition that called engine with use_det=False
    mock_raw(Image.new("RGB", (50, 20)), use_det=False, use_cls=False)
    assert mock_raw.call_args[1].get("use_det") is False

    # 2. Call ocr_page on a full page image
    test_page = Image.new("RGB", (200, 300), color="white")
    page_data, _, _, _ = engine.ocr_page(test_page, page_number=1, input_id="test-input")

    # 3. Verify ocr_page explicitly passed use_det=True to prevent state pollution
    assert mock_raw.call_args[1].get("use_det") is True
    assert len(page_data.spans) == 1
    assert page_data.spans[0].text == "Detected text"


def test_ruled_table_ignores_isolated_header_footer_lines() -> None:
    """Proves detect_ruled_tables does not swallow body paragraphs between header/footer rules."""
    import numpy as np
    from PIL import Image, ImageDraw

    from sarathi.sankalpa import TextSpan
    from sarathi.shakti.ocr.engine.layout import detect_ruled_tables

    # Image with top line at y=30 and bottom line at y=800, but no vertical lines or table cells
    img = Image.new("RGB", (600, 900), color="white")
    draw = ImageDraw.Draw(img)
    draw.line([(50, 30), (550, 30)], fill="black", width=2)
    draw.line([(50, 800), (550, 800)], fill="black", width=2)
    arr = np.array(img)

    spans = [
        TextSpan(
            text=f"Paragraph body line {i}",
            bounding_box=(60.0, float(100 + i * 40), 500.0, float(120 + i * 40)),
            confidence=0.95,
        )
        for i in range(15)
    ]

    tables, consumed = detect_ruled_tables(arr, spans)
    assert len(tables) == 0, "Isolated header/footer divider lines must not be classified as a ruled table"
    assert len(consumed) == 0, "No body spans should be consumed by non-existent table"


def test_ocr_full_text_includes_tables_and_strips_markdown_headings(tmp_path: Path) -> None:
    """Proves OCR capability embeds tabular data in full_text and strips markdown hashes in plain text export."""
    from unittest.mock import MagicMock

    from PIL import Image

    tbl = TableData(name="Summary", headers=("Metric", "Value"), rows=(("Pages", "55"), ("Accuracy", "99%")))
    p1 = PageData(
        page_number=1,
        text="# Main Report Title\n## Section 1\nBody narrative line.",
        tables=(tbl,),
    )

    cap = OCRCapability()
    cap._engine = MagicMock()
    cap._engine.ocr_page.return_value = (
        p1,
        ProvenanceRecord(page_number=1, capability_id="ocr", evidence={"confidence": 0.95}),
        "dev",
        [],
    )

    img = Image.new("RGB", (100, 100), color="white")
    img_path = tmp_path / "test.png"
    img.save(img_path)

    req = Request(
        request_id="req-tbl-text",
        requirement="ocr",
        inputs=(
            InputRef(
                input_id="inp-1",
                source_path=img_path,
                display_name="test.png",
                size_bytes=img_path.stat().st_size,
                media_type="image/png",
            ),
        ),
        profile=ExecutionProfile.INSTANT,
    )
    ctx = ExecutionContext(request_id="req-tbl-text", run_id="run-1", trace_id="trace-1", span_id="span-1")
    res = cap.execute(req, ctx)

    # 1. CanonicalDocument text contains both narrative and serialized table
    doc = res.data if isinstance(res.data, CanonicalDocument) else res.data["documents"][0]
    assert "Main Report Title" in doc.text
    assert "Metric | Value" in doc.text
    assert "Pages | 55" in doc.text

    # 2. Plain text payload has markdown headers stripped
    txt_payload = next(p for p in res.artifact_payloads if p.intent.name.endswith(".txt"))
    txt_content = txt_payload.content.decode("utf-8")
    assert "# " not in txt_content
    assert "## " not in txt_content
    assert "Main Report Title" in txt_content
    assert "Metric | Value" in txt_content


def test_ocr_scanned_pdf_avoids_duplicate_native_provenance(tmp_path: Path) -> None:
    """Proves OCR capability does not append read_pdf provenance for scanned PDFs with zero usable native text."""
    from unittest.mock import MagicMock, patch

    cap = OCRCapability()
    cap._engine = MagicMock()

    # Create dummy 1-page scanned PDF
    doc = pymupdf.open()
    doc.new_page(width=300, height=400)
    pdf_path = tmp_path / "scanned.pdf"
    doc.save(str(pdf_path))
    doc.close()

    p_scanned = PageData(page_number=1, text="", metadata={"is_scanned_image": True})
    p_ocr = PageData(page_number=1, text="Scanned OCR Text", metadata={"confidence": 0.95})
    ocr_prov = ProvenanceRecord(page_number=1, capability_id="ocr", evidence={"confidence": 0.95})

    cap._engine.ocr_page.return_value = (p_ocr, ocr_prov, "en", [])

    with patch("sarathi.shakti.native_extraction.readers.pdf.read_pdf") as mock_read_pdf:
        # Mock read_pdf returning unusable scanned page and a native provenance record
        native_prov = ProvenanceRecord(page_number=1, capability_id="read_native", evidence={"confidence": 1.0})
        mock_read_pdf.return_value = (
            CanonicalDocument(document_id="doc-native", pages=(p_scanned,)),
            (native_prov,),
            [],
        )

        req = Request(
            request_id="req-scanned-prov",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-scanned",
                    source_path=pdf_path,
                    display_name="scanned.pdf",
                    size_bytes=pdf_path.stat().st_size,
                    media_type="application/pdf",
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )
        ctx = ExecutionContext(request_id="req-scanned-prov", run_id="run-1", trace_id="trace-1", span_id="span-1")
        res = cap.execute(req, ctx)

        # Provenance must only contain ocr, NEVER read_native
        caps = [pr.capability_id for pr in res.provenance]
        assert "read_native" not in caps
        assert "ocr" in caps


def test_ocr_missing_confidence_remains_none_without_085_fallback() -> None:
    """Proves record_ocr_page_telemetry does not substitute 0.85 when spans have no confidence."""
    from sarathi.darpana import Darpana
    from sarathi.shakti.ocr.telemetry import record_ocr_page_telemetry

    darpana = Darpana(capacity=50)
    ctx = ExecutionContext("run-ocr-truth", "req-ocr-truth", "t-ocr", "s-ocr")
    inp = InputRef("inp-ocr-1", Path("page.png"), "page.png", 1024)

    page_data = PageData(
        page_number=1,
        text="unmeasured text line",
        spans=(
            TextSpan(text="unmeasured", confidence=None),
            TextSpan(text="text", confidence=None),
        ),
    )

    record_ocr_page_telemetry(
        darpana=darpana,
        context=ctx,
        inp_ref=inp,
        page_idx=1,
        page_data=page_data,
        dur_ns=25_000_000,
        binding=None,
        worker_id="cpu-worker-0",
    )

    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    assert len(pramana_recs) > 0

    page_rec = next(r for r in pramana_recs if r.attributes.get("level") == "page")
    assert page_rec.confidence is None, f"Expected page confidence=None but got {page_rec.confidence}"
    assert page_rec.attributes.get("min_confidence") is None
    assert page_rec.attributes.get("max_confidence") is None

    region_recs = [r for r in pramana_recs if r.attributes.get("level") == "region"]
    for rrec in region_recs:
        assert rrec.confidence is None, f"Expected region confidence=None but got {rrec.confidence}"


def test_ocr_valid_confidence_propagates_faithfully() -> None:
    """Proves valid measured scores propagate accurately with score_kind='raw_engine'."""
    from sarathi.darpana import Darpana
    from sarathi.shakti.ocr.telemetry import record_ocr_page_telemetry

    darpana = Darpana(capacity=50)
    ctx = ExecutionContext("run-ocr-valid", "req-ocr-valid", "t-ocr", "s-ocr")
    inp = InputRef("inp-ocr-2", Path("page2.png"), "page2.png", 1024)

    page_data = PageData(
        page_number=1,
        text="first line\nsecond line",
        spans=(
            TextSpan(text="first line", confidence=0.92),
            TextSpan(text="second line", confidence=0.88),
        ),
    )

    record_ocr_page_telemetry(
        darpana=darpana,
        context=ctx,
        inp_ref=inp,
        page_idx=1,
        page_data=page_data,
        dur_ns=30_000_000,
        binding=None,
        worker_id="cpu-worker-0",
    )

    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    page_rec = next(r for r in pramana_recs if r.attributes.get("level") == "page")
    assert page_rec.confidence is not None
    assert page_rec.confidence.score == 0.9
    assert page_rec.confidence.evidence.get("score_kind") == "raw_engine"
    assert page_rec.confidence.evidence.get("calibrated") is False
    assert page_rec.attributes.get("min_confidence") == 0.88
    assert page_rec.attributes.get("max_confidence") == 0.92


def test_ne_ocr_fallback_preserves_independent_scores_and_raw_delta() -> None:
    """Proves fallback telemetry records raw_confidence_score_delta and preserves source/replacement scores."""
    from sarathi.darpana import Darpana
    from sarathi.shakti.ocr.telemetry import record_ocr_page_telemetry

    darpana = Darpana(capacity=50)
    ctx = ExecutionContext("run-ocr-fb", "req-ocr-fb", "t-ocr", "s-ocr")
    inp = InputRef("inp-ocr-3", Path("page3.png"), "page3.png", 1024)

    fallback_span = TextSpan(
        text="recovered text",
        confidence=0.89,
        metadata={
            "fallback_applied": True,
            "fallback_engine": "ne_ocr",
            "original_confidence": 0.42,
            "replacement_confidence": 0.89,
            "raw_confidence_score_delta": 0.47,
            "confidence_gain": 0.47,
        },
    )

    page_data = PageData(
        page_number=1,
        text="recovered text",
        spans=(fallback_span,),
        metadata={
            "fallback_applied": True,
            "fallback_engine": "ne_ocr",
            "fallback_improved_count": 1,
            "raw_confidence_score_delta": 0.47,
            "fallback_total_gain": 0.47,
        },
    )

    record_ocr_page_telemetry(
        darpana=darpana,
        context=ctx,
        inp_ref=inp,
        page_idx=1,
        page_data=page_data,
        dur_ns=40_000_000,
        binding=None,
        worker_id="cpu-worker-0",
    )

    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    reg_rec = next(r for r in pramana_recs if r.attributes.get("level") == "region")

    assert reg_rec.attributes.get("original_confidence") == 0.42
    assert reg_rec.attributes.get("replacement_confidence") == 0.89
    assert reg_rec.attributes.get("raw_confidence_score_delta") == 0.47
    assert reg_rec.confidence is not None
    assert reg_rec.confidence.evidence.get("original_confidence") == 0.42
    assert reg_rec.confidence.evidence.get("replacement_confidence") == 0.89
    assert reg_rec.confidence.evidence.get("raw_confidence_score_delta") == 0.47


def test_instant_profile_never_invokes_fallback() -> None:
    """Instant profile must never invoke retry, even for low-confidence spans."""
    import io

    from PIL import Image

    from sarathi.shakti.ocr.engine import RapidOCREngine

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

    doc = res.data if isinstance(res.data, CanonicalDocument) else res.data[0]
    page = doc.pages[0]
    assert not retry_invoked
    assert page.text == "राज"
    assert page.metadata["validation_outcome"] != "retry_improved"


def test_instant_page_does_not_materialize_unused_fallback_image() -> None:
    """Instant OCR must not allocate a PIL fallback crop image that cannot be used."""
    from PIL import Image

    from sarathi.shakti.ocr.engine import RapidOCREngine

    engine = RapidOCREngine()
    engine._engine = lambda _arr, **_kwargs: DummyOutput(
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
    from PIL import Image

    from sarathi.shakti.ocr.engine import RapidOCREngine

    engine = RapidOCREngine()
    engine._engine = lambda _arr, **_kwargs: DummyOutput(
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
    from PIL import Image

    from sarathi.shakti.ocr.engine import RapidOCREngine

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
    assert crops_seen[0].shape[1] == 106
    assert crops_seen[0].shape[0] == 46
    assert prov.evidence["validation_outcome"] == "retry_improved"
    assert prov.evidence["retry_applied"] is True


def test_custom_profile_rebuilds_all_evidence_on_binarize_pass() -> None:
    """When Custom binarize runs, text, spans, boxes, confidence, warnings, and evidence are rebuilt together."""
    import numpy as np
    from PIL import Image

    from sarathi.shakti.ocr.engine import RapidOCREngine

    engine = RapidOCREngine()

    def fake_rapidocr(arr, **_kwargs):
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
    from sarathi.dosh import DoshError, FailureCode
    from sarathi.shakti.ocr.engine import RapidOCREngine

    engine = RapidOCREngine()
    cap = OCRCapability(engine=engine)
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1")
    inp = InputRef("inp-1", Path("dummy.png"), "dummy.png", 10)

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


def test_check_ocr_readiness_validates_truthfully() -> None:
    """check_ocr_readiness must verify dependencies, manifest, and model checksums safely."""
    from sarathi.shakti.ocr import check_ocr_readiness

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
    import threading
    import time

    from PIL import Image

    from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra

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
        inputs.append(
            InputRef(
                input_id=f"i-{idx + 1}", source_path=p, display_name=f"img_{idx + 1}.png", size_bytes=p.stat().st_size
            )
        )

    binding = ExecutionBinding("cpu-0", DeviceType.CPU, "cpu", "CPU", approved_concurrency=2)
    ctx = ExecutionContext("run-c", "req-c", "t-c", "s-c", execution_binding=binding)
    req = Request("req-c", "ocr", inputs=tuple(inputs))

    res = cap.execute(req, ctx)

    assert isinstance(res.data, tuple)
    assert len(res.data) == 4
    for idx, doc in enumerate(res.data):
        assert doc.source_input_id == f"i-{idx + 1}"
        assert f"Text for i-{idx + 1}" in doc.text

    assert max_active > 1, f"Expected concurrency > 1, got {max_active}"
    assert max_active <= 2, f"Expected concurrency <= 2, got {max_active}"


def test_ocr_page_validation_enabled_option() -> None:
    """Verify validation_enabled=False sets validation_outcome to 'skipped'."""
    from PIL import Image

    from sarathi.shakti.ocr.engine import RapidOCREngine

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
    import io

    from sarathi.dosh import DoshError, FailureCode

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


def test_json_export_preserves_metadata_and_tables() -> None:
    """Verify JSON export artifact preserves span metadata, language, script, and tables."""
    import json

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
        custom_options={"export_json": True},
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


def test_default_ocr_omits_json_artifact_for_clean_output() -> None:
    """Verify default OCR execution omits ocr.json, leaving clean .docx and .txt outputs."""
    p = PageData(page_number=1, text="Simple OCR line", spans=(), tables=())
    req = Request(
        "req-clean",
        "ocr",
        inputs=(InputRef("in-1", Path("test.png"), "image/png", 100),),
        profile=ExecutionProfile.INSTANT,
    )
    ctx = ExecutionContext("run-clean", "req-clean", "t1", "s1")

    mock_engine = MagicMock()
    mock_engine.ocr_page.return_value = (p, None, None, ())
    cap = OCRCapability(engine=mock_engine)

    with patch.object(Path, "read_bytes", return_value=b"fake_image_bytes"):
        with patch("sarathi.shakti.ocr.capability.iter_images_from_bytes", return_value=[MagicMock()]):
            with patch("sarathi.shakti.ocr.capability.get_page_count_from_bytes", return_value=1):
                res = cap.execute(req, ctx)

    payload_names = [pl.intent.name for pl in res.artifact_payloads]
    assert any(n.endswith(".docx") for n in payload_names)
    assert any(n.endswith(".txt") for n in payload_names)
    assert not any(n.endswith(".json") for n in payload_names)


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


def test_bug_T3_type_error_cascades_ocr() -> None:
    """T3: Fake OCR engine raising TypeError in __call__ must not be called a second time."""
    from PIL import Image

    from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine

    call_count = 0

    def buggy_call(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        raise TypeError("internal engine failure")

    mock_runner = MagicMock()
    mock_runner.side_effect = buggy_call

    engine = RapidOCREngine()
    engine._get_engine = MagicMock(return_value=mock_runner)

    img = Image.new("RGB", (100, 100), color="white")
    with pytest.raises(TypeError, match="internal engine failure"):
        engine.ocr_page(img, page_number=1, input_id="in-1")

    assert call_count == 1, f"Expected active_engine to be called exactly once, but was called {call_count} times"


def test_devanagari_digit_normalization() -> None:
    """Verify Devanagari numerals are normalized to ASCII/Arabic digits by default and preserved when opted out."""
    from types import SimpleNamespace

    from PIL import Image

    from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine
    from sarathi.shakti.ocr.engine.parser import _parse_rapidocr_output
    from sarathi.shakti.text.typography import normalize_devanagari_numerals

    # 1. Direct typography primitive
    assert normalize_devanagari_numerals("०१२३४५६७८९") == "0123456789"
    assert normalize_devanagari_numerals("पृष्ठ २३ (वर्ष २०२६)") == "पृष्ठ 23 (वर्ष 2026)"
    assert normalize_devanagari_numerals("English 123 unaffected") == "English 123 unaffected"
    assert normalize_devanagari_numerals("") == ""
    assert normalize_devanagari_numerals(None) == ""

    # 2. Output parser behavior
    fake_out = SimpleNamespace(
        txts=["पृष्ठ २३", "मूल्य रु ५००"],
        boxes=[[[0, 0], [10, 0], [10, 10], [0, 10]], [[0, 20], [10, 20], [10, 30], [0, 30]]],
        scores=[0.95, 0.90],
    )
    # Default (normalize_digits=True, filter_opt=False)
    lines, spans, _, _, _, _ = _parse_rapidocr_output(fake_out, filter_opt=False, normalize_digits=True)
    assert lines == ["पृष्ठ 23", "मूल्य रु 500"]
    assert spans[0].text == "पृष्ठ 23"
    assert spans[1].text == "मूल्य रु 500"

    # Opt-out (normalize_digits=False)
    lines_raw, spans_raw, _, _, _, _ = _parse_rapidocr_output(fake_out, filter_opt=False, normalize_digits=False)
    assert lines_raw == ["पृष्ठ २३", "मूल्य रु ५००"]
    assert spans_raw[0].text == "पृष्ठ २३"
    assert spans_raw[1].text == "मूल्य रु ५००"

    # 3. Coordinator end-to-end page test
    engine = RapidOCREngine()
    mock_runner = MagicMock()
    mock_runner.return_value = fake_out
    engine._get_engine = MagicMock(return_value=mock_runner)

    img = Image.new("RGB", (100, 100), color="white")
    # Default: normalized
    page_data, _, _, _ = engine.ocr_page(img, 1, "inp-1", profile=ExecutionProfile.ACCURATE)
    assert "पृष्ठ 23" in page_data.text
    assert "मूल्य रु 500" in page_data.text

    # Opt-out: preserved
    page_data_opt_out, _, _, _ = engine.ocr_page(
        img, 1, "inp-1", profile=ExecutionProfile.CUSTOM, custom_options={"normalize_digits": False}
    )
    assert "पृष्ठ २३" in page_data_opt_out.text
    assert "मूल्य रु ५००" in page_data_opt_out.text


def test_ocr_capability_normalize_digits_custom_option(context: ExecutionContext, tmp_path: Path) -> None:
    """Verify OCRCapability validates normalize_digits in CUSTOM profile."""
    from PIL import Image

    from sarathi.shakti.ocr.capability import OCRCapability

    img_path = tmp_path / "test.png"
    Image.new("RGB", (10, 10), color="white").save(img_path)

    cap = OCRCapability()

    # Invalid non-boolean value rejected with FailureCode.VALIDATION_FAILED
    req_invalid = Request(
        request_id="req-invalid-norm",
        requirement="ocr",
        inputs=(InputRef(input_id="in-1", source_path=img_path, display_name="test.png", size_bytes=100),),
        profile=ExecutionProfile.CUSTOM,
        custom_options={"normalize_digits": "not-a-bool"},
    )
    with pytest.raises(DoshError) as exc_info:
        cap.execute(req_invalid, context)
    assert exc_info.value.code is FailureCode.VALIDATION_FAILED
    assert "normalize_digits" in exc_info.value.message
