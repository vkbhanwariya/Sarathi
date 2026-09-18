"""Unit tests for the consequence-driven Critical Span Detector and elevated OCR thresholds."""

from __future__ import annotations

from typing import Any

from PIL import Image

from sarathi.sankalpa import ExecutionProfile
from sarathi.shakti.ocr.engine import RapidOCREngine
from sarathi.shakti.ocr.engine.critical import (
    CriticalityType,
    classify_span,
)


class DummyOutput:
    def __init__(self, txts: list[str], boxes: list[Any], scores: list[float]) -> None:
        self.txts = txts
        self.boxes = boxes
        self.scores = scores


def test_classify_span_categories() -> None:
    """Verify classify_span accurately identifies high-consequence entities."""
    # 1. Currency & Amounts
    crit, ctype = classify_span("₹ 1,50,000.00")
    assert crit is True
    assert ctype == CriticalityType.CURRENCY_AMOUNT

    crit, ctype = classify_span("Rs. 45000")
    assert crit is True
    assert ctype == CriticalityType.CURRENCY_AMOUNT

    crit, ctype = classify_span("Total debited 950.50")
    assert crit is True
    assert ctype == CriticalityType.CURRENCY_AMOUNT

    # 2. Statutory Identifiers
    crit, ctype = classify_span("PAN: ABCDE1234F")
    assert crit is True
    assert ctype == CriticalityType.STATUTORY_IDENTIFIER

    crit, ctype = classify_span("GSTIN 07AAAAA0000A1Z5")
    assert crit is True
    assert ctype == CriticalityType.STATUTORY_IDENTIFIER

    crit, ctype = classify_span("IFSC SBIN0001234")
    assert crit is True
    assert ctype == CriticalityType.STATUTORY_IDENTIFIER

    # 3. Dates
    crit, ctype = classify_span("Dated: 15/08/2024")
    assert crit is True
    assert ctype == CriticalityType.DATE

    crit, ctype = classify_span("26 Jan 2023")
    assert crit is True
    assert ctype == CriticalityType.DATE

    # 4. Account references
    crit, ctype = classify_span("A/C No. 9876543210")
    assert crit is True
    assert ctype == CriticalityType.ACCOUNT_REFERENCE

    crit, ctype = classify_span("UTR Ref: UTR123456789")
    assert crit is True
    assert ctype == CriticalityType.ACCOUNT_REFERENCE

    # 5. Legal references
    crit, ctype = classify_span("Under Section 138 of NI Act")
    assert crit is True
    assert ctype == CriticalityType.LEGAL_REFERENCE

    crit, ctype = classify_span("धारा 420")
    assert crit is True
    assert ctype == CriticalityType.LEGAL_REFERENCE

    # 6. Percentage rates
    crit, ctype = classify_span("Interest rate 8.5% p.a.")
    assert crit is True
    assert ctype == CriticalityType.PERCENTAGE_RATE

    # Negative cases (ordinary prose)
    crit, ctype = classify_span("Meeting minutes of the executive committee")
    assert crit is False
    assert ctype is None

    crit, ctype = classify_span("The quick brown fox jumps over the lazy dog")
    assert crit is False
    assert ctype is None


def test_critical_span_elevated_crop_retry() -> None:
    """A critical span with confidence 0.75 triggers retry under default critical threshold (0.85).

    Standard spans with 0.75 do not trigger retry since standard threshold is 0.65.
    """
    engine = RapidOCREngine(default_lang="en")

    invoked_crops: list[Any] = []

    def mock_call(img_arr: Any, **kwargs: Any) -> DummyOutput:
        if kwargs.get("use_det") is False:
            invoked_crops.append(img_arr)
            return DummyOutput(txts=["₹ 50,000.00"], boxes=[], scores=[0.96])
        # Two spans: one standard text at 0.75, one critical text at 0.75
        return DummyOutput(
            txts=["Regular text line", "₹ 50,000.00"],
            boxes=[
                [(10, 10), (100, 10), (100, 30), (10, 30)],
                [(10, 40), (100, 40), (100, 60), (10, 60)],
            ],
            scores=[0.75, 0.75],
        )

    engine._engine = mock_call

    img = Image.new("RGB", (200, 100), color="white")
    page_data, provenance, _, warnings = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-crit-retry",
        profile=ExecutionProfile.ACCURATE,
    )

    # Only the critical span (₹ 50,000.00) should be retried (0.75 < 0.85).
    # The regular text (0.75 >= 0.65) must NOT be retried.
    assert len(invoked_crops) == 1
    assert provenance.evidence["retry_count"] == 1
    assert provenance.evidence["retry_improved_count"] == 1

    crit_span = page_data.spans[1]
    assert crit_span.text == "₹ 50,000.00"
    assert crit_span.confidence == 0.96
    assert crit_span.metadata["retry_applied"] is True

    reg_span = page_data.spans[0]
    assert reg_span.text == "Regular text line"
    assert reg_span.confidence == 0.75
    assert reg_span.metadata.get("retry_applied") is None


def test_critical_span_elevated_review_warning() -> None:
    """A critical span with confidence 0.85 emits OCR_CRITICAL_SPAN_LOW_CONFIDENCE (< 0.90),

    while normal text at 0.85 emits no warning (>= 0.80).
    """
    engine = RapidOCREngine(default_lang="en")

    def mock_call(img_arr: Any, **kwargs: Any) -> DummyOutput:
        # Avoid retrying by returning same or not triggering retry (use instant mode)
        return DummyOutput(
            txts=["General description", "PAN: ABCDE1234F", "Short note"],
            boxes=[
                [(10, 10), (100, 10), (100, 30), (10, 30)],
                [(10, 40), (100, 40), (100, 60), (10, 60)],
                [(10, 70), (100, 70), (100, 90), (10, 90)],
            ],
            scores=[0.85, 0.85, 0.70],  # 0.85 regular (ok), 0.85 critical (warn!), 0.70 regular (warn!)
        )

    engine._engine = mock_call

    img = Image.new("RGB", (200, 120), color="white")
    _, _, _, warnings = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-crit-warning",
        profile=ExecutionProfile.INSTANT,
    )

    codes = [w.code for w in warnings]
    assert "OCR_CRITICAL_SPAN_LOW_CONFIDENCE" in codes
    assert "OCR_LOW_CONFIDENCE" in codes

    crit_warning = next(w for w in warnings if w.code == "OCR_CRITICAL_SPAN_LOW_CONFIDENCE")
    assert "PAN: ABCDE1234F" in crit_warning.message
    assert crit_warning.context["is_critical"] is True
    assert crit_warning.context["criticality_type"] == CriticalityType.STATUTORY_IDENTIFIER.value

    low_warning = next(w for w in warnings if w.code == "OCR_LOW_CONFIDENCE")
    assert "Short note" in low_warning.message
