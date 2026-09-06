"""RapidOCR Output and Geometry Parser for Sarathi V2.

Normalizes raw OCR model inferences, extracts text spans, validates bounding boxes,
checks confidence score bounds, and generates factual warnings.
"""

from __future__ import annotations

import itertools
import math
import unicodedata
from typing import Any

from sarathi.sankalpa import TextSpan, WarningRecord
from sarathi.shakti.ocr.engine.common import STAGE_NAME
from sarathi.shakti.ocr.engine.tesseract import filter_english_and_numbers


def _parse_rapidocr_output(
    output: Any,
    filter_opt: bool = True,
) -> tuple[list[str], list[TextSpan], list[float], list[WarningRecord], bool, bool]:
    """Parse raw RapidOCR engine output into validated text lines, spans, and warnings."""
    lines: list[str] = []
    spans: list[TextSpan] = []
    conf_scores: list[float] = []
    warnings: list[WarningRecord] = []
    has_invalid_confidence = False
    has_invalid_geometry = False

    if output and getattr(output, "txts", None):
        raw_txts = list(output.txts)
        raw_boxes = list(output.boxes) if getattr(output, "boxes", None) is not None else []
        raw_scores = list(output.scores) if getattr(output, "scores", None) is not None else []
        if (raw_boxes and len(raw_boxes) != len(raw_txts)) or (raw_scores and len(raw_scores) != len(raw_txts)):
            warnings.append(
                WarningRecord(
                    code="OCR_METADATA_LENGTH_MISMATCH",
                    message="Engine output text, box, and score counts disagree; unaligned items padded safely.",
                    stage=STAGE_NAME,
                )
            )

        for text_val, box_val, score_val in itertools.zip_longest(
            raw_txts, raw_boxes, raw_scores, fillvalue=None
        ):
            if text_val is None:
                continue
            norm_text = unicodedata.normalize("NFC", str(text_val or "").strip())
            if filter_opt:
                norm_text = filter_english_and_numbers(norm_text)
            if norm_text:
                lines.append(norm_text)
                conf: float | None = None
                if score_val is not None:
                    try:
                        score_float = float(score_val)
                        if (
                            not math.isnan(score_float)
                            and not math.isinf(score_float)
                            and 0.0 <= score_float <= 1.0
                        ):
                            conf = score_float
                            conf_scores.append(conf)
                        else:
                            has_invalid_confidence = True
                            warnings.append(
                                WarningRecord(
                                    code="OCR_INVALID_CONFIDENCE",
                                    message="Engine returned out-of-bounds or non-finite confidence ratio.",
                                    stage=STAGE_NAME,
                                )
                            )
                    except (TypeError, ValueError):
                        has_invalid_confidence = True
                        warnings.append(
                            WarningRecord(
                                code="OCR_INVALID_CONFIDENCE",
                                message="Engine returned non-numeric confidence value.",
                                stage=STAGE_NAME,
                            )
                        )
                else:
                    has_invalid_confidence = True
                    warnings.append(
                        WarningRecord(
                            code="OCR_INVALID_CONFIDENCE",
                            message="Engine returned missing confidence value.",
                            stage=STAGE_NAME,
                        )
                    )

                bounding_box: tuple[float, float, float, float] | None = None
                if box_val is not None:
                    try:
                        if len(box_val) < 4:
                            has_invalid_geometry = True
                            warnings.append(
                                WarningRecord(
                                    code="OCR_INVALID_GEOMETRY",
                                    message="Engine returned bounding box with fewer than 4 points.",
                                    stage=STAGE_NAME,
                                )
                            )
                        else:
                            min_x = min(float(pt[0]) for pt in box_val)
                            min_y = min(float(pt[1]) for pt in box_val)
                            max_x = max(float(pt[0]) for pt in box_val)
                            max_y = max(float(pt[1]) for pt in box_val)
                            if any(math.isnan(v) or math.isinf(v) for v in (min_x, min_y, max_x, max_y)):
                                has_invalid_geometry = True
                                warnings.append(
                                    WarningRecord(
                                        code="OCR_INVALID_GEOMETRY",
                                        message="Engine returned non-finite bounding box coordinates.",
                                        stage=STAGE_NAME,
                                    )
                                )
                            else:
                                bounding_box = (min_x, min_y, max_x, max_y)
                    except (TypeError, ValueError, IndexError):
                        has_invalid_geometry = True
                        warnings.append(
                            WarningRecord(
                                code="OCR_INVALID_GEOMETRY",
                                message="Engine returned malformed or non-numeric bounding box coordinates.",
                                stage=STAGE_NAME,
                            )
                        )

                spans.append(
                    TextSpan(
                        text=norm_text,
                        bounding_box=bounding_box,
                        confidence=conf,
                    )
                )

    return lines, spans, conf_scores, warnings, has_invalid_confidence, has_invalid_geometry
