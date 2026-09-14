"""Image enhancement, orientation correction, and noise reduction for OCR."""

from __future__ import annotations

from typing import Any


def deskew_image(image_arr: Any) -> tuple[Any, float]:
    """Detect text orientation angle and apply affine rotation correction if cv2 is available."""
    try:
        import cv2
        import numpy as np

        if not isinstance(image_arr, np.ndarray) or image_arr.size == 0:
            return image_arr, 0.0

        gray = cv2.cvtColor(image_arr, cv2.COLOR_RGB2GRAY) if len(image_arr.shape) == 3 else image_arr.copy()
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))

        if len(coords) < 100:
            return image_arr, 0.0

        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        elif angle > 45:
            angle = 90 - angle
        else:
            angle = -angle

        if 0.5 < abs(angle) < 45.0:
            (h, w) = image_arr.shape[:2]
            center = (w // 2, h // 2)
            m_rot = cv2.getRotationMatrix2D(center, angle, 1.0)
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
