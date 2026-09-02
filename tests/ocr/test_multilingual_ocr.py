"""Focused tests for Multilingual OCR Routing (v5 Devanagari + v6 English) and Hardware Projections."""

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageDraw, ImageFont

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
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
    assert adapter._executable_path is not None
    assert adapter._executable_path.is_file()
    assert "tesseract.exe" in adapter._executable_path.name.lower()


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
