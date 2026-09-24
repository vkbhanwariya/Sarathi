"""Native PDF format reader leveraging PyMuPDF."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf

from sarathi.sankalpa import (
    CanonicalDocument,
    PageData,
    ProvenanceRecord,
    TableData,
    TextSpan,
    WarningRecord,
)
from sarathi.shakti.native_extraction.readers.common import (
    CAPABILITY_ID,
    PLUGIN_ID,
    STAGE_NAME,
)
from sarathi.shakti.text import cell_text
from sarathi.shakti.text.typography import (
    classify_page_lines,
    detect_running_headers_footers,
    normalize_text_spacing,
)
from sarathi.yantra.resources import GLOBAL_PYMUPDF_LOCK

_PDF_TEXT_FLAGS = pymupdf.TEXT_DEHYPHENATE | pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES


def _resolve_pdf_font_names(doc: pymupdf.Document) -> dict[str, str]:
    """Extract embedded TrueType SFNT metadata from PyMuPDF to map obfuscated font names to true families."""
    from sarathi.shakti.font_conversion.detector import extract_ttf_font_family

    font_map: dict[str, str] = {}
    seen_xrefs: set[int] = set()

    for page_idx in range(len(doc)):
        try:
            page_fonts = doc[page_idx].get_fonts()
        except Exception:
            continue
        for f in page_fonts:
            if not f or len(f) < 5:
                continue
            xref, ext, _, basefont, ref_name = f[0], str(f[1]).lower(), f[2], str(f[3]), str(f[4])
            clean_base = basefont
            if "+" in clean_base:
                parts = clean_base.split("+", 1)
                if len(parts[0]) == 6 and parts[0].isalpha() and parts[1].strip():
                    clean_base = parts[1].strip()

            if clean_base:
                font_map[basefont] = clean_base
                font_map[ref_name] = clean_base

            # If embedded TrueType font exists, extract TTF table to find canonical Name ID 1/4
            if xref > 0 and xref not in seen_xrefs and ext in ("ttf", "otf", "cff", "n/a"):
                seen_xrefs.add(xref)
                try:
                    extracted = doc.extract_font(xref)
                    buf: Any = None
                    if isinstance(extracted, tuple) and len(extracted) >= 4:
                        buf = extracted[3]
                    elif isinstance(extracted, dict):
                        buf = extracted.get("buffer")
                    if buf and isinstance(buf, (bytes, bytearray)):
                        family = extract_ttf_font_family(buf)
                        if family:
                            font_map[basefont] = family
                            font_map[ref_name] = family
                            if clean_base:
                                font_map[clean_base] = family
                except Exception:
                    pass

    return font_map


def _get_font_conversion_tools() -> dict[str, Any]:
    from sarathi.shakti.font_conversion.byte_normalizer import has_macroman_signatures, normalize_macroman_bytes
    from sarathi.shakti.font_conversion.converter import FontConverter
    from sarathi.shakti.font_conversion.detector import (
        decide_run_profile,
        load_font_profiles,
        resolve_profile_from_font_name,
    )
    from sarathi.shakti.text.legacy_detection import is_legacy_text

    return {
        "converter": FontConverter(),
        "profiles": load_font_profiles(),
        "resolve": resolve_profile_from_font_name,
        "decide": decide_run_profile,
        "normalize_macroman": normalize_macroman_bytes,
        "has_macroman": has_macroman_signatures,
        "is_legacy_text": is_legacy_text,
    }


def _process_page_stream_spans(
    text_page: pymupdf.TextPage,
    doc_font_map: dict[str, str],
    convert_legacy_fonts: bool,
    fc_tools: dict[str, Any] | None,
    warnings: list[WarningRecord],
    page_num: int,
) -> tuple[list[TextSpan], list[tuple[str, tuple[float, float, float, float]]], list[str], set[str]]:
    """Extract and transduce text spans in logical stream order before spatial line reconstruction."""
    page_spans: list[TextSpan] = []
    page_blocks: list[tuple[str, tuple[float, float, float, float]]] = []
    all_line_texts: list[str] = []
    converted_profiles: set[str] = set()

    page_dict = text_page.extractDICT()

    for block in page_dict.get("blocks", []):
        if "lines" not in block:
            continue
        block_line_texts: list[str] = []
        for line in block["lines"]:
            raw_spans = line.get("spans", [])
            if not raw_spans:
                continue

            spans_data: list[dict[str, Any]] = []
            for s in raw_spans:
                s_text = s.get("text", "")
                if not isinstance(s_text, str) or not s_text:
                    continue
                s_font = str(s.get("font", ""))
                resolved_font = doc_font_map.get(s_font) or s_font
                if fc_tools and fc_tools["has_macroman"](s_text):
                    s_text = fc_tools["normalize_macroman"](s_text)
                spans_data.append(
                    {
                        "text": s_text,
                        "font": resolved_font,
                        "size": float(s.get("size", 12.0)),
                        "bbox": tuple(float(v) for v in s.get("bbox", (0.0, 0.0, 0.0, 0.0))),
                    }
                )

            if not spans_data:
                continue

            converted_spans: list[dict[str, Any]] = []
            if convert_legacy_fonts and fc_tools is not None:
                converter = fc_tools["converter"]
                profiles = fc_tools["profiles"]
                resolve = fc_tools["resolve"]
                decide = fc_tools["decide"]

                i = 0
                while i < len(spans_data):
                    cur = spans_data[i]
                    p_id, fam = resolve(cur["font"], profiles)

                    if fam in ("modern", "latin"):
                        converted_spans.append(cur)
                        i += 1
                        continue
                    if fam == "unsupported_legacy":
                        warnings.append(
                            WarningRecord(
                                code="UNSUPPORTED_LEGACY_FONT",
                                message=f"Unsupported legacy font '{cur['font']}' preserved without conversion on page {page_num}.",
                                stage=CAPABILITY_ID,
                            )
                        )
                        converted_spans.append(cur)
                        i += 1
                        continue
                    if p_id is None:
                        decision = decide(cur["font"], cur["text"], profiles=profiles)
                        if decision.decision == "convert" and decision.profile:
                            p_id = decision.profile
                        elif decision.decision == "preserve" and decision.reason == "unsupported_legacy_font":
                            warnings.append(
                                WarningRecord(
                                    code="UNSUPPORTED_LEGACY_FONT",
                                    message=f"Unsupported legacy font '{cur['font']}' preserved without conversion on page {page_num}.",
                                    stage=CAPABILITY_ID,
                                )
                            )
                            converted_spans.append(cur)
                            i += 1
                            continue
                        else:
                            converted_spans.append(cur)
                            i += 1
                            continue

                    # Group adjacent spans in line sharing this legacy profile to preserve keystroke sequence
                    j = i + 1
                    group_text = cur["text"]
                    group_bbox = list(cur["bbox"])
                    while j < len(spans_data):
                        nxt = spans_data[j]
                        nxt_pid, _ = resolve(nxt["font"], profiles)
                        if nxt_pid == p_id:
                            group_text += nxt["text"]
                            group_bbox[2] = max(group_bbox[2], nxt["bbox"][2])
                            group_bbox[3] = max(group_bbox[3], nxt["bbox"][3])
                            j += 1
                        else:
                            break

                    converted_text = converter.convert(group_text, profile_id=p_id)
                    converted_profiles.add(p_id)
                    converted_spans.append(
                        {
                            "text": converted_text,
                            "font": "Mangal",
                            "original_font": cur["font"],
                            "size": cur["size"],
                            "bbox": tuple(group_bbox),
                            "is_converted": True,
                        }
                    )
                    i = j
            else:
                converted_spans = spans_data

            line_str = "".join(s["text"] for s in converted_spans)
            if line_str.strip():
                block_line_texts.append(line_str)
                for s in converted_spans:
                    if s["text"].strip():
                        meta: dict[str, Any] = {
                            "font_name": s["font"],
                            "font_size_pt": round(s["size"], 1),
                            "is_heading": s["size"] >= 14.0,
                        }
                        if s.get("original_font"):
                            meta["original_font"] = s["original_font"]
                        page_spans.append(
                            TextSpan(
                                text=s["text"].strip(),
                                bounding_box=s["bbox"],
                                metadata=meta,
                            )
                        )

        if block_line_texts:
            b_bbox = tuple(float(v) for v in block.get("bbox", (0.0, 0.0, 0.0, 0.0)))
            page_blocks.append(("\n".join(block_line_texts), b_bbox))
            all_line_texts.extend(block_line_texts)

    return page_spans, page_blocks, all_line_texts, converted_profiles


def _extract_vector_stroke_tables(
    page: pymupdf.Page,
    spans: list[TextSpan],
    page_num: int,
) -> list[TableData]:
    """Cluster intersecting horizontal and vertical vector drawing paths into structured tables."""
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    if not drawings:
        return []

    h_lines: list[tuple[float, float, float]] = []
    v_lines: list[tuple[float, float, float]] = []

    for d in drawings:
        items = d.get("items", [])
        for item in items:
            cmd = item[0]
            if cmd == "l":
                p1, p2 = item[1], item[2]
                x0, y0, x1, y1 = float(p1.x), float(p1.y), float(p2.x), float(p2.y)
                if abs(y1 - y0) <= 2.0 and abs(x1 - x0) >= 15.0:
                    h_lines.append((round(y0, 1), min(x0, x1), max(x0, x1)))
                elif abs(x1 - x0) <= 2.0 and abs(y1 - y0) >= 15.0:
                    v_lines.append((round(x0, 1), min(y0, y1), max(y0, y1)))
            elif cmd == "re":
                r = item[1]
                rx0, ry0, rx1, ry1 = float(r.x0), float(r.y0), float(r.x1), float(r.y1)
                if abs(ry1 - ry0) >= 15.0 and abs(rx1 - rx0) >= 15.0:
                    h_lines.append((round(ry0, 1), rx0, rx1))
                    h_lines.append((round(ry1, 1), rx0, rx1))
                    v_lines.append((round(rx0, 1), ry0, ry1))
                    v_lines.append((round(rx1, 1), ry0, ry1))

    if len(h_lines) < 3 or len(v_lines) < 3:
        return []

    h_lines.sort(key=lambda item: item[0])
    y_coords: list[float] = []
    for y, _, _ in h_lines:
        if not y_coords or (y - y_coords[-1]) >= 8.0:
            y_coords.append(y)

    v_lines.sort(key=lambda item: item[0])
    x_coords: list[float] = []
    for x, _, _ in v_lines:
        if not x_coords or (x - x_coords[-1]) >= 15.0:
            x_coords.append(x)

    if len(y_coords) < 3 or len(x_coords) < 3:
        return []

    grid_rows: list[list[str]] = []
    for r in range(len(y_coords) - 1):
        row_cells: list[str] = []
        top_y, bot_y = y_coords[r], y_coords[r + 1]
        for c in range(len(x_coords) - 1):
            left_x, right_x = x_coords[c], x_coords[c + 1]
            cell_texts = []
            for s in spans:
                if not s.bounding_box or not s.text:
                    continue
                sx0, sy0, sx1, sy1 = s.bounding_box
                mid_x = (sx0 + sx1) / 2.0
                mid_y = (sy0 + sy1) / 2.0
                if left_x - 3.0 <= mid_x <= right_x + 3.0 and top_y - 3.0 <= mid_y <= bot_y + 3.0:
                    cell_texts.append(s.text.strip())
            row_cells.append(" ".join(cell_texts))
        grid_rows.append(row_cells)

    has_text = any(any(cell.strip() for cell in row) for row in grid_rows)
    if not has_text:
        return []

    headers = tuple(grid_rows[0])
    rows = tuple(tuple(row) for row in grid_rows[1:])
    table_bbox = (float(x_coords[0]), float(y_coords[0]), float(x_coords[-1]), float(y_coords[-1]))

    return [
        TableData(
            name=f"Page_{page_num}_VectorTable_1",
            headers=headers,
            rows=rows,
            metadata={"bounding_box": table_bbox, "extraction_method": "vector_drawings"},
        )
    ]


def read_pdf(
    data: bytes,
    input_id: str,
    skip_header_footer: bool = False,
    use_layout: bool = False,
    convert_legacy_fonts: bool = True,
    password: str | None = None,
    source_path: Path | str | None = None,
) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...], tuple[WarningRecord, ...]]:
    """Extract full text, pages, rich text spans, and tables from a native PDF document."""
    fallback_warning: WarningRecord | None = None
    if use_layout:
        try:
            from sarathi.shakti.native_extraction.readers.pdf_layout import (
                is_layout_package_available,
                read_pdf_with_layout,
            )

            if is_layout_package_available():
                return read_pdf_with_layout(
                    data,
                    input_id,
                    skip_header_footer=skip_header_footer,
                    convert_legacy_fonts=convert_legacy_fonts,
                    password=password,
                    source_path=source_path,
                )

            fallback_warning = WarningRecord(
                code="LAYOUT_PACKAGE_UNAVAILABLE",
                message="Layout engine (xberg) is not installed; falling back to standard PyMuPDF reader.",
                stage=CAPABILITY_ID,
            )
        except Exception as exc:
            fallback_warning = WarningRecord(
                code="LAYOUT_ANALYSIS_FAILED",
                message=f"Layout analysis failed; falling back to standard reader: {exc}",
                stage=CAPABILITY_ID,
            )

    pages: list[PageData] = []
    provenances: list[ProvenanceRecord] = []
    warnings: list[WarningRecord] = [fallback_warning] if fallback_warning else []
    full_text_parts: list[str] = []
    all_doc_tables: list[TableData] = []
    all_converted_profiles: set[str] = set()

    fc_tools: dict[str, Any] | None = None
    if convert_legacy_fonts:
        try:
            fc_tools = _get_font_conversion_tools()
        except Exception:
            fc_tools = None

    GLOBAL_PYMUPDF_LOCK.acquire()
    try:
        if source_path is not None and Path(source_path).is_file():
            doc = pymupdf.open(str(source_path))
        else:
            doc = pymupdf.open(stream=data, filetype="pdf")
        if doc.is_encrypted:
            if password:
                auth_success = bool(doc.authenticate(password))
                if not auth_success:
                    warnings.append(
                        WarningRecord(
                            code="PDF_AUTHENTICATION_FAILED",
                            message=f"Provided password failed to decrypt PDF for input {input_id}.",
                            stage=CAPABILITY_ID,
                        )
                    )
            else:
                warnings.append(
                    WarningRecord(
                        code="PDF_PASSWORD_REQUIRED",
                        message=f"PDF document {input_id} is password protected but no password was provided.",
                        stage=CAPABILITY_ID,
                    )
                )
            if doc.is_encrypted:
                return (
                    CanonicalDocument(
                        document_id=f"doc-{input_id}",
                        source_input_id=input_id,
                        pages=(),
                        tables=(),
                        text="",
                        detected_type="pdf",
                    ),
                    tuple(provenances),
                    tuple(warnings),
                )
        total_pages = len(doc)
        page_heights: list[float] = []
        doc_font_map = _resolve_pdf_font_names(doc)

        # Pre-extract stream-order page data to avoid spatial jumbling
        cached_pages: list[
            tuple[list[TextSpan], list[tuple[str, tuple[float, float, float, float]]], list[str]]
        ] = []
        all_page_blocks: list[list[tuple[str, tuple[float, float, float, float]]]] = []

        for page_idx in range(total_pages):
            page = doc[page_idx]
            page_num = page_idx + 1
            page_heights.append(float(page.rect.height))
            text_page = page.get_textpage(flags=_PDF_TEXT_FLAGS)

            p_spans, p_blocks, p_lines, p_conv_profs = _process_page_stream_spans(
                text_page=text_page,
                doc_font_map=doc_font_map,
                convert_legacy_fonts=convert_legacy_fonts,
                fc_tools=fc_tools,
                warnings=warnings,
                page_num=page_num,
            )
            all_converted_profiles.update(p_conv_profs)

            # Fallback to standard blocks if span extraction returned nothing
            if not p_blocks:
                try:
                    raw_blocks = text_page.extractBLOCKS()
                    for b in raw_blocks:
                        if len(b) >= 5:
                            x0, y0, x1, y1, b_text = b[0], b[1], b[2], b[3], b[4]
                            if isinstance(b_text, str) and b_text.strip():
                                b_clean = b_text.strip()
                                p_blocks.append((b_clean, (float(x0), float(y0), float(x1), float(y1))))
                                if not p_spans:
                                    p_spans.append(
                                        TextSpan(
                                            text=b_clean,
                                            bounding_box=(float(x0), float(y0), float(x1), float(y1)),
                                        )
                                    )
                except Exception:
                    pass

            cached_pages.append((p_spans, p_blocks, p_lines))
            all_page_blocks.append(p_blocks)
            del text_page

        header_templates, footer_templates = (
            detect_running_headers_footers(all_page_blocks, page_heights) if total_pages >= 2 else (set(), set())
        )

        for page_idx in range(total_pages):
            page_num = page_idx + 1
            page = doc[page_idx]
            p_height = page_heights[page_idx]
            spans, p_blocks, p_lines = cached_pages[page_idx]

            body_lines, header_lines, footer_lines = classify_page_lines(
                p_blocks, p_height, header_templates, footer_templates
            )

            body_text = normalize_text_spacing("\n\n".join(body_lines))
            if skip_header_footer and (header_lines or footer_lines):
                page_text = body_text
            elif p_lines:
                page_text = normalize_text_spacing("\n\n".join(p_lines))
            else:
                raw_text = page.get_text().strip()
                page_text = normalize_text_spacing(raw_text)

            if page_text:
                full_text_parts.append(page_text)

            page_rect = page.rect
            page_meta: dict[str, Any] = {
                "body_char_count": len(body_text.strip()),
                "page_height": float(p_height),
                "page_width": float(page_rect.width),
            }
            if header_lines:
                page_meta["header"] = "\n\n".join(header_lines)
            if footer_lines:
                page_meta["footer"] = "\n\n".join(footer_lines)

            # Compute image area vs page area to arbitrate hybrid scanned pages
            page_area = max(1.0, float(page_rect.width * page_rect.height))
            image_area = 0.0
            try:
                for img_info in page.get_image_info():
                    bbox = img_info.get("bbox")
                    if bbox:
                        image_area += max(0.0, float((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))
            except Exception:
                pass

            image_coverage = min(1.0, image_area / page_area)
            page_meta["image_coverage"] = round(image_coverage, 3)
            if image_coverage >= 0.80 and (len(page_text.strip()) < 30 or len(body_text.strip()) == 0):
                page_meta["is_scanned_image"] = True

            if not spans and p_blocks:
                for b_text, b_box in p_blocks:
                    spans.append(
                        TextSpan(
                            text=b_text,
                            bounding_box=b_box,
                        )
                    )

            # Extract native vector tables if present (skip for scanned pages)
            page_tables: list[TableData] = []
            if not page_meta.get("is_scanned_image"):
                tabs = None
                try:
                    tabs = page.find_tables(
                        vertical_strategy="lines",
                        horizontal_strategy="lines",
                        snap_tolerance=3.0,
                        join_tolerance=3.0,
                        min_words_vertical=1,
                        refine=True,
                    )
                except Exception:
                    try:
                        tabs = page.find_tables(refine=True)
                    except (pymupdf.FileDataError, ValueError):
                        warnings.append(
                            WarningRecord(
                                code="PDF_TABLE_DETECTION_SKIPPED",
                                message="Vector table extraction skipped for page.",
                                stage=STAGE_NAME,
                            )
                        )

                if tabs and len(tabs.tables) > 0:
                    for t_idx, tab in enumerate(tabs.tables, 1):
                        extracted_rows = tab.extract()
                        if extracted_rows and len(extracted_rows) > 0:
                            header_obj = getattr(tab, "header", None)
                            header_names = getattr(header_obj, "names", None) if header_obj is not None else None
                            is_external = (
                                bool(getattr(header_obj, "external", False)) if header_obj is not None else False
                            )

                            if is_external and header_names:
                                headers = tuple(cell_text(h) for h in header_names)
                                data_rows = tuple(tuple(cell_text(val) for val in row) for row in extracted_rows)
                            else:
                                candidate_headers = header_names if header_names else extracted_rows[0]
                                headers = tuple(cell_text(h) for h in candidate_headers)
                                data_rows = tuple(tuple(cell_text(val) for val in row) for row in extracted_rows[1:])

                            if all_converted_profiles and fc_tools:
                                converter = fc_tools["converter"]
                                is_leg = fc_tools["is_legacy_text"]
                                norm_m = fc_tools["normalize_macroman"]
                                first_prof = next(iter(all_converted_profiles))

                                def _conv_cell(cell_val: Any) -> Any:
                                    if not isinstance(cell_val, str) or not cell_val.strip():
                                        return cell_val
                                    c_norm = norm_m(cell_val)
                                    if is_leg(c_norm):
                                        return converter.convert(c_norm, profile_id=first_prof)
                                    return cell_val

                                headers = tuple(cell_text(_conv_cell(h)) for h in headers)
                                data_rows = tuple(tuple(cell_text(_conv_cell(val)) for val in row) for row in data_rows)

                            t_meta = {}
                            if getattr(tab, "bbox", None) is not None:
                                t_meta["bounding_box"] = tuple(float(v) for v in tab.bbox)
                            t_obj = TableData(
                                name=f"Page_{page_num}_Table_{t_idx}",
                                headers=headers,
                                rows=data_rows,
                                metadata=t_meta,
                            )
                            page_tables.append(t_obj)
                            all_doc_tables.append(t_obj)

                # Vector Stroke Fallback Clustering if find_tables found no tables
                if not page_tables:
                    vector_tables = _extract_vector_stroke_tables(page, spans, page_num)
                    for v_tab in vector_tables:
                        page_tables.append(v_tab)
                        all_doc_tables.append(v_tab)

            pages.append(
                PageData(
                    page_number=page_num,
                    text=page_text,
                    spans=tuple(spans),
                    tables=tuple(page_tables),
                    metadata=page_meta,
                )
            )

            provenances.append(
                ProvenanceRecord(
                    source_input_id=input_id,
                    stage=STAGE_NAME,
                    plugin_id=PLUGIN_ID,
                    capability_id=CAPABILITY_ID,
                    page_number=page_num,
                    evidence={
                        "reader": "pymupdf",
                        "page_count": total_pages,
                        "has_native_text": bool(page_text),
                        "table_count": len(page_tables),
                    },
                )
            )

        if all_converted_profiles:
            provenances.append(
                ProvenanceRecord(
                    source_input_id=input_id,
                    stage="convert_legacy_fonts",
                    capability_id="font_conversion",
                    evidence={"profile": sorted(all_converted_profiles)},
                )
            )
    finally:
        try:
            doc.close()
        except Exception:
            pass
        GLOBAL_PYMUPDF_LOCK.release()

    canonical_doc = CanonicalDocument(
        document_id=f"doc-{input_id}",
        source_input_id=input_id,
        pages=tuple(pages),
        tables=tuple(all_doc_tables),
        text="\n\n".join(full_text_parts),
        detected_type="pdf",
    )
    return canonical_doc, tuple(provenances), tuple(warnings)
