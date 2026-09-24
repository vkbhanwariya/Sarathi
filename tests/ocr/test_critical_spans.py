"""Unit tests for the consequence-driven Critical Span Detector and elevated OCR thresholds."""

from __future__ import annotations

from typing import Any

from PIL import Image

from sarathi.sankalpa import ExecutionProfile
from sarathi.shakti.ocr.engine import RapidOCREngine, enhance_crop_contrast
from sarathi.shakti.ocr.engine.critical import (
    CriticalityType,
    classify_span,
    repair_critical_token,
    validate_critical_token,
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
    """Critical spans below retry threshold trigger bounded single-crop recovery without prose retries."""
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

    # Exactly 1 crop invoked for the critical currency span; standard prose is never retried
    assert len(invoked_crops) == 1

    crit_span = page_data.spans[1]
    assert crit_span.text == "₹ 50,000.00"
    assert crit_span.confidence == 0.96
    assert crit_span.metadata.get("critical_recovered") is True

    reg_span = page_data.spans[0]
    assert reg_span.text == "Regular text line"
    assert reg_span.confidence == 0.75
    assert reg_span.metadata.get("critical_recovered") is not True


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


def test_repair_critical_token_currency_and_numbers() -> None:
    """Verify repair_critical_token fixes common digit/letter confusions in financial amounts."""
    # 'O' -> '0' in amounts
    rep, was_rep = repair_critical_token("₹ 1,O00.5O", CriticalityType.CURRENCY_AMOUNT)
    assert was_rep is True
    assert rep == "₹ 1,000.50"

    rep, was_rep = repair_critical_token("Rs. 25O.00", CriticalityType.CURRENCY_AMOUNT)
    assert was_rep is True
    assert rep == "Rs. 250.00"

    # 'l' -> '1' in amounts
    rep, was_rep = repair_critical_token("1,l50.00", CriticalityType.CURRENCY_AMOUNT)
    assert was_rep is True
    assert rep == "1,150.00"

    # 'S' -> '5' in amounts
    rep, was_rep = repair_critical_token("₹ 5,S00.00", CriticalityType.CURRENCY_AMOUNT)
    assert was_rep is True
    assert rep == "₹ 5,500.00"

    # 'B' -> '8' in amounts
    rep, was_rep = repair_critical_token("₹ 1,B00.00", CriticalityType.CURRENCY_AMOUNT)
    assert was_rep is True
    assert rep == "₹ 1,800.00"

    # Non-currency prose is NOT altered
    clean_text = "The amount is verified"
    rep, was_rep = repair_critical_token(clean_text)
    assert was_rep is False
    assert rep == clean_text


def test_repair_critical_token_dates() -> None:
    """Verify repair_critical_token fixes OCR confusions in dates."""
    rep, was_rep = repair_critical_token("12-O5-2024", CriticalityType.DATE)
    assert was_rep is True
    assert rep == "12-05-2024"

    rep, was_rep = repair_critical_token("l5-08-1947", CriticalityType.DATE)
    assert was_rep is True
    assert rep == "15-08-1947"


def test_repair_critical_token_statutory() -> None:
    """Verify repair_critical_token fixes OCR confusions in PAN and IFSC codes."""
    # PAN: 5 letters + 4 digits + 1 letter (with '0' in 5th letter and 'O' in digits, 'P' individual status)
    rep, was_rep = repair_critical_token("ABCP012O4E", CriticalityType.STATUTORY_IDENTIFIER)
    assert was_rep is True
    assert rep == "ABCPO1204E"

    # IFSC: 4 letters + '0' + 6 alphanumeric (with 'O' in position 5)
    rep, was_rep = repair_critical_token("SBINO001234", CriticalityType.STATUTORY_IDENTIFIER)
    assert was_rep is True
    assert rep == "SBIN0001234"

    # GSTIN with middle typo: 27AAPFU0939F1ZV -> simulated OCR error 27AAPFU0949F1ZV
    # Checksum MUST NOT manufacture 27AAPFU0949F1ZT; observed text must be preserved.
    rep, was_rep = repair_critical_token("27AAPFU0949F1ZV", CriticalityType.STATUTORY_IDENTIFIER)
    assert was_rep is False
    assert rep == "27AAPFU0949F1ZV"


def test_validate_critical_token() -> None:
    """Verify validate_critical_token checks statutory and financial syntaxes."""
    # Valid PAN (with 'P' individual entity code)
    valid, label = validate_critical_token("ABCPE1234F", CriticalityType.STATUTORY_IDENTIFIER)
    assert valid is True
    assert label == "valid_pan"

    # Invalid PAN
    valid, _ = validate_critical_token("12345ABCDE", CriticalityType.STATUTORY_IDENTIFIER)
    assert valid is False

    # Valid IFSC
    valid, label = validate_critical_token("SBIN0001234", CriticalityType.STATUTORY_IDENTIFIER)
    assert valid is True
    assert label == "valid_ifsc"

    # Valid calendar date (leap year Feb 29)
    valid, label = validate_critical_token("29/02/2024", CriticalityType.DATE)
    assert valid is True
    assert label == "valid_date"

    # Invalid calendar date (non-leap year Feb 29)
    valid, label = validate_critical_token("29/02/2023", CriticalityType.DATE)
    assert valid is False
    assert label == "invalid_calendar_date"

    # Invalid calendar date (April 31st does not exist)
    valid, label = validate_critical_token("31/04/2024", CriticalityType.DATE)
    assert valid is False
    assert label == "invalid_calendar_date"

    # Valid decimal amount
    valid, label = validate_critical_token("₹ 1,50,000.50", CriticalityType.CURRENCY_AMOUNT)
    assert valid is True
    assert label == "valid_amount"

    # Valid banking UTR reference
    valid, label = validate_critical_token("UTR: PUNB123456789012", CriticalityType.ACCOUNT_REFERENCE)
    assert valid is True
    assert label == "valid_utr"


def test_bounded_recovery_caps_at_max_crops() -> None:
    """Verify that a page with many low-confidence critical spans strictly caps crop retries at max_crops."""
    engine = RapidOCREngine(default_lang="en")

    invoked_crops: list[Any] = []

    def mock_call(img_arr: Any, **kwargs: Any) -> DummyOutput:
        if kwargs.get("use_det") is False:
            invoked_crops.append(img_arr)
            return DummyOutput(txts=["₹ 1,000.00"], boxes=[], scores=[0.95])
        # Return 6 critical spans all with low confidence 0.70
        txts = [f"₹ {i},000.00" for i in range(1, 7)]
        boxes = [[(10, i * 20), (100, i * 20), (100, i * 20 + 15), (10, i * 20 + 15)] for i in range(1, 7)]
        scores = [0.70] * 6
        return DummyOutput(txts=txts, boxes=boxes, scores=scores)

    engine._engine = mock_call

    img = Image.new("RGB", (200, 200), color="white")
    # By default max_crops is 3
    page_data, _, _, _ = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-cap-test",
        profile=ExecutionProfile.ACCURATE,
    )

    # Exactly 3 crops invoked, never all 6
    assert len(invoked_crops) == 3
    recovered_count = sum(1 for s in page_data.spans if s.metadata.get("critical_recovered"))
    assert recovered_count == 3


def test_enhance_crop_contrast() -> None:
    """Verify enhance_crop_contrast executes CLAHE and preserves image array geometry."""
    import numpy as np

    crop = np.full((32, 120, 3), 128, dtype=np.uint8)
    enhanced = enhance_crop_contrast(crop)
    assert enhanced.shape == crop.shape
    assert enhanced.dtype == np.uint8


def test_devanagari_akshara_synthesis_in_parser() -> None:
    """Verify OCR parser synthesizes canonical Devanagari Akshara Unicode."""
    from sarathi.shakti.ocr.engine.parser import _parse_rapidocr_output

    # Simulate RapidOCR returning decomposed or misordered matra e.g. 'ि' followed by virama 'ि्' -> '्ि'
    raw_output = DummyOutput(
        txts=["हूँ", "क\u093e\u0947", "ख\u093f\u094d"],  # हूँ, composed ओ matra, misplaced matra
        boxes=[
            [(10, 10), (50, 10), (50, 30), (10, 30)],
            [(10, 40), (50, 40), (50, 60), (10, 60)],
            [(10, 70), (50, 70), (50, 90), (10, 90)],
        ],
        scores=[0.9, 0.9, 0.9],
    )

    _, spans, _, _, _, _ = _parse_rapidocr_output(raw_output, filter_opt=False)
    assert len(spans) == 3
    assert spans[0].text == "हूँ"
    assert spans[1].text == "को"
    assert "\u094d\u093f" in spans[2].text


def test_classify_label_anchor() -> None:
    """Verify classify_label_anchor detects statutory, account, date, and currency anchors."""
    from sarathi.shakti.ocr.engine.critical import classify_label_anchor

    assert classify_label_anchor("PAN:") == CriticalityType.STATUTORY_IDENTIFIER
    assert classify_label_anchor("GSTIN") == CriticalityType.STATUTORY_IDENTIFIER
    assert classify_label_anchor("A/C No:") == CriticalityType.ACCOUNT_REFERENCE
    assert classify_label_anchor("Date:") == CriticalityType.DATE
    assert classify_label_anchor("Total Amount:") == CriticalityType.CURRENCY_AMOUNT
    assert classify_label_anchor("Random General Text") is None


def test_context_anchored_recovery_triggers_on_corrupted_statutory_token() -> None:
    """Verify that a corrupted statutory token following a label anchor enters crop recovery."""
    engine = RapidOCREngine(default_lang="en")

    invoked_crops: list[Any] = []

    def mock_call(img_arr: Any, **kwargs: Any) -> DummyOutput:
        if kwargs.get("use_det") is False:
            invoked_crops.append(img_arr)
            # Re-recognizer cleanly recognizes the repaired PAN
            return DummyOutput(txts=["ABCPE1234F"], boxes=[], scores=[0.96])
        # Return label span 'PAN:' followed by noisy statutory token with character '?'
        txts = ["PAN:", "ABcPE1234?"]
        boxes = [
            [(10, 10), (50, 10), (50, 30), (10, 30)],
            [(60, 10), (160, 10), (160, 30), (60, 30)],
        ]
        scores = [0.95, 0.70]
        return DummyOutput(txts=txts, boxes=boxes, scores=scores)

    engine._engine = mock_call

    img = Image.new("RGB", (200, 200), color="white")
    page_data, _, _, _ = engine.ocr_page(
        image=img,
        page_number=1,
        input_id="inp-anchor-test",
        profile=ExecutionProfile.ACCURATE,
    )

    # Corrupted token was recovered because of the preceding 'PAN:' anchor
    assert len(invoked_crops) == 1
    recovered_spans = [s for s in page_data.spans if s.metadata.get("critical_recovered")]
    assert len(recovered_spans) == 1
    assert recovered_spans[0].text == "ABCPE1234F"
