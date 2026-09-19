"""Image enhancement, orientation correction, and noise reduction for OCR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


def deskew_image(image_arr: Any) -> tuple[Any, float]:
    """Detect text orientation angle and apply affine rotation correction if cv2 is available."""
    try:
        import cv2
        import numpy as np

        if not isinstance(image_arr, np.ndarray) or image_arr.size == 0:
            return image_arr, 0.0

        gray = cv2.cvtColor(image_arr, cv2.COLOR_RGB2GRAY) if len(image_arr.shape) == 3 else image_arr.copy()
        if float(np.std(gray)) < 2.0:
            return image_arr, 0.0

        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        ink_count = cv2.countNonZero(thresh)
        if ink_count < 100 or ink_count > thresh.size * 0.95:
            return image_arr, 0.0

        (h, w) = image_arr.shape[:2]
        # Downscale for fast projection-profile search across candidate angles
        scale = min(1.0, 350.0 / max(h, w))
        if scale < 1.0:
            small = cv2.resize(thresh, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)
        else:
            small = thresh

        sh, sw = small.shape[:2]
        center = (sw // 2, sh // 2)

        def score_angle(ang: float) -> float:
            m_tmp = cv2.getRotationMatrix2D(center, ang, 1.0)
            rot = cv2.warpAffine(
                small,
                m_tmp,
                (sw, sh),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0,
            )
            proj = np.sum(rot, axis=1)
            return float(np.var(proj))

        # Coarse search from -15 to +15 in 0.5 degree steps
        coarse_angles = np.arange(-15.0, 15.001, 0.5)
        coarse_vars = [score_angle(float(a)) for a in coarse_angles]
        best_coarse_idx = int(np.argmax(coarse_vars))
        best_coarse_angle = float(coarse_angles[best_coarse_idx])

        # Fine search in 0.1 degree steps around peak
        fine_angles = np.arange(best_coarse_angle - 0.6, best_coarse_angle + 0.601, 0.1)
        fine_vars = [score_angle(float(a)) for a in fine_angles]
        best_fine_idx = int(np.argmax(fine_vars))
        angle = float(fine_angles[best_fine_idx])

        peak_var = fine_vars[best_fine_idx]
        median_var = float(np.median(coarse_vars))
        conf = (peak_var - median_var) / (peak_var + 1e-6)

        # Require reasonable confidence and meaningful skew (|angle| > 0.5)
        if conf >= 0.20 and 0.5 < abs(angle) < 45.0:
            orig_center = (w // 2, h // 2)
            m_rot = cv2.getRotationMatrix2D(orig_center, angle, 1.0)
            rotated = cv2.warpAffine(
                image_arr,
                m_rot,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            return rotated, round(float(angle), 2)

        return image_arr, 0.0
    except Exception:
        return image_arr, 0.0


def is_low_contrast_image(image_arr: Any, std_threshold: float = 40.0) -> bool:
    """Check if image has low global contrast based on pixel intensity standard deviation."""
    try:
        import numpy as np

        if not isinstance(image_arr, np.ndarray) or image_arr.size == 0:
            return False
        if len(image_arr.shape) == 3:
            gray = 0.299 * image_arr[:, :, 0] + 0.587 * image_arr[:, :, 1] + 0.114 * image_arr[:, :, 2]
            return float(np.std(gray)) < std_threshold
        return float(np.std(image_arr)) < std_threshold
    except Exception:
        return False


def apply_clahe(image_arr: Any, clip_limit: float = 2.0, tile_grid_size: tuple[int, int] = (8, 8)) -> Any:
    """Apply Contrast Limited Adaptive Histogram Equalization (CLAHE) if cv2 is available."""
    try:
        import cv2
        import numpy as np

        if not isinstance(image_arr, np.ndarray) or image_arr.size == 0:
            return image_arr

        if len(image_arr.shape) == 3:
            lab = cv2.cvtColor(image_arr, cv2.COLOR_RGB2LAB)
            l_ch, a_ch, b_ch = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
            cl = clahe.apply(l_ch)
            limg = cv2.merge((cl, a_ch, b_ch))
            return cv2.cvtColor(limg, cv2.COLOR_LAB2RGB)
        else:
            clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
            return clahe.apply(image_arr)
    except Exception:
        return image_arr


def remove_stamp_artifacts(image_arr: Any) -> Any:
    """Inpaint colored official rubber stamps that occlude underlying text if cv2 is available."""
    try:
        import cv2
        import numpy as np

        if not isinstance(image_arr, np.ndarray) or len(image_arr.shape) != 3 or image_arr.size == 0:
            return image_arr

        hsv = cv2.cvtColor(image_arr, cv2.COLOR_RGB2HSV)
        # Mask red and blue official rubber stamp pigments
        lower_red1 = np.array([0, 70, 50])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 70, 50])
        upper_red2 = np.array([180, 255, 255])
        mask_r1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask_r2 = cv2.inRange(hsv, lower_red2, upper_red2)
        stamp_mask = mask_r1 | mask_r2

        if cv2.countNonZero(stamp_mask) > 100:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            stamp_mask = cv2.dilate(stamp_mask, kernel, iterations=1)
            return cv2.inpaint(image_arr, stamp_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

        return image_arr
    except Exception:
        return image_arr


def preprocess_ocr_image(
    image_arr: Any,
    deskew: bool = True,
    clahe: bool = False,
    remove_stamps: bool = False,
) -> Any:
    """Run the pre-OCR vision enhancement pipeline with strict fallback when cv2 is unavailable."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        # Strict graceful fallback when OpenCV is not installed
        return image_arr

    out = image_arr
    if deskew:
        out, _ = deskew_image(out)
    if remove_stamps:
        out = remove_stamp_artifacts(out)
    if clahe:
        out = apply_clahe(out)
    return out


@dataclass(frozen=True)
class RotationCandidate:
    """Candidate orientation evaluation result."""

    rotation: int  # 0, 90, 180, 270
    mean_confidence: float
    char_count: int
    output: Any = None
    spans: tuple[Any, ...] = ()
    lines: tuple[str, ...] = ()
    conf_scores: tuple[float, ...] = ()
    warnings: tuple[Any, ...] = ()


def choose_page_rotation(
    candidates: Sequence[RotationCandidate | dict[str, Any] | tuple[int, float, int]],
) -> int:
    """Select the optimal page rotation angle (0, 90, 180, 270) based on confidence * char_count."""
    if not candidates:
        return 0

    best_rotation = 0
    best_score = -1.0

    for cand in candidates:
        if isinstance(cand, RotationCandidate):
            rot = cand.rotation
            mean_conf = cand.mean_confidence
            chars = cand.char_count
        elif isinstance(cand, dict):
            rot = int(cand.get("rotation", 0))
            mean_conf = float(cand.get("mean_confidence", 0.0))
            chars = int(cand.get("char_count", 0))
        elif isinstance(cand, (tuple, list)):
            rot = int(cand[0])
            mean_conf = float(cand[1])
            chars = int(cand[2])
        else:
            continue

        score = float(mean_conf * chars)
        # Prefer higher score, tie-break to 0 if original orientation is tied for best
        if score > best_score or (score == best_score and rot == 0):
            best_score = score
            best_rotation = rot

    return best_rotation
