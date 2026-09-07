"""Focused tests for Multilingual OCR Routing (v5 Devanagari + v6 English) and Hardware Projections."""

import importlib.util
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
)
from sarathi.shakti.ocr.capability import OCRCapability
from sarathi.shakti.ocr.engine import RapidOCREngine, TesseractFallbackAdapter
from sarathi.yantra.devices import DeviceInventory, DeviceType

_OCR_AVAILABLE = bool(
    importlib.util.find_spec("rapidocr")
    and importlib.util.find_spec("openvino")
    and importlib.util.find_spec("PIL")
    and importlib.util.find_spec("numpy")
)

if not _OCR_AVAILABLE:
    pytest.skip(
        "Multilingual OCR tests require optional OCR dependencies (rapidocr, openvino, PIL, numpy).",
        allow_module_level=True,
    )


def _create_sample_image(text: str, path: Path) -> None:
    img = Image.new("RGB", (300, 80), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((10, 25), text, fill="black", font=font)
    img.save(path)


def test_tesseract_discovery_finds_installed_executable() -> None:
    """Proves TesseractFallbackAdapter successfully discovers installed Tesseract in user programs."""
    adapter = TesseractFallbackAdapter()
    assert adapter.is_available() is True
    assert adapter.executable_path is not None
    assert adapter.executable_path.is_file()
    assert "tesseract.exe" in adapter.executable_path.name.lower()
    if adapter.tessdata_dir is not None:
        assert adapter.tessdata_dir.is_dir()


def test_pytesseract_auto_configured_and_functional() -> None:
    """Proves pytesseract is automatically configured with the resolved binary and operational."""
    import pytesseract

    from sarathi.shakti.ocr import configure_pytesseract

    success = configure_pytesseract()
    assert success is True
    assert pytesseract.pytesseract.tesseract_cmd is not None
    assert Path(pytesseract.pytesseract.tesseract_cmd).is_file()

    version = pytesseract.get_tesseract_version()
    assert str(version).startswith("5.")
    langs = pytesseract.get_languages()
    assert "eng" in langs


def test_pytesseract_image_to_string_operational(tmp_path: Path) -> None:
    """Proves pytesseract executes real image_to_string OCR on a rendered image."""
    import pytesseract

    img_path = tmp_path / "tess_test.png"
    _create_sample_image("HELLO", img_path)

    text = pytesseract.image_to_string(Image.open(img_path))
    assert "HELLO" in text.upper()


def test_multilingual_devanagari_engine_routing(tmp_path: Path) -> None:
    """Proves RapidOCREngine routes to PP-OCRv5 Devanagari model and records factual evidence."""
    img_path = tmp_path / "hindi_sample.png"
    _create_sample_image("SAMPLE-TEXT", img_path)

    engine = RapidOCREngine()
    img = Image.open(img_path)
    page_data, prov, conf, warnings = engine.ocr_page(
        img,
        page_number=1,
        input_id="inp-hi",
        profile=ExecutionProfile.INSTANT,
        custom_options={"lang": "devanagari"},
    )

    assert prov.evidence.get("model") == "PP-OCRv5-Devanagari"
    assert "devanagari" in engine._engines


def test_multilingual_v6_english_engine_routing(tmp_path: Path) -> None:
    """Proves RapidOCREngine routes to PP-OCRv6 English model and records factual evidence."""
    img_path = tmp_path / "en_sample.png"
    _create_sample_image("SAMPLE-TEXT", img_path)

    engine = RapidOCREngine()
    img = Image.open(img_path)
    page_data, prov, conf, warnings = engine.ocr_page(
        img,
        page_number=1,
        input_id="inp-en",
        profile=ExecutionProfile.INSTANT,
        custom_options={"lang": "en_v6"},
    )

    assert prov.evidence.get("model") == "PP-OCRv6"
    assert "v6_en" in engine._engines


def test_capability_validates_unsupported_language(tmp_path: Path) -> None:
    """Proves OCRCapability rejects unrecognized custom_options language."""
    img_path = tmp_path / "sample.png"
    _create_sample_image("TEXT", img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-val", "req-val", "tr-val", "sp-val")
    req = Request(
        request_id="req-val",
        requirement="ocr",
        inputs=(InputRef("inp-val", img_path, "sample.png", 100),),
        profile=ExecutionProfile.INSTANT,
        custom_options={"lang": "klingon_v99"},
    )

    with pytest.raises(DoshError) as exc_info:
        cap.execute(req, ctx)
    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "Requested OCR language" in exc_info.value.message


def test_device_inventory_default_vs_detect_accelerators() -> None:
    """Proves DeviceInventory preserves CPU-only default while detect_accelerators factually probes."""
    default_inv = DeviceInventory.default_inventory()
    assert len(default_inv) == 1
    assert default_inv.get_device("cpu-0") is not None

    probed_inv = DeviceInventory.default_inventory(detect_accelerators=True)
    assert len(probed_inv) >= 1
    assert probed_inv.get_device("cpu-0") is not None
    # If openvino detected GPU or NPU, verify device types
    for dev in probed_inv.devices:
        assert dev.device_type in (DeviceType.CPU, DeviceType.GPU, DeviceType.NPU)


def test_multilingual_ocr_preserves_mixed_hindi_tokens() -> None:
    """Verify default OCR parser does not drop Devanagari tokens in mixed-script documents."""
    from sarathi.shakti.ocr.engine.coordinator import _parse_rapidocr_output

    class MockRapidOutput:
        txts = ["Invoice #12345", "दिनांक: 15/08/2024", "कुल राशि: ₹ 45,250/-", "Approved by Manager"]
        boxes = [[10, 10, 100, 20], [10, 30, 100, 40], [10, 50, 100, 60], [10, 70, 100, 80]]
        scores = [0.95, 0.92, 0.90, 0.88]

    # With filter_opt=False (new default for general OCR)
    lines, spans, confs, warns, _, _ = _parse_rapidocr_output(MockRapidOutput(), filter_opt=False)
    assert len(lines) == 4
    assert any("दिनांक" in line for line in lines)
    assert any("कुल राशि" in line for line in lines)
    assert any("₹ 45,250/-" in line for line in lines)
