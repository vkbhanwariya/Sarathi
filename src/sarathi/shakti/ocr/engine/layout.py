"""Layout and Table Reconstruction Engine for Sarathi OCR.

Uses existing OCR geometry and OpenCV morphology to separate layout reconstruction
from neural text recognition. Owns:
- Ruled and borderless table detection (synthesizing TableData and PageData.tables).
- Column-aware and reading-order-aware paragraph grouping.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from sarathi.sankalpa import TableData, TextSpan
from sarathi.shakti.ocr.engine.parser import sort_reading_order_xycut
from sarathi.shakti.ocr.typography import infer_line_font_size
from sarathi.shakti.text.typography import normalize_text_spacing, reconstruct_line_from_spans

_LIST_BULLET_RE = re.compile(r"^(\s*([•\-\*–—]|(\d+|[a-zA-Z]|[ivxIVX]+|[०-९]+|[क-ह])[\.\)\/\-]))\s+")


@dataclass
class _VisualLine:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    max_h: float


def _build_line_text(sorted_spans: Sequence[TextSpan]) -> str:
    """Reconstruct line text using font-metric gap analysis when bboxes are present."""
    line_spans_data = [
        (
            s.text,
            s.bounding_box,
            max(1.0, abs(s.bounding_box[3] - s.bounding_box[1])) if s.bounding_box else 12.0,
        )
        for s in sorted_spans
        if s.bounding_box is not None and s.text and s.text.strip()
    ]
    if line_spans_data:
        res = reconstruct_line_from_spans(line_spans_data)
        if res:
            return res
    return " ".join(it.text.strip() for it in sorted_spans if it.text and it.text.strip())


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
    sorted_by_y = sorted(spans, key=lambda s: s.bounding_box[1] if s.bounding_box else 0.0)

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
        return (), (), False

    # 3. Detect column partition positions across all rows using start edges (x0)
    col_x_starts: list[float] = []
    for r in rows:
        for s in r:
            if s.bounding_box:
                col_x_starts.append(s.bounding_box[0])

    if not col_x_starts:
        return (), (), False

    col_x_starts.sort()
    col_clusters: list[list[float]] = [[col_x_starts[0]]]
    for x in col_x_starts[1:]:
        if abs(x - statistics.mean(col_clusters[-1])) < 35.0:
            col_clusters[-1].append(x)
        else:
            col_clusters.append([x])

    col_anchors = [statistics.mean(c) for c in col_clusters]
    num_cols = len(col_anchors)

    # 4. Map spans into a structured 2D grid and detect spanning cells
    grid: list[list[str]] = []
    has_spanning_cells = False
    for r in rows:
        row_cells = [""] * num_cols
        for s in r:
            if not s.bounding_box:
                continue
            sx0 = s.bounding_box[0]
            sx1 = s.bounding_box[2]
            # Find nearest column anchor
            best_c = min(range(num_cols), key=lambda ci: abs(col_anchors[ci] - sx0))
            if best_c < num_cols - 1 and (sx1 - col_anchors[best_c + 1]) > 15.0:
                has_spanning_cells = True
            if row_cells[best_c]:
                row_cells[best_c] += " " + s.text.strip()
            else:
                row_cells[best_c] = s.text.strip()
        grid.append(row_cells)

    if len(grid) == 1:
        return tuple(grid[0]), (), has_spanning_cells

    headers = tuple(grid[0])
    data_rows = tuple(tuple(r) for r in grid[1:])
    return headers, data_rows, has_spanning_cells


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
        if h < 40 or w < 40:
            return (), set()

        gray = cv2.cvtColor(image_arr, cv2.COLOR_RGB2GRAY) if len(image_arr.shape) == 3 else image_arr.copy()
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 2)

        # Resolution-adaptive kernel sizing relative to image dimensions
        w_kernel_len = max(15, min(w // 30, 50))
        h_kernel_len = max(10, min(h // 30, 50))

        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w_kernel_len, 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, h_kernel_len))

        h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel)
        v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel)

        table_grid = cv2.add(h_lines, v_lines)
        contours, _ = cv2.findContours(table_grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        total_area = float(h * w)
        t_idx = 1
        candidate_boxes: list[tuple[float, float, float, float]] = []

        # 1. From combined grid contours (both horizontal and vertical lines present)
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            cnt_area = float(cw * ch)
            if 0.005 * total_area <= cnt_area <= 0.85 * total_area and cw >= 60 and ch >= 30:
                candidate_boxes.append((float(x), float(y), float(x + cw), float(y + ch)))

        # 2. Check for multi-line horizontal tables with tight pitch (spacing <= 120px, >= 3 lines)
        h_contours, _ = cv2.findContours(h_lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h_line_rects = [cv2.boundingRect(c) for c in h_contours]
        wide_h_lines = sorted([r for r in h_line_rects if r[2] >= 60], key=lambda r: r[1])
        if len(wide_h_lines) >= 3:
            h_groups: list[list[tuple[int, int, int, int]]] = []
            curr_group = [wide_h_lines[0]]
            for r in wide_h_lines[1:]:
                # Consecutive table rows must have tight vertical spacing (<= 120px)
                if r[1] - (curr_group[-1][1] + curr_group[-1][3]) <= 120:
                    curr_group.append(r)
                else:
                    if len(curr_group) >= 3:
                        h_groups.append(curr_group)
                    curr_group = [r]
            if len(curr_group) >= 3:
                h_groups.append(curr_group)

            for grp in h_groups:
                t_bx0 = float(min(r[0] for r in grp))
                t_by0 = float(grp[0][1])
                t_bx1 = float(max(r[0] + r[2] for r in grp))
                t_by1 = float(grp[-1][1] + grp[-1][3])
                if (t_by1 - t_by0) >= 30 and (t_bx1 - t_bx0) >= 60 and (t_by1 - t_by0) <= 0.70 * h:
                    overlap = any(
                        (
                            max(0.0, min(cb[2], t_bx1) - max(cb[0], t_bx0))
                            * max(0.0, min(cb[3], t_by1) - max(cb[1], t_by0))
                        )
                        > 0.5 * (t_bx1 - t_bx0) * (t_by1 - t_by0)
                        for cb in candidate_boxes
                    )
                    if not overlap:
                        candidate_boxes.append((t_bx0, t_by0, t_bx1, t_by1))

        # For each candidate box, find matching spans and cluster into table
        for table_box in candidate_boxes:
            t_spans: list[TextSpan] = []
            t_span_indices: list[int] = []
            bx0, by0, bx1, by1 = table_box
            for s_idx, span in enumerate(spans):
                if s_idx in consumed_indices or span.bounding_box is None:
                    continue
                sx0, sy0, sx1, sy1 = span.bounding_box
                cx = (sx0 + sx1) / 2.0
                cy = (sy0 + sy1) / 2.0
                if (bx0 - 5.0) <= cx <= (bx1 + 5.0) and (by0 - 5.0) <= cy <= (by1 + 5.0):
                    t_spans.append(span)
                    t_span_indices.append(s_idx)

            if len(t_spans) >= 4:
                headers, data_rows, has_spanning = _cluster_spans_into_grid(t_spans)
                if headers and data_rows and len(headers) >= 2:
                    tables.append(
                        TableData(
                            name=f"Table {t_idx}",
                            headers=headers,
                            rows=data_rows,
                            metadata={
                                "bounding_box": table_box,
                                "kind": "ruled_table",
                                "has_spanning_cells": has_spanning,
                            },
                        )
                    )
                    consumed_indices.update(t_span_indices)
                    t_idx += 1
    except Exception:
        pass

    return tuple(tables), consumed_indices


def detect_borderless_tables(
    spans: Sequence[TextSpan],
    consumed_indices: set[int],
    start_table_idx: int = 1,
) -> tuple[tuple[TableData, ...], set[int]]:
    """Detect borderless tables via coordinate-based row and column clustering.

    Analyzes unconsumed spans to detect regular 2D tabular arrangements (at least 2 columns
    and at least 2 rows) sharing vertically aligned column boundaries with horizontal gutters.
    """
    unconsumed = [
        (idx, s)
        for idx, s in enumerate(spans)
        if idx not in consumed_indices and s.bounding_box is not None and s.text and s.text.strip()
    ]
    if len(unconsumed) < 4:
        return (), set()

    # 1. Cluster unconsumed spans into horizontal visual rows
    sorted_spans = sorted(unconsumed, key=lambda it: it[1].bounding_box[1])  # sort by y0
    rows: list[list[tuple[int, TextSpan]]] = []
    curr_row: list[tuple[int, TextSpan]] = [sorted_spans[0]]
    curr_y0 = sorted_spans[0][1].bounding_box[1]
    curr_y1 = sorted_spans[0][1].bounding_box[3]

    for idx, s in sorted_spans[1:]:
        sy0, sy1 = s.bounding_box[1], s.bounding_box[3]
        s_h = max(1.0, sy1 - sy0)
        overlap = max(0.0, min(curr_y1, sy1) - max(curr_y0, sy0))
        if overlap >= 0.45 * s_h:
            curr_row.append((idx, s))
            curr_y0 = min(curr_y0, sy0)
            curr_y1 = max(curr_y1, sy1)
        else:
            rows.append(sorted(curr_row, key=lambda it: it[1].bounding_box[0]))
            curr_row = [(idx, s)]
            curr_y0, curr_y1 = sy0, sy1
    if curr_row:
        rows.append(sorted(curr_row, key=lambda it: it[1].bounding_box[0]))

    if len(rows) < 2:
        return (), set()

    tables: list[TableData] = []
    new_consumed: set[int] = set()
    t_idx = start_table_idx

    i = 0
    while i < len(rows):
        if len(rows[i]) < 2:
            i += 1
            continue

        candidate_rows = [rows[i]]
        cand_y1 = max(item[1].bounding_box[3] for item in rows[i])
        j = i + 1

        while j < len(rows):
            r = rows[j]
            r_y0 = min(item[1].bounding_box[1] for item in r)
            r_y1 = max(item[1].bounding_box[3] for item in r)
            gap = r_y0 - cand_y1
            row_h = r_y1 - r_y0

            if gap > max(25.0, 2.0 * row_h):
                break

            if len(r) >= 2:
                candidate_rows.append(r)
                cand_y1 = max(cand_y1, r_y1)
                j += 1
            else:
                break

        if len(candidate_rows) >= 2:
            t_items = [item for r in candidate_rows for item in r]
            t_spans = [item[1] for item in t_items]
            t_indices = [item[0] for item in t_items]

            headers, data_rows, has_spanning = _cluster_spans_into_grid(t_spans)
            if headers and data_rows and len(headers) >= 2 and len(data_rows) >= 1:
                all_cells = list(headers) + [c for r in data_rows for c in r]
                non_empty = [c.strip() for c in all_cells if c and c.strip()]
                occupancy = len(non_empty) / max(1, len(all_cells))
                avg_len = sum(len(c) for c in non_empty) / max(1, len(non_empty))
                max_len = max((len(c) for c in non_empty), default=0)

                # Require at least 2 distinct columns populated in data rows
                cols_populated = sum(
                    1 for c_idx in range(len(headers)) if sum(1 for r in data_rows if r[c_idx].strip()) >= 1
                )

                # Invariants: genuine data table (high occupancy, concise cell data, non-prose)
                is_real_table = occupancy >= 0.40 and avg_len <= 80.0 and max_len <= 200 and cols_populated >= 2

                if is_real_table:
                    bx0 = min(s.bounding_box[0] for s in t_spans)
                    by0 = min(s.bounding_box[1] for s in t_spans)
                    bx1 = max(s.bounding_box[2] for s in t_spans)
                    by1 = max(s.bounding_box[3] for s in t_spans)

                    tables.append(
                        TableData(
                            name=f"Table {t_idx}",
                            headers=headers,
                            rows=data_rows,
                            metadata={
                                "bounding_box": (bx0, by0, bx1, by1),
                                "kind": "borderless_table",
                                "has_spanning_cells": has_spanning,
                            },
                        )
                    )
                    new_consumed.update(t_indices)
                    t_idx += 1
                    i = j
                    continue

        i += 1

    return tuple(tables), new_consumed


def reconstruct_layout(
    image_arr: np.ndarray | None,
    spans: Sequence[TextSpan],
    preserve_layout: bool = False,
) -> tuple[str, tuple[TableData, ...]]:
    """Reconstruct structured layout: detect tables, partition columns, and group paragraphs.

    Args:
        image_arr: Full page image array (or None if unavailable).
        spans: Extracted text spans from OCR.
        preserve_layout: Whether to run deep layout reconstruction and table extraction.

    Returns:
        (reconstructed_page_text, detected_tables)
    """
    if not spans:
        return "", ()

    detected_tables: list[TableData] = []
    consumed_indices: set[int] = set()

    if preserve_layout:
        # 1. Ruled tables via OpenCV morphology
        if image_arr is not None and isinstance(image_arr, np.ndarray) and image_arr.size > 0:
            ruled_tables, ruled_consumed = detect_ruled_tables(image_arr, spans)
            detected_tables.extend(ruled_tables)
            consumed_indices.update(ruled_consumed)

        # 2. Borderless tables via coordinate-based row and column clustering
        borderless_tables, borderless_consumed = detect_borderless_tables(
            spans,
            consumed_indices,
            start_table_idx=len(detected_tables) + 1,
        )
        detected_tables.extend(borderless_tables)
        consumed_indices.update(borderless_consumed)

    # Filter out spans consumed by detected tables so they are not jumbled in body paragraphs
    body_spans = [s for idx, s in enumerate(spans) if idx not in consumed_indices and s.text and s.text.strip()]
    if not body_spans and not detected_tables:
        body_spans = list(spans)

    if not body_spans:
        return "", tuple(detected_tables)

    # Sort body spans into natural 2D reading order using Recursive XY-Cut
    ordered_spans = sort_reading_order_xycut(body_spans)

    # Group into lines and paragraphs
    paragraphs = group_paragraphs(ordered_spans)

    return paragraphs, tuple(detected_tables)


def group_paragraphs(spans: Sequence[TextSpan]) -> str:
    """Group ordered text spans into cohesive paragraphs based on geometry and line heights."""
    valid_spans = [s for s in spans if s.text and s.text.strip()]
    if not valid_spans:
        return ""

    # 1. Cluster spans on similar horizontal baselines into visual lines
    lines: list[_VisualLine] = []
    curr_line_spans: list[TextSpan] = [valid_spans[0]]

    for s in valid_spans[1:]:
        if s.bounding_box is None:
            curr_line_spans.append(s)
            continue
        prev_box = curr_line_spans[-1].bounding_box
        if prev_box is None:
            curr_line_spans.append(s)
            continue

        sy0, sy1 = s.bounding_box[1], s.bounding_box[3]
        py0, py1 = prev_box[1], prev_box[3]
        line_h = max(1.0, min(py1 - py0, sy1 - sy0))
        v_overlap = max(0.0, min(py1, sy1) - max(py0, sy0))

        if v_overlap >= 0.45 * line_h:
            curr_line_spans.append(s)
        else:
            sorted_line = sorted(
                curr_line_spans,
                key=lambda it: it.bounding_box[0] if it.bounding_box else 0.0,
            )
            line_str = _build_line_text(sorted_line)
            if line_str:
                x0_min = min((it.bounding_box[0] for it in sorted_line if it.bounding_box), default=0.0)
                y0_min = min((it.bounding_box[1] for it in sorted_line if it.bounding_box), default=0.0)
                x1_max = max((it.bounding_box[2] for it in sorted_line if it.bounding_box), default=0.0)
                y1_max = max((it.bounding_box[3] for it in sorted_line if it.bounding_box), default=0.0)
                lines.append(
                    _VisualLine(
                        x0=x0_min,
                        y0=y0_min,
                        x1=x1_max,
                        y1=y1_max,
                        text=line_str,
                        max_h=max(1.0, y1_max - y0_min),
                    )
                )
            curr_line_spans = [s]

    if curr_line_spans:
        sorted_line = sorted(
            curr_line_spans,
            key=lambda it: it.bounding_box[0] if it.bounding_box else 0.0,
        )
        line_str = _build_line_text(sorted_line)
        if line_str:
            x0_min = min((it.bounding_box[0] for it in sorted_line if it.bounding_box), default=0.0)
            y0_min = min((it.bounding_box[1] for it in sorted_line if it.bounding_box), default=0.0)
            x1_max = max((it.bounding_box[2] for it in sorted_line if it.bounding_box), default=0.0)
            y1_max = max((it.bounding_box[3] for it in sorted_line if it.bounding_box), default=0.0)
            lines.append(
                _VisualLine(
                    x0=x0_min,
                    y0=y0_min,
                    x1=x1_max,
                    y1=y1_max,
                    text=line_str,
                    max_h=max(1.0, y1_max - y0_min),
                )
            )

    if not lines:
        return ""

    # Compute median line height to determine paragraph breaks
    heights = [ln.max_h for ln in lines if ln.max_h > 0]
    median_h = statistics.median(heights) if heights else 15.0
    widths = [ln.x1 - ln.x0 for ln in lines if (ln.x1 - ln.x0) > 0]
    max_w = max(widths) if widths else 100.0
    min_x0 = min((ln.x0 for ln in lines), default=0.0)
    max_x1 = max((ln.x1 for ln in lines), default=100.0)

    # Infer headings and apply markdown prefix (# or ##) to visual lines
    _TERMINAL_PUNCT = (".", "।", "!", "?", ";")
    for ln in lines:
        if ln.text and not ln.text.startswith(("# ", "## ", "### ")):
            bbox = (ln.x0, ln.y0, ln.x1, ln.y1)
            size_pt, is_head = infer_line_font_size(bbox, median_line_height=median_h)
            if is_head:
                trimmed_ln = ln.text.strip()
                words = trimmed_ln.split()
                line_w = ln.x1 - ln.x0
                # Invariants: short title-like text, not ending with sentence punctuation
                is_short_text = len(words) <= 12
                no_sentence_end = not trimmed_ln.endswith(_TERMINAL_PUNCT)
                is_isolated = (line_w <= 0.95 * max_w) or (size_pt >= 17.0) or len(lines) <= 2
                letters_count = sum(1 for ch in trimmed_ln if ch.isalpha())
                has_valid_word = any(len(w) >= 3 and any(ch.isalpha() for ch in w) for w in words)
                is_letter_dense = (letters_count / max(1, len(trimmed_ln))) >= 0.50
                if is_short_text and no_sentence_end and is_isolated and has_valid_word and is_letter_dense:
                    if size_pt >= 17.0:
                        ln.text = f"# {ln.text}"
                    else:
                        ln.text = f"## {ln.text}"

    # 2. Join lines into paragraphs based on geometry
    para_blocks: list[str] = []
    curr_block: list[str] = [lines[0].text]
    prev = lines[0]

    for curr in lines[1:]:
        gap = curr.y0 - prev.y1

        # 1. Vertical gap exceeds paragraph pitch
        is_large_gap = gap >= max(10.0, median_h * 1.25)

        # 2. Heading line
        is_heading = (curr.max_h >= 1.35 * median_h) or curr.text.startswith(("# ", "## ", "### "))
        was_heading = (prev.max_h >= 1.35 * median_h) or prev.text.startswith(("# ", "## ", "### "))

        # 3. List bullet item
        is_list_item = bool(_LIST_BULLET_RE.match(curr.text))

        # 4. Previous line ended significantly early (terminal line of paragraph)
        is_prev_short = (
            (prev.x1 < max_x1 - 2.5 * median_h)
            and ((prev.x1 - prev.x0) < 0.70 * max_w)
            and (gap >= 0.3 * median_h)
            and not was_heading
        )

        # 5. Indentation at the start of a paragraph
        is_indented = (curr.x0 >= min_x0 + 1.5 * median_h) and (gap >= 0.5 * median_h)

        # 6. Horizontal column jump
        is_column_jump = (curr.x0 > prev.x1 + 30.0) or (curr.y0 < prev.y0 - 2.0 * median_h)

        if is_large_gap or is_heading or was_heading or is_list_item or is_prev_short or is_indented or is_column_jump:
            para_blocks.append(" ".join(curr_block))
            curr_block = [curr.text]
        else:
            curr_block.append(curr.text)
        prev = curr

    if curr_block:
        para_blocks.append(" ".join(curr_block))

    cleaned = "\n\n".join(normalize_text_spacing(p) for p in para_blocks if p.strip())
    return cleaned


def detect_column_count(spans: Sequence[TextSpan]) -> int:
    """Detect whether text spans are organized in multiple distinct columns (e.g. 2 columns)."""
    items = [s.bounding_box for s in spans if s.bounding_box and s.text and s.text.strip()]
    if len(items) < 4:
        return 1

    # Filter out full-width spans (e.g. page titles, header banners) that cross multiple columns
    min_x = min(b[0] for b in items)
    max_x = max(b[2] for b in items)
    total_w = max_x - min_x
    min_y = min(b[1] for b in items)
    max_y = max(b[3] for b in items)
    total_h = max_y - min_y

    if total_w < 100.0 or total_h < 50.0:
        return 1

    filtered = [b for b in items if (b[2] - b[0]) < 0.65 * total_w]
    if len(filtered) < 4:
        return 1
    items = filtered

    avg_h = sum(b[3] - b[1] for b in items) / len(items)
    min_gutter = max(20.0, avg_h * 1.0)

    # Sort primarily by X, then Y
    sorted_by_x = sorted(items, key=lambda b: (b[0], b[1]))
    cols: list[list[tuple[float, float, float, float]]] = []
    curr_col = [sorted_by_x[0]]
    max_x1 = sorted_by_x[0][2]

    for b in sorted_by_x[1:]:
        if b[0] >= max_x1 + min_gutter:
            cols.append(curr_col)
            curr_col = [b]
            max_x1 = b[2]
        else:
            curr_col.append(b)
            max_x1 = max(max_x1, b[2])
    if curr_col:
        cols.append(curr_col)

    if len(cols) >= 2:
        # Multi-column content must represent a substantial portion of the page:
        # at least 35% of page items or at least 25% of total page height.
        col_total_items = sum(len(c) for c in cols)
        max_col_h = max(max(b[3] for b in c) - min(b[1] for b in c) for c in cols)
        if col_total_items < 0.35 * len(items) and max_col_h < 0.25 * total_h:
            return 1

        # Check pairwise adjacent column balance and vertical overlap
        for ci in range(len(cols) - 1):
            c1, c2 = cols[ci], cols[ci + 1]
            # 1. Line count balance (rejects e.g. 25 lines vs 2 signature lines)
            len_ratio = min(len(c1), len(c2)) / max(len(c1), len(c2))
            if len_ratio < 0.35:
                return 1
            # 2. Vertical overlap: columns must run side-by-side
            c1_y0 = min(b[1] for b in c1)
            c1_y1 = max(b[3] for b in c1)
            c2_y0 = min(b[1] for b in c2)
            c2_y1 = max(b[3] for b in c2)
            c1_h = max(1.0, c1_y1 - c1_y0)
            c2_h = max(1.0, c2_y1 - c2_y0)
            y_overlap = max(0.0, min(c1_y1, c2_y1) - max(c1_y0, c2_y0))
            if (y_overlap / min(c1_h, c2_h)) < 0.40:
                return 1

        return min(3, len(cols))
    return 1


__all__ = [
    "detect_borderless_tables",
    "detect_column_count",
    "detect_ruled_tables",
    "group_paragraphs",
    "reconstruct_layout",
]
