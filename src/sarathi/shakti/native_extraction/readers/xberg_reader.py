"""High-performance document extraction reader leveraging the pure-Rust Xberg engine.

Provides:
- Lock-free, multi-threaded native document extraction across Meteor Lake CPU cores.
- Multi-column reading order via Rust XY-Cut algorithms.
- Complex script reassembly (Devanagari, RTL, CJK).
- Support for extended document formats (PDF, PPTX, EML, MSG, RTF, EPUB).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

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
from sarathi.shakti.text.typography import normalize_text_spacing

_TERMINAL_PUNCT = (".", "।", "!", "?", ";", ":")


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
) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...], tuple[WarningRecord, ...]]:
    """Extract structured document content, pages, headings, and tables using Xberg."""
    import xberg

    warnings: list[WarningRecord] = []
    passwords = [password] if password else None

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
    inp = xberg.ExtractInput(
        kind="bytes",
        bytes=data,
        mime_type=mime_type or "application/pdf",
        filename=filename,
    )

    try:
        res = _run_coroutine_sync(xberg.extract(inp, config=cfg))
    except Exception as exc:
        warnings.append(
            WarningRecord(
                code="XBERG_EXTRACTION_FAILED",
                message=f"Xberg document extraction failed: {exc}",
                stage=CAPABILITY_ID,
            )
        )
        return (
            CanonicalDocument(
                document_id=f"doc-{input_id}",
                source_input_id=input_id,
                pages=(),
                tables=(),
                text="",
                detected_type="pdf",
            ),
            (),
            tuple(warnings),
        )

    if not res.results:
        return (
            CanonicalDocument(
                document_id=f"doc-{input_id}",
                source_input_id=input_id,
                pages=(),
                tables=(),
                text="",
                detected_type="pdf",
            ),
            (),
            tuple(warnings),
        )

    doc_res = res.results[0]

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

        doc_tables.append(
            TableData(
                name=f"Table {t_idx}",
                headers=headers,
                rows=rows,
                metadata={"bounding_box": bbox, "kind": "xberg_table"},
            )
        )

    # Convert extracted pages and spans
    pages: list[PageData] = []
    raw_pages = getattr(doc_res, "pages", None) or []

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
                    confidence=1.0,
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
            p_text = "\n".join(p_lines)
            non_empty_lines = [ln for ln in p_lines if ln.strip()]
            spans = []
            for l_idx, ln in enumerate(non_empty_lines):
                is_head = (
                    ln.startswith(("# ", "## ", "### "))
                    or (l_idx == 0 and p_idx == 0)
                    or (len(ln) < 45 and not ln.endswith(_TERMINAL_PUNCT))
                )
                cls_name = "title" if (l_idx == 0 and p_idx == 0 and is_head) else ("section-header" if is_head else "paragraph")
                spans.append(
                    TextSpan(
                        text=ln,
                        confidence=1.0,
                        metadata={
                            "layout_class": cls_name,
                            "is_heading": is_head,
                            "layout_order": l_idx,
                        },
                    )
                )

            # Match page-specific tables
            p_tables = [t for t in doc_tables if getattr(t.metadata, "get", lambda k: None)("page") == p_num]
            pages.append(
                PageData(
                    page_number=p_num,
                    text=p_text,
                    spans=tuple(spans),
                    tables=tuple(p_tables if p_tables else (doc_tables if len(raw_pages) == 1 else ())),
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
                "legacy_reader": "pymupdf_layout",
                "engine": "xberg_rust",
                "page_count": len(pages),
                "layout_elements_count": len(p.spans),
                "format": mime_type or "application/pdf",
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
        detected_type="pdf",
    )

    return canonical_doc, provenances, tuple(warnings)
