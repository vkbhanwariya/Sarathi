"""Layout and Table Reconstruction Engine for Sarathi OCR.

Uses existing OCR geometry and OpenCV morphology to separate layout reconstruction
from neural text recognition. Owns:
- Ruled and borderless table detection (synthesizing TableData and PageData.tables).
- Column-aware and reading-order-aware paragraph grouping.
"""

from __future__ import annotations

import statistics
from typing import Sequence

import numpy as np

from sarathi.sankalpa import TableData, TextSpan
from sarathi.shakti.ocr.engine.parser import sort_reading_order_xycut
from sarathi.shakti.text.typography import normalize_text_spacing


def _spans_inside_box(
    spans: Sequence[TextSpan],
    box: tuple[float, float, float, float],
) -> list[TextSpan]:
    """Return spans whose spatial center falls strictly within the bounding box."""
    bx0, by0, bx1, by1 = box
    inside: list[TextSpan] = []
    for s in spans:
        if s.bounding_box is None:
            continue
        sx0, sy0, sx1, sy1 = s.bounding_box
        cx = (sx0 + sx1) / 2.0
        cy = (sy0 + sy1) / 2.0
        if bx0 <= cx <= bx1 and by0 <= cy <= by1:
            inside.append(s)
    return inside


def _cluster_spans_into_grid(
    spans: Sequence[TextSpan],
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Cluster table text spans into rows and columns to synthesize headers and rows."""
    if not spans:
        return (), ()

    # 1. Sort spans top-to-bottom
    sorted_by_y = sorted(spans, key=lambda s: (s.bounding_box[1] if s.bounding_box else 0.0))

    # 2. Cluster into rows based on vertical overlap
    rows: list[list[TextSpan]] = []
    curr_row: list[TextSpan] = [sorted_by_y[0]]
    curr_y0 = sorted_by_y[0].bounding_box[1] if sorted_by_y[0].bounding_box else 0.0
    curr_y1 = sorted_by_y[0].bounding_box[3] if sorted_by_y[0].bounding_box else 0.0

    for s in sorted_by_y[1:]:
        if s.bounding_box is None:
            continue
        sy0, sy1 = s.bounding_box[1], s.bounding_box[3]
        s_h = max(1.0, sy1 - sy0)
        overlap = max(0.0, min(curr_y1, sy1) - max(curr_y0, sy0))
        if overlap >= 0.45 * s_h:
            curr_row.append(s)
            curr_y0 = min(curr_y0, sy0)
            curr_y1 = max(curr_y1, sy1)
        else:
            rows.append(sorted(curr_row, key=lambda it: it.bounding_box[0] if it.bounding_box else 0.0))
            curr_row = [s]
            curr_y0, curr_y1 = sy0, sy1
    if curr_row:
        rows.append(sorted(curr_row, key=lambda it: it.bounding_box[0] if it.bounding_box else 0.0))

    if not rows:
        return (), ()

    # 3. Detect column partition positions across all rows
    col_x_centers: list[float] = []
    for r in rows:
        for s in r:
            if s.bounding_box:
                col_x_centers.append((s.bounding_box[0] + s.bounding_box[2]) / 2.0)

    if not col_x_centers:
        return (), ()

    # Find distinct column buckets
    col_x_centers.sort()
    col_clusters: list[list[float]] = [[col_x_centers[0]]]
    for x in col_x_centers[1:]:
        if abs(x - statistics.mean(col_clusters[-1])) < 35.0:
            col_clusters[-1].append(x)
        else:
            col_clusters.append([x])

    col_anchors = [statistics.mean(c) for c in col_clusters]
    num_cols = len(col_anchors)

    # 4. Map spans into a structured 2D grid
    grid: list[list[str]] = []
    for r in rows:
        row_cells = [""] * num_cols
        for s in r:
            if not s.bounding_box:
                continue
            cx = (s.bounding_box[0] + s.bounding_box[2]) / 2.0
            # Find nearest column anchor
            best_c = min(range(num_cols), key=lambda ci: abs(col_anchors[ci] - cx))
            if row_cells[best_c]:
                row_cells[best_c] += " " + s.text.strip()
            else:
                row_cells[best_c] = s.text.strip()
        grid.append(row_cells)

    if len(grid) == 1:
        return tuple(grid[0]), ()

    headers = tuple(grid[0])
    data_rows = tuple(tuple(r) for r in grid[1:])
    return headers, data_rows


def detect_ruled_tables(
    image_arr: np.ndarray,
    spans: Sequence[TextSpan],
) -> tuple[tuple[TableData, ...], set[int]]:
    """Detect ruled tables using OpenCV morphology with resolution-adaptive line kernels."""
    tables: list[TableData] = []
    consumed_indices: set[int] = set()

    if not isinstance(image_arr, np.ndarray) or image_arr.size == 0 or len(image_arr.shape) < 2:
        return (), set()

    try:
        import cv2

        h, w = image_arr.shape[:2]
        if h < 50 or w < 50:
            return (), set()

        gray = cv2.cvtColor(image_arr, cv2.COLOR_RGB2GRAY) if len(image_arr.shape) == 3 else image_arr.copy()
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 2
        )

        # Resolution-adaptive kernel sizing relative to image dimensions
        w_kernel_len = max(20, w // 40)
        h_kernel_len = max(20, h // 40)

        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w_kernel_len, 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, h_kernel_len))

        h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel)
        v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel)

        table_grid = cv2.add(h_lines, v_lines)
        contours, _ = cv2.findContours(table_grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        total_area = float(h * w)
        t_idx = 1

        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            cnt_area = float(cw * ch)
            # Table must occupy at least 3% of page area and have reasonable height/width
            if cnt_area >= 0.03 * total_area and cw >= 80 and ch >= 40:
                table_box = (float(x), float(y), float(x + cw), float(y + ch))
                t_spans = []
                for s_idx, span in enumerate(spans):
                    if span.bounding_box is None:
                        continue
                    sx0, sy0, sx1, sy1 = span.bounding_box
                    cx = (sx0 + sx1) / 2.0
                    cy = (sy0 + sy1) / 2.0
                    if x <= cx <= (x + cw) and y <= cy <= (y + ch):
                        t_spans.append(span)
                        consumed_indices.add(s_idx)

                if t_spans:
                    headers, data_rows = _cluster_spans_into_grid(t_spans)
                    if headers or data_rows:
                        tables.append(
                            TableData(
                                name=f"Table {t_idx}",
                                headers=headers,
                                rows=data_rows,
                                metadata={
                                    "bounding_box": table_box,
                                    "kind": "ruled_table",
                                },
                            )
                        )
                        t_idx += 1
    except Exception:
        pass

    return tuple(tables), consumed_indices


def reconstruct_layout(
    image_arr: np.ndarray,
    spans: Sequence[TextSpan],
    preserve_layout: bool = True,
) -> tuple[str, tuple[TableData, ...]]:
    """Reconstruct structured layout: detect tables, partition columns, and group paragraphs.

    Args:
        image_arr: Full page image array.
        spans: Extracted text spans from OCR.
        preserve_layout: Whether to run deep layout reconstruction and table extraction.

    Returns:
        (reconstructed_page_text, detected_tables)
    """
    if not spans:
        return "", ()

    detected_tables: tuple[TableData, ...] = ()
    consumed_indices: set[int] = set()

    if preserve_layout:
        detected_tables, consumed_indices = detect_ruled_tables(image_arr, spans)

    # Filter out spans consumed by detected tables so they are not jumbled in body paragraphs
    body_spans = [s for idx, s in enumerate(spans) if idx not in consumed_indices and s.text and s.text.strip()]
    if not body_spans and not detected_tables:
        body_spans = list(spans)

    # Sort body spans into natural 2D reading order using Recursive XY-Cut
    ordered_spans = sort_reading_order_xycut(body_spans)

    # Group into lines and paragraphs
    paragraphs = group_paragraphs(ordered_spans)

    return paragraphs, detected_tables


def group_paragraphs(spans: Sequence[TextSpan]) -> str:
    """Group ordered text spans into cohesive paragraphs based on geometry and line heights."""
    if not spans:
        return ""

    # 1. Cluster spans on similar horizontal baselines into visual lines
    lines: list[tuple[float, float, str]] = []  # (top_y, bottom_y, text)
    curr_line_spans: list[TextSpan] = [spans[0]]

    for s in spans[1:]:
        if s.bounding_box is None:
            curr_line_spans.append(s)
            continue
        prev_box = curr_line_spans[-1].bounding_box
        if prev_box is None:
            curr_line_spans.append(s)
            continue

        sy0, sy1 = s.bounding_box[1], s.bounding_box[3]
        py0, py1 = prev_box[1], prev_box[3]
        line_h = max(1.0, py1 - py0)
        v_overlap = max(0.0, min(py1, sy1) - max(py0, sy0))

        if v_overlap >= 0.5 * line_h:
            curr_line_spans.append(s)
        else:
            sorted_line = sorted(
                curr_line_spans,
                key=lambda it: it.bounding_box[0] if it.bounding_box else 0.0,
            )
            line_str = " ".join(it.text.strip() for it in sorted_line if it.text.strip())
            if line_str:
                y0_min = min((it.bounding_box[1] for it in sorted_line if it.bounding_box), default=0.0)
                y1_max = max((it.bounding_box[3] for it in sorted_line if it.bounding_box), default=0.0)
                lines.append((y0_min, y1_max, line_str))
            curr_line_spans = [s]

    if curr_line_spans:
        sorted_line = sorted(
            curr_line_spans,
            key=lambda it: it.bounding_box[0] if it.bounding_box else 0.0,
        )
        line_str = " ".join(it.text.strip() for it in sorted_line if it.text.strip())
        if line_str:
            y0_min = min((it.bounding_box[1] for it in sorted_line if it.bounding_box), default=0.0)
            y1_max = max((it.bounding_box[3] for it in sorted_line if it.bounding_box), default=0.0)
            lines.append((y0_min, y1_max, line_str))

    if not lines:
        return ""

    # Compute median line height to determine paragraph breaks
    heights = [ln[1] - ln[0] for ln in lines if (ln[1] - ln[0]) > 0]
    median_h = statistics.median(heights) if heights else 15.0
    paragraph_break_threshold = max(18.0, median_h * 1.45)

    # 2. Join lines into paragraphs
    para_blocks: list[str] = []
    curr_block: list[str] = [lines[0][2]]
    last_y1 = lines[0][1]

    for y0, y1, text in lines[1:]:
        gap = y0 - last_y1
        if gap >= paragraph_break_threshold:
            para_blocks.append(" ".join(curr_block))
            curr_block = [text]
        else:
            curr_block.append(text)
        last_y1 = max(last_y1, y1)

    if curr_block:
        para_blocks.append(" ".join(curr_block))

    cleaned = "\n\n".join(normalize_text_spacing(p) for p in para_blocks if p.strip())
    return cleaned


__all__ = [
    "detect_ruled_tables",
    "group_paragraphs",
    "reconstruct_layout",
]
