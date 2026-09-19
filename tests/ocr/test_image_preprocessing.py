# ruff: noqa: E402
"""Tests for Pre-OCR Vision Filters and OpenCV Fallback Behavior."""

from __future__ import annotations

import unittest.mock as mock
from typing import Any

import pytest

# Finding 26 Fix: Guard numpy import so environments without ocr optional extra skip cleanly
np = pytest.importorskip("numpy")

from sarathi.sankalpa import ExecutionProfile
from sarathi.shakti.ocr.engine import (
    RapidOCREngine,
    apply_clahe,
    deskew_image,
    preprocess_ocr_image,
    remove_stamp_artifacts,
)


def test_preprocess_ocr_image_strict_fallback_when_cv2_unavailable() -> None:
    """Verify pre-OCR vision filters return image array unchanged when cv2 is not importable."""
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)

    with mock.patch.dict("sys.modules", {"cv2": None}):
        res = preprocess_ocr_image(dummy_img)
        # Must return the original array untouched
        assert np.array_equal(res, dummy_img)


def test_deskew_image_handles_empty_or_trivial() -> None:
    """Verify deskew_image returns original image with 0.0 angle for blank or empty arrays."""
    blank_img = np.zeros((50, 50, 3), dtype=np.uint8)
    out_img, angle = deskew_image(blank_img)
    assert angle == 0.0
    assert out_img.shape == (50, 50, 3)


def test_apply_clahe_enhancement() -> None:
    """Verify apply_clahe enhances contrast on RGB and grayscale images without altering shape."""
    pytest.importorskip("cv2")
    # Low-contrast image with a subtle gradient
    x = np.linspace(50, 80, 64, dtype=np.uint8)
    rgb_img = np.zeros((64, 64, 3), dtype=np.uint8)
    rgb_img[:, :] = x[:, None]

    enhanced = apply_clahe(rgb_img)
    assert enhanced.shape == (64, 64, 3)
    # Finding 25: Assert contrast enhancement actually altered the pixel values
    assert not np.array_equal(enhanced, rgb_img)

    gray_img = np.zeros((64, 64), dtype=np.uint8)
    gray_img[:, :] = x[:, None]
    enhanced_gray = apply_clahe(gray_img)
    assert enhanced_gray.shape == (64, 64)
    assert not np.array_equal(enhanced_gray, gray_img)


def test_remove_stamp_artifacts_safety() -> None:
    """Verify remove_stamp_artifacts safely passes through clean images."""
    clean_img = np.full((64, 64, 3), 255, dtype=np.uint8)
    res = remove_stamp_artifacts(clean_img)
    assert res.shape == (64, 64, 3)
    assert np.array_equal(res, clean_img)


def test_remove_stamp_artifacts_inpainting() -> None:
    """Verify remove_stamp_artifacts detects red stamp pixels and applies inpainting."""
    pytest.importorskip("cv2")
    img = np.full((80, 80, 3), 255, dtype=np.uint8)
    # Stamp a red circle in the center (RGB red: [255, 0, 0])
    img[30:50, 30:50] = [255, 0, 0]

    inpainted = remove_stamp_artifacts(img)
    assert inpainted.shape == img.shape
    # Red patch must have been altered/inpainted
    assert not np.array_equal(inpainted[30:50, 30:50], img[30:50, 30:50])


def test_preprocess_ocr_image_defaults_are_non_destructive() -> None:
    """Findings 22 & 23 Fix: Preprocessing defaults must NOT inpaint stamps or force aggressive CLAHE."""
    img = np.full((60, 60, 3), 255, dtype=np.uint8)
    img[20:40, 20:40] = [255, 0, 0]

    # By default, remove_stamps and clahe are False
    processed = preprocess_ocr_image(img)
    # Red pixels must NOT be deleted by default
    expected_patch = np.zeros((20, 20, 3), dtype=np.uint8)
    expected_patch[:, :] = [255, 0, 0]
    assert np.array_equal(processed[20:40, 20:40], expected_patch)


def test_full_pipeline_with_cv2_present() -> None:
    """Finding 25 Fix: Verify full pipeline actually transforms image when cv2 is present."""
    pytest.importorskip("cv2")
    # Grayscale gradient image with a red patch
    sample_img = np.zeros((100, 100, 3), dtype=np.uint8)
    sample_img[:, :] = np.linspace(40, 100, 100, dtype=np.uint8)[:, None]
    sample_img[40:60, 40:60] = [255, 0, 0]

    processed = preprocess_ocr_image(sample_img, deskew=False, clahe=True, remove_stamps=True)
    assert processed is not None
    assert processed.shape == sample_img.shape
    # Verification that real transformation occurred
    assert not np.array_equal(processed, sample_img)


def test_ocr_page_profile_preprocessing_logic() -> None:
    """Findings 22 & 23: Verify ocr_page dispatches non-destructive preprocessing per profile."""
    cv2 = pytest.importorskip("cv2")
    engine = RapidOCREngine(default_lang="en")
    mock_runner = mock.MagicMock(return_value=None)
    engine._get_engine = mock.MagicMock(return_value=mock_runner)

    img = np.full((60, 60, 3), 255, dtype=np.uint8)

    # 1. INSTANT profile: does not apply stamp removal or aggressive CLAHE
    with mock.patch("sarathi.shakti.ocr.engine.preprocess_ocr_image", wraps=preprocess_ocr_image) as mock_prep:
        engine.ocr_page(img, 1, "in-1", profile=ExecutionProfile.INSTANT)
        mock_prep.assert_called_once()
        _, kwargs = mock_prep.call_args
        assert kwargs["remove_stamps"] is False
        assert kwargs["clahe"] is False

    # 2. ACCURATE profile: enables clahe, but keeps remove_stamps False
    with mock.patch("sarathi.shakti.ocr.engine.preprocess_ocr_image", wraps=preprocess_ocr_image) as mock_prep:
        engine.ocr_page(img, 1, "in-1", profile=ExecutionProfile.ACCURATE)
        mock_prep.assert_called_once()
        _, kwargs = mock_prep.call_args
        assert kwargs["remove_stamps"] is False
        assert kwargs["clahe"] is True

    # 3. Explicit remove_stamps=True in custom_options: applies removal and records warning on stamped image
    img_stamped = np.full((100, 100, 3), 255, dtype=np.uint8)
    cv2.circle(img_stamped, (50, 50), 30, (220, 30, 30), 4)
    _, _, _, warns = engine.ocr_page(
        img_stamped, 1, "in-1", profile=ExecutionProfile.INSTANT, custom_options={"remove_stamps": True}
    )
    assert any(w.code == "STAMP_REMOVAL_APPLIED" for w in warns)


def test_bug_O10_deskew_angle_estimation() -> None:
    """O10: Verify deskew estimates text line angle, not bounding box of asymmetric ink or borders."""
    cv2 = pytest.importorskip("cv2")

    # 1. Text lines rotated by +3 degrees
    img_p3 = np.full((800, 600, 3), 255, dtype=np.uint8)
    for y in range(100, 700, 50):
        cv2.putText(
            img_p3,
            "The quick brown fox jumps over the lazy dog 12345",
            (50, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 0),
            2,
        )
    m_p3 = cv2.getRotationMatrix2D((300, 400), 3.0, 1.0)
    img_p3 = cv2.warpAffine(img_p3, m_p3, (600, 800), borderValue=(255, 255, 255))
    _, angle_p3 = deskew_image(img_p3)
    assert abs(abs(angle_p3) - 3.0) <= 0.5

    # 2. Text lines rotated by -3 degrees
    img_m3 = np.full((800, 600, 3), 255, dtype=np.uint8)
    for y in range(100, 700, 50):
        cv2.putText(
            img_m3,
            "The quick brown fox jumps over the lazy dog 12345",
            (50, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 0),
            2,
        )
    m_m3 = cv2.getRotationMatrix2D((300, 400), -3.0, 1.0)
    img_m3 = cv2.warpAffine(img_m3, m_m3, (600, 800), borderValue=(255, 255, 255))
    _, angle_m3 = deskew_image(img_m3)
    assert abs(abs(angle_m3) - 3.0) <= 0.5

    # 3. 0 deg skew page with full-page border and horizontal table rows
    img_border = np.full((800, 600, 3), 255, dtype=np.uint8)
    cv2.rectangle(img_border, (20, 20), (580, 780), (0, 0, 0), 2)
    for y in range(100, 700, 60):
        cv2.putText(
            img_border,
            "Regular horizontal text row inside table",
            (50, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 0),
            1,
        )
    out_b, angle_b = deskew_image(img_border)
    assert angle_b == 0.0
    assert np.array_equal(out_b, img_border)

    # 4. 0 deg skew page with asymmetric layout (title top-left, signature bottom-right)
    # On unpatched code, minAreaRect over ink bounding box computes ~ -24.8 deg and rotates!
    img_asym = np.full((800, 600, 3), 255, dtype=np.uint8)
    cv2.putText(img_asym, "OFFICIAL NOTICE", (50, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    cv2.putText(img_asym, "Authorized Signatory", (350, 750), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    out_asym, angle_asym = deskew_image(img_asym)
    assert angle_asym == 0.0
    assert np.array_equal(out_asym, img_asym)


def test_bug_O11_binarize_and_isolated_state() -> None:
    """O11: Verify Otsu binarization preserves gradient/shadowed text and engines have isolated state."""
    # 1. Verify RapidOCREngine class has no shared locks or pools
    assert not hasattr(RapidOCREngine, "_infer_lock"), "Class-level _infer_lock must be removed"
    assert not hasattr(RapidOCREngine, "_gpu_pools"), "Class-level _gpu_pools must be removed"
    assert not hasattr(RapidOCREngine, "_init_lock"), "Class-level _init_lock must be removed"
    assert not hasattr(RapidOCREngine, "_gpu_engines"), "Class-level _gpu_engines must be removed"

    e1 = RapidOCREngine()
    e2 = RapidOCREngine()
    assert e1._infer_lock is not e2._infer_lock
    assert e1._gpu_pools is not e2._gpu_pools

    # 2. Verify binarize on gradient/shadowed illumination uses Otsu (not constant 128)
    # Shadowed document: paper background is 80 (well below 128), text is 10
    img = np.full((100, 100, 3), 80, dtype=np.uint8)
    img[40:60, 40:60] = 10  # text patch

    mock_runner = mock.MagicMock(return_value=None)
    e1._get_engine = mock.MagicMock(return_value=mock_runner)

    e1.ocr_page(img, 1, "in-1", profile=ExecutionProfile.CUSTOM, custom_options={"binarize": True})
    assert mock_runner.called
    binarized_arr = mock_runner.call_args[0][0]

    # With constant 128 threshold, all pixels <= 128 would become 0 (mean == 0.0)
    # With Otsu threshold, background (80) becomes 255 and text (10) becomes 0, so mean > 150
    assert float(np.mean(binarized_arr)) > 150.0
    # Background must be white (255)
    assert np.all(binarized_arr[0, 0] == [255, 255, 255])
    # Text patch must be black (0)
    assert np.all(binarized_arr[50, 50] == [0, 0, 0])


def test_choose_page_rotation() -> None:
    """Verify choose_page_rotation scores candidates by mean_confidence * char_count."""
    from sarathi.shakti.ocr.engine.preprocessing import RotationCandidate, choose_page_rotation

    # 1. 0 deg has low score, 90 deg has high score
    c0 = RotationCandidate(rotation=0, mean_confidence=0.3, char_count=10)
    c90 = RotationCandidate(rotation=90, mean_confidence=0.95, char_count=50)
    c180 = RotationCandidate(rotation=180, mean_confidence=0.2, char_count=5)
    c270 = RotationCandidate(rotation=270, mean_confidence=0.1, char_count=2)
    assert choose_page_rotation([c0, c90, c180, c270]) == 90

    # 2. 0 deg is already best
    c0_best = RotationCandidate(rotation=0, mean_confidence=0.98, char_count=100)
    assert choose_page_rotation([c0_best, c90]) == 0

    # 3. Tuple input support
    assert choose_page_rotation([(0, 0.4, 20), (180, 0.9, 40)]) == 180


def test_bug_O12_page_orientation_detection() -> None:
    """O12: Verify page orientation detection recovers 90/180/270 rotated scans."""
    cv2 = pytest.importorskip("cv2")

    class DummyOcrOutput:
        def __init__(self, txts: list[str], boxes: list[Any], scores: list[float]) -> None:
            self.txts = txts
            self.boxes = boxes
            self.scores = scores

    call_count = 0

    def mock_ocr(arr: np.ndarray, **kwargs: Any) -> DummyOcrOutput:
        nonlocal call_count
        call_count += 1
        # Marker pixel at (y=0, x=0) indicates upright orientation
        if arr[0, 0, 0] == 42:
            return DummyOcrOutput(
                txts=["Upright Text"],
                boxes=[[[10, 10], [100, 10], [100, 25], [10, 25]]],
                scores=[0.95],
            )
        # If tall boxes (rotated 90 or 270)
        h, w = arr.shape[:2]
        if arr[0, w - 1, 0] == 42 or arr[h - 1, 0, 0] == 42:
            return DummyOcrOutput(
                txts=["x"],
                boxes=[[[10, 10], [20, 10], [20, 100], [10, 100]]],
                scores=[0.3],
            )
        # Upside down (180)
        return DummyOcrOutput(
            txts=["???"],
            boxes=[[[10, 10], [100, 10], [100, 25], [10, 25]]],
            scores=[0.2],
        )

    engine = RapidOCREngine(engine=mock_ocr)

    # Base upright image: marker at [0, 0] is [42, 42, 42]
    img_upright = np.full((120, 120, 3), 255, dtype=np.uint8)
    img_upright[0, 0] = [42, 42, 42]

    # 1. Correctly oriented page: exactly 1 call, no rotation applied, no warning
    call_count = 0
    p0, _, _, w0 = engine.ocr_page(img_upright, 1, "in-1", profile=ExecutionProfile.INSTANT)
    assert p0.text == "Upright Text"
    assert p0.metadata.get("rotation_applied") == 0
    assert not any(w.code == "OCR_PAGE_ROTATED" for w in w0)
    assert call_count == 1

    # 2. Rotated 90 degrees clockwise
    img_90 = cv2.rotate(img_upright, cv2.ROTATE_90_CLOCKWISE)
    p90, _, _, w90 = engine.ocr_page(img_90, 1, "in-1", profile=ExecutionProfile.INSTANT)
    assert p90.text == "Upright Text"
    assert p90.metadata.get("rotation_applied") in (90, 270)
    assert any(w.code == "OCR_PAGE_ROTATED" for w in w90)

    # 3. Rotated 180 degrees
    img_180 = cv2.rotate(img_upright, cv2.ROTATE_180)
    p180, _, _, w180 = engine.ocr_page(img_180, 1, "in-1", profile=ExecutionProfile.INSTANT)
    assert p180.text == "Upright Text"
    assert p180.metadata.get("rotation_applied") == 180
    assert any(w.code == "OCR_PAGE_ROTATED" for w in w180)

    # 4. Rotated 270 degrees clockwise
    img_270 = cv2.rotate(img_upright, cv2.ROTATE_90_COUNTERCLOCKWISE)
    p270, _, _, w270 = engine.ocr_page(img_270, 1, "in-1", profile=ExecutionProfile.INSTANT)
    assert p270.text == "Upright Text"
    assert p270.metadata.get("rotation_applied") in (90, 270)
    assert any(w.code == "OCR_PAGE_ROTATED" for w in w270)


def make_stamped_page() -> tuple[np.ndarray, list[tuple[int, int, int, tuple[int, int, int]]], list[np.ndarray], np.ndarray, np.ndarray, np.ndarray]:
    """Generate synthetic document with 5 colored stamps, red heading, small red blob, and black text."""
    cv2 = pytest.importorskip("cv2")
    # Synthetic page 800x600, white background
    img = np.full((800, 600, 3), 255, dtype=np.uint8)

    # Legitimate red heading
    cv2.putText(
        img,
        "CONFIDENTIAL REPORT - URGENT",
        (40, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (200, 20, 20),
        2,
    )
    heading_mask = (img[:, :, 0] > 150) & (img[:, :, 1] < 50) & (np.arange(800)[:, None] < 70)

    # Small red text blob (under 0.1% area = 480 px)
    cv2.putText(img, "Ref: 99", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 30, 30), 1)
    blob_mask = (
        (img[:, :, 0] > 150)
        & (img[:, :, 1] < 50)
        & (np.arange(800)[:, None] >= 70)
        & (np.arange(800)[:, None] < 100)
    )

    # Black text lines across the page
    for y in range(120, 750, 30):
        cv2.putText(
            img,
            f"Line {y}: Standard legal agreement text paragraph with numbers 12345.",
            (40, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (10, 10, 10),
            1,
        )

    gray_clean = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    black_text_mask = gray_clean < 50

    # 5 stamps: red, blue, violet, faded pink, dark navy
    stamps = [
        (150, 250, 45, (220, 30, 30)),    # red
        (450, 250, 45, (30, 80, 220)),    # blue
        (150, 450, 45, (150, 40, 200)),   # violet
        (450, 450, 45, (230, 140, 160)),  # faded pink
        (300, 650, 45, (15, 30, 100)),    # dark navy
    ]

    stamp_masks = []
    for cx, cy, r, rgb in stamps:
        s_layer = np.zeros((800, 600, 3), dtype=np.uint8)
        s_mask = np.zeros((800, 600), dtype=np.uint8)
        cv2.circle(s_layer, (cx, cy), r, rgb, 3)
        cv2.circle(s_mask, (cx, cy), r, 255, 3)
        cv2.circle(s_layer, (cx, cy), r - 10, rgb, 2)
        cv2.circle(s_mask, (cx, cy), r - 10, 255, 2)
        cv2.putText(s_layer, "VERIFIED", (cx - 30, cy + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, rgb, 1)
        s_mask[(s_layer[:, :, 0] > 0) | (s_layer[:, :, 1] > 0) | (s_layer[:, :, 2] > 0)] = 255
        stamp_masks.append(s_mask)

        # Multiply blend over text
        for c in range(3):
            val = rgb[c]
            mask_bool = s_mask > 0
            img[mask_bool, c] = np.clip(
                (img[mask_bool, c].astype(np.float32) * (val / 255.0)), 0, 255
            ).astype(np.uint8)

    return img, stamps, stamp_masks, heading_mask, blob_mask, black_text_mask


def test_bug_O13_stamp_identification_and_removal() -> None:
    """O13: Verify hue-agnostic stamp detection, stamp-likeness filter, and text preservation."""
    cv2 = pytest.importorskip("cv2")
    try:
        from sarathi.shakti.ocr.engine.preprocessing import detect_stamps
    except ImportError:
        detect_stamps = None

    img, stamps, stamp_masks, heading_mask, blob_mask, black_text_mask = make_stamped_page()
    out = remove_stamp_artifacts(img)
    gray_out = cv2.cvtColor(out, cv2.COLOR_RGB2GRAY)

    # 1. For each of the 5 stamps, at least 98% of stamp-only pixels are near-white (gray >= 200)
    for idx, (cx, cy, r, rgb) in enumerate(stamps):
        s_mask = stamp_masks[idx]
        stamp_only = (s_mask > 0) & (~black_text_mask)
        near_white_count = np.count_nonzero((gray_out >= 200) & stamp_only)
        total_stamp_only = np.count_nonzero(stamp_only)
        frac = near_white_count / total_stamp_only if total_stamp_only else 1.0
        assert frac >= 0.98, f"Stamp {idx} ({rgb}) failed: only {frac*100:.1f}% near-white"

    # 2. Legitimate red heading keeps at least 95% of its pixels
    heading_kept = np.count_nonzero(out[heading_mask, 0] > 150)
    heading_frac = heading_kept / np.count_nonzero(heading_mask)
    assert heading_frac >= 0.95, f"Heading destroyed: only {heading_frac*100:.1f}% kept"

    # 3. At least 95% of original black text pixels survive
    survived_text = (gray_out < 100) & black_text_mask
    survived_ratio = np.count_nonzero(survived_text) / np.count_nonzero(black_text_mask)
    assert survived_ratio >= 0.95, f"Text erased: only {survived_ratio*100:.1f}% survived"

    # 4. Small red text blob is unchanged
    blob_kept = np.count_nonzero(out[blob_mask, 0] > 150)
    blob_frac = blob_kept / np.count_nonzero(blob_mask)
    assert blob_frac >= 0.95, f"Small blob altered: only {blob_frac*100:.1f}% kept"

    # 5. Page with no stamps is returned unchanged with removed_ratio == 0
    clean_page = np.full((100, 100, 3), 255, dtype=np.uint8)
    clean_out = remove_stamp_artifacts(clean_page)
    assert np.array_equal(clean_out, clean_page)
    assert detect_stamps is not None
    detection_clean = detect_stamps(clean_page)
    assert detection_clean.removed_ratio == 0.0

    # 7. Coordinator warning verification
    engine = RapidOCREngine(engine=lambda arr, **kw: mock.MagicMock(txts=[], boxes=[], scores=[]))
    # Unstamped page must NOT emit EXPERIMENTAL_STAMP_REMOVAL or STAMP_REMOVAL_APPLIED
    _, _, _, w_clean = engine.ocr_page(
        clean_page, 1, "in-1", custom_options={"stamp_mode": "remove"}
    )
    assert not any(w.code in ("EXPERIMENTAL_STAMP_REMOVAL", "STAMP_REMOVAL_APPLIED") for w in w_clean)

    # Stamped page must emit STAMP_REMOVAL_APPLIED with context
    _, _, _, w_stamped = engine.ocr_page(img, 1, "in-1", custom_options={"stamp_mode": "remove"})
    stamp_warns = [w for w in w_stamped if w.code == "STAMP_REMOVAL_APPLIED"]
    assert len(stamp_warns) == 1
    assert stamp_warns[0].context.get("stamp_count", 0) >= 4
    assert stamp_warns[0].context.get("removed_ratio", 0) > 0


@pytest.mark.performance
def test_bug_O13_stamp_removal_performance_a4() -> None:
    """O13: Benchmark stamp removal on A4 @ 200 DPI under 100 ms."""
    cv2 = pytest.importorskip("cv2")
    import time

    # A4 @ 200 DPI: 2338 x 1654
    h, w = 2338, 1654
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    cv2.circle(img, (400, 500), 100, (220, 30, 30), 5)
    cv2.circle(img, (1200, 500), 100, (30, 80, 220), 5)
    cv2.circle(img, (400, 1500), 100, (150, 40, 200), 5)
    cv2.circle(img, (1200, 1500), 100, (230, 140, 160), 5)
    cv2.circle(img, (800, 2000), 100, (15, 30, 100), 5)

    # Warmup
    remove_stamp_artifacts(img)

    t0 = time.perf_counter()
    remove_stamp_artifacts(img)
    dt_ms = (time.perf_counter() - t0) * 1000
    assert dt_ms < 100.0, f"A4 stamp removal took {dt_ms:.1f}ms, expected < 100ms"
