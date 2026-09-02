"""Tests for Advanced OCR Modes: Accurate, Custom, and Deferred Layout Preserving."""

import importlib.util
from pathlib import Path
from typing import Any
import pytest
from PIL import Image, ImageDraw, ImageFont

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import Kosh, Manthan
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.shakti.ocr import OCRCapability
from sarathi.shakti.ocr.engine import RapidOCREngine, TesseractFallbackAdapter
from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO

_OCR_AVAILABLE = bool(
    importlib.util.find_spec("rapidocr")
    and importlib.util.find_spec("openvino")
    and importlib.util.find_spec("PIL")
    and importlib.util.find_spec("numpy")
)

pytestmark = pytest.mark.skipif(
    not _OCR_AVAILABLE,
    reason="Advanced OCR tests require optional OCR dependencies (rapidocr, openvino, PIL, numpy).",
)


class MockTesseractAdapter(TesseractFallbackAdapter):
    """Deterministic test adapter for targeted Tesseract fallback."""

    def __init__(
        self,
        available: bool = True,
        result: tuple[str, float | None] | None = ("TESSERACT_CORRECTED", 0.90),
        raise_error: Exception | None = None,
    ) -> None:
        super().__init__()
        self._available = available
        self._result = result
        self._raise_error = raise_error
        self.call_count = 0

    def is_available(self) -> bool:
        return self._available

    def recognize_crop(self, crop_image: Any) -> tuple[str, float | None]:
        if not self._available:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Tesseract fallback engine is not installed.",
            )
        self.call_count += 1
        if self._raise_error is not None:
            raise self._raise_error
        if self._result is None:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Tesseract fallback produced unusable output.",
            )
        return self._result


class DummyRapidOCROutput:
    def __init__(self, txts: list[str], boxes: list[Any], scores: list[float]) -> None:
        self.txts = txts
        self.boxes = boxes
        self.scores = scores


def _create_clean_image(path: Path) -> None:
    img = Image.new("RGB", (600, 150), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((20, 20), "OFFICIAL GOVERNMENT ORDER", fill="black", font=font)
    draw.text((20, 50), "Date: 15/08/2026 Reference: REF-9900", fill="black", font=font)
    draw.text((20, 80), "Approved Amount: Rs 50,000.00", fill="black", font=font)
    img.save(path)


def test_accurate_profile_executes_and_preserves_clean_cases(tmp_path: Path) -> None:
    img_path = tmp_path / "clean_order.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-acc-1", "req-acc-1", "t-acc", "s-acc")
    inp = InputRef(input_id="inp-acc-1", source_path=img_path, display_name="clean_order.png", size_bytes=img_path.stat().st_size)

    req = Request(
        request_id="req-acc-1",
        requirement="ocr",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
    )

    result = cap.execute(req, ctx)

    assert isinstance(result, Result)
    assert isinstance(result.data, CanonicalDocument)
    doc = result.data
    assert "GOVERNMENT" in doc.text or "ORDER" in doc.text
    assert doc.pages[0].metadata.get("profile") == "accurate"


def test_accurate_profile_measured_confidence_replaces_weaker_rapidocr_span() -> None:
    """Proves factual measured Tesseract confidence replaces weaker RapidOCR span (< 0.65)."""
    img = Image.new("RGB", (200, 50), color="white")
    adapter = MockTesseractAdapter(available=True, result=("TESSERACT_HIGH_CONF", 0.94))
    engine = RapidOCREngine(tesseract_adapter=adapter)
    engine._engine = lambda _arr: DummyRapidOCROutput(
        txts=["WEAK_TEXT"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.50],
    )

    page_data, prov, conf, warnings = engine.ocr_page(img, 1, "inp-1", profile=ExecutionProfile.ACCURATE)

    assert page_data.spans[0].text == "TESSERACT_HIGH_CONF"
    assert page_data.spans[0].confidence == 0.94
    assert page_data.text == "TESSERACT_HIGH_CONF"
    assert prov.evidence.get("fallback_applied") is True
    assert adapter.call_count == 1


def test_accurate_profile_preserves_span_when_fallback_confidence_is_none() -> None:
    """Proves unmeasured fallback confidence (None) does NOT replace primary span."""
    img = Image.new("RGB", (200, 50), color="white")
    adapter = MockTesseractAdapter(available=True, result=("TESSERACT_UNMEASURED", None))
    engine = RapidOCREngine(tesseract_adapter=adapter)
    engine._engine = lambda _arr: DummyRapidOCROutput(
        txts=["PRIMARY_RAPID_TEXT"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.55],
    )

    page_data, prov, conf, warnings = engine.ocr_page(img, 1, "inp-2", profile=ExecutionProfile.ACCURATE)

    # Primary RapidOCR span must be preserved because fallback has no measured confidence evidence
    assert page_data.spans[0].text == "PRIMARY_RAPID_TEXT"
    assert page_data.spans[0].confidence == 0.55
    assert page_data.text == "PRIMARY_RAPID_TEXT"
    assert prov.evidence.get("fallback_applied") is None
    assert adapter.call_count == 1


def test_accurate_profile_preserves_span_when_fallback_confidence_is_lower() -> None:
    """Proves lower fallback confidence does NOT replace primary span."""
    img = Image.new("RGB", (200, 50), color="white")
    adapter = MockTesseractAdapter(available=True, result=("TESSERACT_WORSE", 0.40))
    engine = RapidOCREngine(tesseract_adapter=adapter)
    engine._engine = lambda _arr: DummyRapidOCROutput(
        txts=["PRIMARY_RAPID_TEXT"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.55],
    )

    page_data, prov, conf, warnings = engine.ocr_page(img, 1, "inp-3", profile=ExecutionProfile.ACCURATE)

    assert page_data.spans[0].text == "PRIMARY_RAPID_TEXT"
    assert page_data.spans[0].confidence == 0.55
    assert prov.evidence.get("fallback_applied") is None


def test_accurate_profile_warns_when_tesseract_unavailable() -> None:
    """Proves unavailable Tesseract emits OCR_FALLBACK_UNAVAILABLE and preserves primary span."""
    img = Image.new("RGB", (200, 50), color="white")
    adapter = MockTesseractAdapter(available=False)
    engine = RapidOCREngine(tesseract_adapter=adapter)
    engine._engine = lambda _arr: DummyRapidOCROutput(
        txts=["PRIMARY_TEXT"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.45],
    )

    page_data, prov, conf, warnings = engine.ocr_page(img, 1, "inp-4", profile=ExecutionProfile.ACCURATE)

    assert page_data.spans[0].text == "PRIMARY_TEXT"
    assert any(w.code == "OCR_FALLBACK_UNAVAILABLE" for w in warnings)
    assert adapter.call_count == 0


def test_accurate_profile_warns_and_preserves_span_on_execution_failure() -> None:
    """Proves installed-but-failed Tesseract execution emits OCR_FALLBACK_FAILED and preserves primary span."""
    img = Image.new("RGB", (200, 50), color="white")
    adapter = MockTesseractAdapter(
        available=True,
        raise_error=DoshError(FailureCode.EXECUTION_FAILED, "Tesseract fallback execution failed."),
    )
    engine = RapidOCREngine(tesseract_adapter=adapter)
    engine._engine = lambda _arr: DummyRapidOCROutput(
        txts=["PRIMARY_TEXT"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.45],
    )

    page_data, prov, conf, warnings = engine.ocr_page(img, 1, "inp-5", profile=ExecutionProfile.ACCURATE)

    assert page_data.spans[0].text == "PRIMARY_TEXT"
    assert any(w.code == "OCR_FALLBACK_FAILED" for w in warnings)
    assert not any("tmp" in w.message.lower() for w in warnings)
    assert adapter.call_count == 1


def test_accurate_profile_propagates_unexpected_defect() -> None:
    """Proves unexpected programming defects during fallback propagate directly."""
    img = Image.new("RGB", (200, 50), color="white")
    adapter = MockTesseractAdapter(
        available=True,
        raise_error=TypeError("Unexpected programming bug in crop handling"),
    )
    engine = RapidOCREngine(tesseract_adapter=adapter)
    engine._engine = lambda _arr: DummyRapidOCROutput(
        txts=["PRIMARY_TEXT"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.45],
    )

    with pytest.raises(TypeError, match="Unexpected programming bug in crop handling"):
        engine.ocr_page(img, 1, "inp-6", profile=ExecutionProfile.ACCURATE)


def test_tesseract_adapter_parses_tsv_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves TesseractFallbackAdapter parses TSV word confidences factually without fabrication."""
    adapter = TesseractFallbackAdapter()
    monkeypatch.setattr(adapter, "is_available", lambda: True)

    tsv_output = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "1\t1\t0\t0\t0\t0\t0\t0\t100\t50\t-1\t\n"
        "5\t1\t1\t1\t1\t1\t10\t10\t40\t20\t90.0\tOFFICIAL\n"
        "5\t1\t1\t1\t1\t2\t55\t10\t40\t20\t80.0\tDOC\n"
    )

    class MockSubprocessResult:
        returncode = 0
        stdout = tsv_output

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockSubprocessResult())

    img = Image.new("RGB", (100, 50), color="white")
    text, conf = adapter.recognize_crop(img)

    assert text == "OFFICIAL DOC"
    assert conf == pytest.approx(0.85)  # (0.90 + 0.80) / 2 = 0.85 factual average


def test_tesseract_adapter_plain_text_has_none_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves plain text output without TSV confidence returns confidence=None without fabrication."""
    adapter = TesseractFallbackAdapter()
    monkeypatch.setattr(adapter, "is_available", lambda: True)

    class MockSubprocessResult:
        returncode = 0
        stdout = "NON_TSV_PLAIN_TEXT"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockSubprocessResult())

    img = Image.new("RGB", (100, 50), color="white")
    text, conf = adapter.recognize_crop(img)

    assert text == "NON_TSV_PLAIN_TEXT"
    assert conf is None


def test_tesseract_adapter_handles_subprocess_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves subprocess error raises DoshError(EXECUTION_FAILED)."""
    import subprocess
    adapter = TesseractFallbackAdapter()
    monkeypatch.setattr(adapter, "is_available", lambda: True)

    def mock_run_fail(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="tesseract", timeout=10)

    monkeypatch.setattr("subprocess.run", mock_run_fail)

    img = Image.new("RGB", (100, 50), color="white")
    with pytest.raises(DoshError) as exc_info:
        adapter.recognize_crop(img)
    assert exc_info.value.code == FailureCode.EXECUTION_FAILED


def test_deferred_layout_preserving_profile_rejected_safely(tmp_path: Path) -> None:
    """Verify LAYOUT_PRESERVING is rejected as UNSUPPORTED until layout models are proven."""
    img_path = tmp_path / "table.png"
    _create_clean_image(img_path)

    kosh = Kosh()
    kosh.register_plugin(PLUGIN_INFO)
    kosh.register_capability(CAPABILITY_DECLARATION)
    manthan = Manthan(kosh)

    req = Request(
        request_id="req-lay-1",
        requirement="ocr",
        inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="table.png", size_bytes=10),),
        profile=ExecutionProfile.LAYOUT_PRESERVING,
    )

    # 1. Rejection at Manthan resolution
    with pytest.raises(DoshError) as exc_info:
        manthan.resolve(req)
    assert exc_info.value.code == FailureCode.UNSUPPORTED

    # 2. Rejection at direct capability execution
    cap = OCRCapability()
    ctx = ExecutionContext("run-lay", "req-lay-1", "t-lay", "s-lay")
    with pytest.raises(DoshError) as exc_exec:
        cap.execute(req, ctx)
    assert exc_exec.value.code == FailureCode.UNSUPPORTED


def test_custom_profile_validation_rejects_unsupported_engine(tmp_path: Path) -> None:
    img_path = tmp_path / "doc.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-cust-1", "req-cust-1", "t-cust", "s-cust")
    inp = InputRef(input_id="inp-cust-1", source_path=img_path, display_name="doc.png", size_bytes=img_path.stat().st_size)

    bad_req = Request(
        request_id="req-cust-1",
        requirement="ocr",
        inputs=(inp,),
        profile=ExecutionProfile.CUSTOM,
        custom_options={"engine": "unsupported_cloud_engine"},
    )

    with pytest.raises(DoshError) as exc_info:
        cap.execute(bad_req, ctx)

    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "not supported" in str(exc_info.value.message)


def test_custom_profile_executes_valid_options(tmp_path: Path) -> None:
    img_path = tmp_path / "doc.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-cust-2", "req-cust-2", "t-cust", "s-cust")
    inp = InputRef(input_id="inp-cust-2", source_path=img_path, display_name="doc.png", size_bytes=img_path.stat().st_size)

    valid_req = Request(
        request_id="req-cust-2",
        requirement="ocr",
        inputs=(inp,),
        profile=ExecutionProfile.CUSTOM,
        custom_options={"engine": "rapidocr", "binarize": True},
    )

    result = cap.execute(valid_req, ctx)
    assert isinstance(result, Result)
    assert isinstance(result.data, CanonicalDocument)
