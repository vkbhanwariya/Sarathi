"""Image enhancement, orientation correction, and noise reduction for OCR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence, runtime_checkable


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


@dataclass(frozen=True)
class StampRegion:
    """Detected stamp bounding box and dominant RGB color."""

    bbox: list[int]  # [x0, y0, x1, y1]
    dominant_rgb: list[int]


@dataclass(frozen=True)
class StampDetection:
    """Outcome of stamp detection."""

    mask: Any  # np.ndarray uint8 (H, W), 255 where stamp should be removed, 0 elsewhere
    regions: tuple[StampRegion, ...]
    removed_ratio: float


@runtime_checkable
class StampDetector(Protocol):
    """Protocol for pluggable stamp detection implementations."""

    def detect_stamps(
        self,
        image_rgb: Any,
        chroma_thr: float = 38.0,
        min_side_frac: float = 0.045,
        close_frac: float = 0.018,
        work_scale: float = 0.5,
        pad_frac: float = 0.006,
    ) -> StampDetection: ...


def detect_stamps(
    image_rgb: Any,
    chroma_thr: float = 38.0,
    min_side_frac: float = 0.045,
    close_frac: float = 0.018,
    work_scale: float = 0.5,
    pad_frac: float = 0.006,
) -> StampDetection:
    """Detect colored stamp artifacts across any hue using chroma and morphological filtering."""
    try:
        import cv2
        import numpy as np

        if not isinstance(image_rgb, np.ndarray) or len(image_rgb.shape) != 3 or image_rgb.size == 0:
            h, w = (
                image_rgb.shape[:2]
                if isinstance(image_rgb, np.ndarray) and len(image_rgb.shape) >= 2
                else (0, 0)
            )
            return StampDetection(mask=np.zeros((h, w), dtype=np.uint8), regions=(), removed_ratio=0.0)

        h, w = image_rgb.shape[:2]
        empty_mask = np.zeros((h, w), dtype=np.uint8)

        # 1. Downscale image for fast candidate detection
        work_w = max(1, int(w * work_scale))
        work_h = max(1, int(h * work_scale))
        small_img = cv2.resize(image_rgb, (work_w, work_h), interpolation=cv2.INTER_AREA)

        # Chroma = max(R,G,B) - min(R,G,B) on downscaled planes
        sr, sg, sb = cv2.split(small_img)
        s_max = cv2.max(cv2.max(sr, sg), sb)
        s_min = cv2.min(cv2.min(sr, sg), sb)
        s_chroma = cv2.subtract(s_max, s_min)

        # Make threshold relative to paper background
        s_gray = cv2.cvtColor(small_img, cv2.COLOR_RGB2GRAY)
        bright_bg_mask = s_gray > 200
        if np.count_nonzero(bright_bg_mask) > 100:
            bg_chroma = float(np.median(s_chroma[bright_bg_mask]))
        else:
            bg_chroma = 0.0
        effective_thr = max(18.0, chroma_thr + bg_chroma)
        _, s_mask = cv2.threshold(s_chroma, int(effective_thr), 255, cv2.THRESH_BINARY)

        if cv2.countNonZero(s_mask) < 20:
            return StampDetection(mask=empty_mask, regions=(), removed_ratio=0.0)

        # 2. Morphological closing to fuse stamp letters, rings, and dates
        close_ksize = max(3, int(close_frac * work_w))
        if close_ksize % 2 == 0:
            close_ksize += 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_ksize, close_ksize))
        closed = cv2.morphologyEx(s_mask, cv2.MORPH_CLOSE, kernel)

        # 3. Connected components on closed downscaled mask
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(closed, connectivity=8)

        min_side_thr = min_side_frac * w
        pad = max(2, int(pad_frac * w))

        kept_regions: list[StampRegion] = []
        final_mask = np.zeros((h, w), dtype=np.uint8)
        dk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

        for i in range(1, num_labels):
            x, y, comp_w, comp_h, area = stats[i]
            x0 = int(x / work_scale)
            y0 = int(y / work_scale)
            x1 = int((x + comp_w) / work_scale)
            y1 = int((y + comp_h) / work_scale)

            box_w = x1 - x0
            box_h = y1 - y0
            min_side = min(box_w, box_h)

            if min_side < min_side_thr:
                continue

            if box_w * box_h > 0.8 * w * h:
                continue

            rx0 = max(0, x0 - pad)
            ry0 = max(0, y0 - pad)
            rx1 = min(w, x1 + pad)
            ry1 = min(h, y1 + pad)

            # Refine at full resolution inside stamp candidate region only
            crop = image_rgb[ry0:ry1, rx0:rx1]
            cr, cg, cb = cv2.split(crop)
            c_max = cv2.max(cv2.max(cr, cg), cb)
            c_min = cv2.min(cv2.min(cr, cg), cb)
            c_chroma = cv2.subtract(c_max, c_min)
            _, c_mask = cv2.threshold(c_chroma, int(effective_thr), 255, cv2.THRESH_BINARY)

            c_mask = cv2.dilate(c_mask, dk, iterations=1)
            c_gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
            # Protect dark neutral text pixels (low intensity and low chroma)
            c_mask[(c_gray < 60) & (c_chroma < 15)] = 0

            final_mask[ry0:ry1, rx0:rx1] = np.maximum(final_mask[ry0:ry1, rx0:rx1], c_mask)

            comp_chroma_pixels = c_mask > 0
            if np.any(comp_chroma_pixels):
                dom_rgb = [int(v) for v in np.median(crop[comp_chroma_pixels], axis=0)]
            else:
                dom_rgb = [0, 0, 0]

            kept_regions.append(StampRegion(bbox=[rx0, ry0, rx1, ry1], dominant_rgb=dom_rgb))

        if not kept_regions:
            return StampDetection(mask=empty_mask, regions=(), removed_ratio=0.0)

        removed_pixels = cv2.countNonZero(final_mask)
        removed_ratio = float(removed_pixels) / float(h * w)

        return StampDetection(mask=final_mask, regions=tuple(kept_regions), removed_ratio=removed_ratio)
    except Exception:
        h, w = (
            image_rgb.shape[:2]
            if isinstance(image_rgb, np.ndarray) and len(image_rgb.shape) >= 2
            else (0, 0)
        )
        return StampDetection(mask=np.zeros((h, w), dtype=np.uint8), regions=(), removed_ratio=0.0)


def remove_stamp_artifacts(image_arr: Any) -> Any:
    """Remove colored official rubber stamps using hue-agnostic detection and background fill."""
    try:
        import cv2
        import numpy as np

        if not isinstance(image_arr, np.ndarray) or len(image_arr.shape) != 3 or image_arr.size == 0:
            return image_arr

        detection = detect_stamps(image_arr)
        if detection.removed_ratio == 0.0 or cv2.countNonZero(detection.mask) == 0:
            return image_arr

        # Fast background estimation by subsampling document
        sampled = image_arr[::8, ::8]
        s_gray = cv2.cvtColor(sampled, cv2.COLOR_RGB2GRAY)
        bright = s_gray > 180
        if np.count_nonzero(bright) > 10:
            bg_color = np.median(sampled[bright], axis=0).astype(np.uint8)
        else:
            bg_color = np.array([255, 255, 255], dtype=np.uint8)

        out = image_arr.copy()
        out[detection.mask > 0] = bg_color
        return out
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
