"""Tests for PP-OCRv6 Locking and English Font & Numbers Only Filtering."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from sarathi.sankalpa import ExecutionProfile
from sarathi.shakti.ocr.engine import (
    RapidOCREngine,
    filter_english_and_numbers,
)

_OCR_AVAILABLE = bool(
    importlib.util.find_spec("rapidocr")
    and importlib.util.find_spec("openvino")
    and importlib.util.find_spec("PIL")
    and importlib.util.find_spec("numpy")
)

if not _OCR_AVAILABLE:
    pytest.skip(
        "Tests require optional OCR dependencies (rapidocr, openvino, PIL, numpy).",
        allow_module_level=True,
    )


def test_filter_english_and_numbers_unit() -> None:
    """Verify filter_english_and_numbers isolates English alphanumeric tokens and drops noise/Devanagari."""
    # 1. Standard English words & digits
    assert filter_english_and_numbers("Invoice 12345") == "Invoice 12345"
    assert filter_english_and_numbers("A/c No: 9876543210") == "A/c No: 9876543210"
    assert filter_english_and_numbers("Date: 15/08/2026") == "Date: 15/08/2026"
    assert filter_english_and_numbers("Amount: ₹ 25,000.00") == "Amount: ₹ 25,000.00"

    # 2. Pure Devanagari / non-Latin text must be dropped completely
    assert filter_english_and_numbers("भारतीय रिजर्व बैंक") == ""
    assert filter_english_and_numbers("न्यायालय आदेश") == ""

    # 3. Pure noise without alphanumeric letters or numbers must be dropped
    assert filter_english_and_numbers("--- ... === ~~~") == ""
    assert filter_english_and_numbers("   ") == ""

    # 4. Mixed text keeps English and numbers
    assert filter_english_and_numbers("Branch शाखा 001") == "Branch 001"


def test_ocr_engine_routes_to_ppocrv6(tmp_path: Path) -> None:
    """Verify RapidOCREngine routes to PP-OCRv6 model when configured."""
    img_path = tmp_path / "sample.png"
    img = Image.new("RGB", (200, 60), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((10, 20), "INV-9900", fill="black", font=font)
    img.save(img_path)

    engine = RapidOCREngine(default_lang="en_v6")
    loaded_img = Image.open(img_path)
    page_data, prov, conf, warnings = engine.ocr_page(
        loaded_img,
        page_number=1,
        input_id="inp-test",
        profile=ExecutionProfile.INSTANT,
    )

    assert prov.evidence["model"] == "PP-OCRv6"
    assert prov.evidence["scope"] == "english_and_numbers"
    assert "v6_en" in engine._engines


def test_font_conversion_lightweight_oracle_mode(tmp_path: Path) -> None:
    """Verify lightweight oracle mode for font conversion bypasses heavy vision filters."""
    img_path = tmp_path / "lightweight_sample.png"
    img = Image.new("RGB", (200, 60), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((10, 20), "Remington-12", fill="black", font=font)
    img.save(img_path)

    engine = RapidOCREngine(default_lang="en_v6")
    loaded_img = Image.open(img_path)
    page_data, prov, conf, warnings = engine.ocr_page(
        loaded_img,
        page_number=1,
        input_id="inp-oracle",
        profile=ExecutionProfile.INSTANT,
        custom_options={"lightweight": True, "english_numbers_only": True},
    )

    assert prov.evidence["model"] == "PP-OCRv6"
    assert prov.evidence["scope"] == "english_and_numbers"
    assert any("Remington" in line or "12" in line for line in page_data.text.splitlines())
