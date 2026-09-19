"""RapidOCR Output and Geometry Parser for Sarathi.

Normalizes raw OCR model inferences, extracts text spans, validates bounding boxes,
checks confidence score bounds, and generates factual warnings.
"""

from __future__ import annotations

import itertools
import math
import re
import unicodedata
from typing import Any

from sarathi.sankalpa import TextSpan, WarningRecord
from sarathi.shakti.ocr.engine.common import STAGE_NAME

_ALPHANUMERIC_FILTER_RE = re.compile(r"[^\x20-\x7E\u00C0-\u024F₹€£¥§°±×÷½¼¾©®™…\n\r\t•–—“”‘’]")
_HAS_ENGLISH_OR_DIGIT_RE = re.compile(r"[A-Za-z0-9]")


def filter_english_and_numbers(text: str) -> str:
    """Filter text destructively to retain Latin-script letters, numbers, and allowed punctuation.

    WARNING: Destructive by design. Drops non-Latin scripts (e.g. Devanagari) completely,
    normalizes non-breaking spaces, and returns empty string if no ASCII letters or digits remain.
    Preserves Latin-1 Supplement and Latin Extended letters (accented characters), currency
    (₹, €, £, ¥), math/fractions (±, ×, ÷, ½, ¼, ¾, °), and legal/typographic symbols (§, ©, ®, ™, …).
    """
    text = text.replace("\u00a0", " ")
    cleaned = _ALPHANUMERIC_FILTER_RE.sub("", text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    if not _HAS_ENGLISH_OR_DIGIT_RE.search(cleaned):
        return ""
    return cleaned


def sort_reading_order_xycut(spans: list[TextSpan]) -> list[TextSpan]:
    """Sort text spans into natural 2D reading order using Recursive XY-Cut.

    Hierarchically partitions the document into horizontal bands (headers, paragraphs)
    and vertical columns (multi-column layouts) to prevent column interleaving.
    """
    if len(spans) <= 1:
        return spans

    items_with_box: list[tuple[float, float, float, float, TextSpan]] = []
    items_without_box: list[TextSpan] = []

    for s in spans:
        if s.bounding_box is not None:
            x0, y0, x1, y1 = s.bounding_box
            items_with_box.append((x0, y0, x1, y1, s))
        else:
            items_without_box.append(s)

    if not items_with_box:
        return spans

    avg_h = sum(it[3] - it[1] for it in items_with_box) / len(items_with_box)
    min_h_gap = max(12.0, avg_h * 0.75)
    min_v_gap = max(15.0, avg_h * 0.75)

    def _cut(
        items: list[tuple[float, float, float, float, TextSpan]],
    ) -> list[TextSpan]:
        if len(items) <= 1:
            return [it[4] for it in items]

        def _try_horizontal_cut() -> list[list[tuple[float, float, float, float, TextSpan]]]:
            sorted_items = sorted(items, key=lambda it: (it[1], it[0]))
            bands: list[list[tuple[float, float, float, float, TextSpan]]] = []
            curr_band = [sorted_items[0]]
            max_y1 = sorted_items[0][3]

            for it in sorted_items[1:]:
                if it[1] >= max_y1 + min_h_gap:
                    bands.append(curr_band)
                    curr_band = [it]
                    max_y1 = it[3]
                else:
                    curr_band.append(it)
                    max_y1 = max(max_y1, it[3])
            if curr_band:
                bands.append(curr_band)
            return bands if len(bands) > 1 else []

        def _try_vertical_cut() -> list[list[tuple[float, float, float, float, TextSpan]]]:
            sorted_items = sorted(items, key=lambda it: (it[0], it[1]))
            cols: list[list[tuple[float, float, float, float, TextSpan]]] = []
            curr_col = [sorted_items[0]]
            max_x1 = sorted_items[0][2]

            for it in sorted_items[1:]:
                if it[0] >= max_x1 + min_v_gap:
                    cols.append(curr_col)
                    curr_col = [it]
                    max_x1 = it[2]
                else:
                    curr_col.append(it)
                    max_x1 = max(max_x1, it[2])
            if curr_col:
                cols.append(curr_col)
            return cols if len(cols) > 1 else []

        cols = _try_vertical_cut()
        if cols:
            ordered: list[TextSpan] = []
            for c in cols:
                ordered.extend(_cut(c))
            return ordered

        bands = _try_horizontal_cut()
        if bands:
            ordered = []
            for b in bands:
                ordered.extend(_cut(b))
            return ordered

        # Indivisible leaf: sort standard reading order top-to-bottom
        sorted_leaf = sorted(items, key=lambda it: (it[1], it[0]))
        return [it[4] for it in sorted_leaf]

    ordered_with_box = _cut(items_with_box)
    return ordered_with_box + items_without_box


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

        for text_val, box_val, score_val in itertools.zip_longest(raw_txts, raw_boxes, raw_scores, fillvalue=None):
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
                        if not math.isnan(score_float) and not math.isinf(score_float) and 0.0 <= score_float <= 1.0:
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

        if any(s.bounding_box is not None for s in spans):
            spans = sort_reading_order_xycut(spans)
            lines = [s.text for s in spans if s.text]
            conf_scores = [s.confidence for s in spans if s.confidence is not None]

    return lines, spans, conf_scores, warnings, has_invalid_confidence, has_invalid_geometry
