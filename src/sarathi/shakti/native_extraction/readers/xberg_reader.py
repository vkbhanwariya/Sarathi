"""High-performance document extraction reader leveraging the pure-Rust Xberg engine.

Provides:
- Lock-free, multi-threaded native document extraction across Meteor Lake CPU cores.
- Multi-column reading order via Rust XY-Cut algorithms.
- Complex script reassembly (Devanagari, RTL, CJK).
- Support for extended document formats (PDF, PPTX, EML, MSG, RTF, EPUB).
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from sarathi.dosh import DoshError, FailureCode
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
from sarathi.shakti.text.typography import (
    normalize_header_template,
    normalize_text_spacing,
)

_TERMINAL_PUNCT = (".", "।", "!", "?", ";", ":")

_FINANCIAL_OR_STATUTORY_RE = re.compile(
    r"(?:[₹$€£]|Rs\.?|INR|USD|\bAmount\b|\bTotal\b|\bBalance\b|\bDue\b|\bInvoice\b|\bPayment\b|\bTax\b|\bGSTIN\b|\bPAN\b|\bDebit\b|\bCredit\b)",
    re.IGNORECASE,
)


def is_xberg_available() -> bool:
    """Return True if xberg package is installed and operational."""
    try:
        import xberg  # noqa: F401

        return True
    except (ImportError, RuntimeError):
        return False


def _run_coroutine_sync(coro: Any) -> Any:
    """Execute an asyncio coroutine safely from sync code even if an event loop is active."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(coro)).result()
    return asyncio.run(coro)


def read_document_with_xberg(
    data: bytes,
    input_id: str,
    mime_type: str | None = None,
    filename: str | None = None,
    skip_header_footer: bool = False,
    password: str | None = None,
    source_path: Path | str | None = None,
) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...], tuple[WarningRecord, ...]]:
    """Extract structured document content, pages, headings, and tables using Xberg."""
    import xberg

    warnings: list[WarningRecord] = []
    passwords = [password] if password else None

    # Detect MIME type and document format
    detected_mime = mime_type
    detected_type = "pdf"
    if data.startswith(b"{\\rtf") or (filename and filename.lower().endswith(".rtf")):
        detected_mime = "application/rtf"
        detected_type = "rtf"
    elif filename and filename.lower().endswith(".pptx"):
        detected_mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        detected_type = "pptx"
    elif filename and filename.lower().endswith(".epub"):
        detected_mime = "application/epub+zip"
        detected_type = "epub"
    elif filename and filename.lower().endswith((".eml", ".msg")):
        detected_mime = "message/rfc822" if filename.lower().endswith(".eml") else "application/vnd.ms-outlook"
        detected_type = "email"
    elif not detected_mime:
        detected_mime = "application/pdf"
        detected_type = "pdf"
    elif "rtf" in detected_mime.lower():
        detected_type = "rtf"
    elif "presentation" in detected_mime.lower() or "pptx" in detected_mime.lower():
        detected_type = "pptx"
    elif "epub" in detected_mime.lower():
        detected_type = "epub"
    elif "email" in detected_mime.lower() or "message" in detected_mime.lower():
        detected_type = "email"

    pdf_cfg = xberg.PdfConfig(
        reading_order=True,
        extract_tables=True,
        passwords=passwords,
        backend="native",
    )
    cfg = xberg.ExtractionConfig(
        disable_ocr=True,
        pdf_options=pdf_cfg,
        output_format="plain",
    )
    if source_path is not None and Path(source_path).is_file():
        inp = xberg.ExtractInput(
            kind="uri",
            uri=str(Path(source_path).resolve()),
            mime_type=detected_mime,
            filename=filename or Path(source_path).name,
        )
    else:
        inp = xberg.ExtractInput(
            kind="bytes",
            bytes=data,
            mime_type=detected_mime,
            filename=filename,
        )

    try:
        res = _run_coroutine_sync(xberg.extract(inp, config=cfg))
    except Exception as exc:
        raise DoshError(
            FailureCode.EXECUTION_FAILED,
            f"Xberg document extraction failed: {exc}",
            context={"stage": STAGE_NAME},
        ) from exc

    if not res or not res.results:
        raise DoshError(
            FailureCode.EXECUTION_FAILED,
            "Xberg document extraction produced no results",
            context={"stage": STAGE_NAME},
        )

    doc_res = res.results[0]
    raw_pages = getattr(doc_res, "pages", None) or []
    if not doc_res.content and not raw_pages and not getattr(doc_res, "tables", None):
        raise DoshError(
            FailureCode.EXECUTION_FAILED,
            "Xberg document extraction returned empty content",
            context={"stage": STAGE_NAME},
        )

    # Convert extracted tables
    doc_tables: list[TableData] = []
    raw_tables = getattr(doc_res, "tables", None) or []
    for t_idx, t in enumerate(raw_tables, start=1):
        headers: tuple[str, ...] = ()
        rows: tuple[tuple[str, ...], ...] = ()
        if getattr(t, "columns", None):
            headers = tuple(str(c) for c in t.columns)
            rows = tuple(tuple(str(c) for c in r) for r in (t.cells or []))
        elif getattr(t, "cells", None) and len(t.cells) > 0:
            headers = tuple(str(c) for c in t.cells[0])
            rows = tuple(tuple(str(c) for c in r) for r in t.cells[1:])

        bbox = None
        if getattr(t, "bounding_box", None):
            b = t.bounding_box
            bbox = (float(b.x0), float(b.y0), float(b.x1), float(b.y1))

        t_page = getattr(t, "page_number", None) or getattr(t, "page", None)
        if t_page is None and getattr(t, "bounding_box", None):
            t_page = getattr(t.bounding_box, "page_number", None) or getattr(t.bounding_box, "page", None)

        doc_tables.append(
            TableData(
                name=f"Table {t_idx}",
                headers=headers,
                rows=rows,
                metadata={"bounding_box": bbox, "kind": "xberg_table", "page": t_page},
            )
        )

    # Running header/footer detection across pages
    header_templates: set[str] = set()
    footer_templates: set[str] = set()
    total_pages = len(raw_pages)
    if skip_header_footer and total_pages >= 2:
        header_counts: dict[str, set[int]] = defaultdict(set)
        footer_counts: dict[str, set[int]] = defaultdict(set)
        min_pages = max(2, int(total_pages * 0.5)) if total_pages >= 3 else 2

        for p_idx, p in enumerate(raw_pages):
            raw_text = getattr(p, "content", None) or ""
            p_lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
            if p_lines:
                for ln in p_lines[:2]:
                    # Never suppress financial or statutory content
                    if _FINANCIAL_OR_STATUTORY_RE.search(ln):
                        continue
                    tmpl = normalize_header_template(ln)
                    if tmpl:
                        header_counts[tmpl].add(p_idx)
                for ln in p_lines[-2:]:
                    if _FINANCIAL_OR_STATUTORY_RE.search(ln):
                        continue
                    tmpl = normalize_header_template(ln)
                    if tmpl:
                        footer_counts[tmpl].add(p_idx)
        header_templates = {tmpl for tmpl, p_set in header_counts.items() if len(p_set) >= min_pages}
        footer_templates = {tmpl for tmpl, p_set in footer_counts.items() if len(p_set) >= min_pages}

    # Convert extracted pages and spans
    pages: list[PageData] = []

    if not raw_pages and doc_res.content:
        # Single synthesized page if pages list is empty
        lines = [ln.strip() for ln in doc_res.content.splitlines() if ln.strip()]
        spans: list[TextSpan] = []
        for l_idx, ln in enumerate(lines):
            is_head = l_idx == 0 or ln.startswith(("# ", "## ", "### ")) or (len(ln) < 45 and not ln.endswith(_TERMINAL_PUNCT))
            cls_name = "title" if (l_idx == 0 and is_head) else ("section-header" if is_head else "paragraph")
            spans.append(
                TextSpan(
                    text=ln,
                    confidence=None,
                    metadata={
                        "layout_class": cls_name,
                        "is_heading": is_head,
                        "layout_order": l_idx,
                    },
                )
            )
        pages.append(
            PageData(
                page_number=1,
                text=doc_res.content,
                spans=tuple(spans),
                tables=tuple(doc_tables),
            )
        )
    else:
        for p_idx, p in enumerate(raw_pages):
            p_num = getattr(p, "page_number", None) or (p_idx + 1)
            raw_p_text = getattr(p, "content", None) or ""
            p_lines = [normalize_text_spacing(ln) for ln in raw_p_text.splitlines()]
            non_empty_lines = [ln for ln in p_lines if ln.strip()]

            p_headers: list[str] = []
            p_footers: list[str] = []
            body_lines: list[str] = []

            for l_idx, ln in enumerate(non_empty_lines):
                trimmed = ln.strip()
                is_financial = bool(_FINANCIAL_OR_STATUTORY_RE.search(trimmed))
                tmpl = normalize_header_template(trimmed)
                if skip_header_footer and not is_financial and l_idx < 2 and tmpl in header_templates:
                    p_headers.append(trimmed)
                elif skip_header_footer and not is_financial and l_idx >= len(non_empty_lines) - 2 and tmpl in footer_templates:
                    p_footers.append(trimmed)
                else:
                    body_lines.append(ln)

            p_text = "\n".join(body_lines if skip_header_footer else p_lines)
            active_lines = body_lines if skip_header_footer else non_empty_lines

            spans = []
            for l_idx, ln in enumerate(active_lines):
                is_head = (
                    ln.startswith(("# ", "## ", "### "))
                    or (l_idx == 0 and p_idx == 0)
                    or (len(ln) < 45 and not ln.endswith(_TERMINAL_PUNCT))
                )
                cls_name = "title" if (l_idx == 0 and p_idx == 0 and is_head) else ("section-header" if is_head else "paragraph")
                spans.append(
                    TextSpan(
                        text=ln,
                        confidence=None,
                        metadata={
                            "layout_class": cls_name,
                            "is_heading": is_head,
                            "layout_order": l_idx,
                        },
                    )
                )

            # Match page-specific tables
            p_tables = [t for t in doc_tables if t.metadata.get("page") == p_num]
            p_meta: dict[str, Any] = {}
            if p_headers:
                p_meta["header"] = "\n".join(p_headers)
            if p_footers:
                p_meta["footer"] = "\n".join(p_footers)

            pages.append(
                PageData(
                    page_number=p_num,
                    text=p_text,
                    spans=tuple(spans),
                    tables=tuple(p_tables if p_tables else (doc_tables if len(raw_pages) == 1 else ())),
                    metadata=p_meta,
                )
            )

    full_text = "\n\n".join(p.text for p in pages if p.text) if pages else (doc_res.content or "")

    provenances = tuple(
        ProvenanceRecord(
            stage=STAGE_NAME,
            capability_id=CAPABILITY_ID,
            plugin_id=PLUGIN_ID,
            page_number=p.page_number,
            evidence={
                "reader": "xberg_layout",
                "engine": "xberg_rust",
                "page_count": len(pages),
                "layout_elements_count": len(p.spans),
                "format": detected_mime,
            },
        )
        for p in pages
    )

    canonical_doc = CanonicalDocument(
        document_id=f"doc-{input_id}",
        source_input_id=input_id,
        pages=tuple(pages),
        tables=tuple(doc_tables),
        text=full_text,
        detected_type=detected_type,
    )

    return canonical_doc, provenances, tuple(warnings)
