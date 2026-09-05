"""Document Contracts for Sarathi V2.

Defines the canonical format-agnostic and domain-agnostic document representation:
- TextSpan: A localized or segmented piece of text with optional geometry/evidence.
- TableData: Tabular rows and headers extracted from a document.
- PageData: Page-level text, spans, and tables.
- CanonicalDocument: High-level document container exchanged across capabilities.

Does NOT embed PDF, OCR, spreadsheet, bank, translation, or capability-specific logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping


@dataclass(frozen=True, slots=True)
class TextSpan:
    """Localized text segment within a document page or region."""

    text: str
    confidence: float | None = None
    bounding_box: tuple[float, float, float, float] | None = None
    language: str | None = None
    script: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence is not None:
            if isinstance(self.confidence, bool):
                raise TypeError("confidence cannot be a boolean (True/False).")
            if not isinstance(self.confidence, (int, float)):
                raise TypeError(f"confidence must be numeric (float or int), got {type(self.confidence).__name__}.")
            conf_float = float(self.confidence)
            if math.isnan(conf_float) or math.isinf(conf_float):
                raise ValueError(f"confidence cannot be NaN or Inf, got {conf_float}.")
            if not (0.0 <= conf_float <= 1.0):
                raise ValueError(f"confidence must be a ratio in range [0.0, 1.0], got {conf_float}.")
            object.__setattr__(self, "confidence", conf_float)

        if self.bounding_box is not None:
            if len(self.bounding_box) != 4:
                raise ValueError("bounding_box must be a 4-tuple of floats (x0, y0, x1, y1).")
            object.__setattr__(self, "bounding_box", tuple(float(x) for x in self.bounding_box))
        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")


@dataclass(frozen=True, slots=True)
class TableData:
    """Canonical tabular data representation."""

    name: str = ""
    headers: tuple[str, ...] = ()
    rows: tuple[tuple[Any, ...], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.headers, (list, tuple)):
            object.__setattr__(self, "headers", tuple(str(h) for h in self.headers))
        else:
            raise TypeError(f"headers must be a sequence of strings, got {type(self.headers)}.")
        if isinstance(self.rows, (list, tuple)):
            object.__setattr__(self, "rows", tuple(tuple(row) for row in self.rows))
        else:
            raise TypeError(f"rows must be a sequence of row tuples, got {type(self.rows)}.")
        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")


@dataclass(frozen=True, slots=True)
class PageData:
    """Canonical page-level content."""

    page_number: int
    text: str = ""
    spans: tuple[TextSpan, ...] = ()
    tables: tuple[TableData, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError(f"page_number must be >= 1 (1-indexed), got {self.page_number}.")
        if isinstance(self.spans, (list, tuple)):
            for i, span in enumerate(self.spans):
                if not isinstance(span, TextSpan):
                    raise TypeError(f"spans[{i}] must be a TextSpan, got {type(span)}.")
            object.__setattr__(self, "spans", tuple(self.spans))
        else:
            raise TypeError(f"spans must be a sequence of TextSpan, got {type(self.spans)}.")
        if isinstance(self.tables, (list, tuple)):
            for i, table in enumerate(self.tables):
                if not isinstance(table, TableData):
                    raise TypeError(f"tables[{i}] must be a TableData, got {type(table)}.")
            object.__setattr__(self, "tables", tuple(self.tables))
        else:
            raise TypeError(f"tables must be a sequence of TableData, got {type(self.tables)}.")
        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")


@dataclass(frozen=True, slots=True)
class CanonicalDocument:
    """Canonical format-agnostic document representation exchanged across capabilities."""

    document_id: str
    source_input_id: str | None = None
    pages: tuple[PageData, ...] = ()
    tables: tuple[TableData, ...] = ()
    text: str = ""
    detected_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.document_id or not self.document_id.strip():
            raise ValueError("document_id must be a non-empty string.")
        if isinstance(self.pages, (list, tuple)):
            for i, page in enumerate(self.pages):
                if not isinstance(page, PageData):
                    raise TypeError(f"pages[{i}] must be a PageData, got {type(page)}.")
            object.__setattr__(self, "pages", tuple(self.pages))
        else:
            raise TypeError(f"pages must be a sequence of PageData, got {type(self.pages)}.")
        if isinstance(self.tables, (list, tuple)):
            for i, table in enumerate(self.tables):
                if not isinstance(table, TableData):
                    raise TypeError(f"tables[{i}] must be a TableData, got {type(table)}.")
            object.__setattr__(self, "tables", tuple(self.tables))
        else:
            raise TypeError(f"tables must be a sequence of TableData, got {type(self.tables)}.")
        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")


def transform_canonical_document(
    doc: CanonicalDocument,
    text_transform_fn: Callable[[str], str],
    *,
    detected_type: str,
    target_lang: str | None = None,
    target_script: str | None = None,
    span_transform_fn: Callable[[TextSpan], TextSpan | str] | Callable[[str], str] | None = None,
    reconstruct_text_from_spans: bool = False,
) -> CanonicalDocument:
    """Transform text, pages, spans, and tables of a CanonicalDocument with semantic fidelity.

    - Transforms doc.text and all table headers/cells.
    - Transforms page.text and each TextSpan text, updating language and script while preserving geometry.
    - Aggregates tables across ALL pages when document-level tables were originally empty.
    - When reconstruct_text_from_spans is True, page.text and doc.text are composed directly from transformed spans.
    """
    converted_tables: list[TableData] = []
    for t in doc.tables:
        t_rows = [tuple(text_transform_fn(str(c)) for c in r) for r in t.rows]
        t_headers = tuple(text_transform_fn(str(h)) for h in t.headers) if t.headers else ()
        converted_tables.append(TableData(name=t.name, headers=t_headers, rows=tuple(t_rows), metadata=t.metadata))

    converted_pages: list[PageData] = []
    for p in doc.pages:
        p_page_tables: list[TableData] = []
        for t in p.tables:
            t_rows = [tuple(text_transform_fn(str(c)) for c in r) for r in t.rows]
            t_headers = tuple(text_transform_fn(str(h)) for h in t.headers) if t.headers else ()
            p_page_tables.append(TableData(name=t.name, headers=t_headers, rows=tuple(t_rows), metadata=t.metadata))

        p_spans: list[TextSpan] = []
        for s in p.spans:
            if span_transform_fn is not None:
                try:
                    res = span_transform_fn(s)  # type: ignore[arg-type]
                except TypeError:
                    res = span_transform_fn(s.text)  # type: ignore[call-arg]
                if isinstance(res, TextSpan):
                    p_spans.append(res)
                    continue
                s_text = str(res) if res is not None else ""
            else:
                s_text = text_transform_fn(s.text) if s.text else ""

            p_spans.append(
                TextSpan(
                    text=s_text,
                    confidence=s.confidence,
                    bounding_box=s.bounding_box,
                    language=target_lang if target_lang is not None else s.language,
                    script=target_script if target_script is not None else s.script,
                    metadata=dict(s.metadata),
                )
            )

        if reconstruct_text_from_spans and p_spans:
            has_p_idx = any(s.metadata and "paragraph_index" in s.metadata for s in p_spans)
            if has_p_idx:
                p_groups: dict[int, list[str]] = {}
                for s in p_spans:
                    idx = s.metadata.get("paragraph_index", 0) if s.metadata else 0
                    p_groups.setdefault(idx, []).append(s.text)
                p_text = "\n".join("".join(parts).strip() for parts in p_groups.values() if "".join(parts).strip())
            else:
                p_text = "".join(s.text for s in p_spans)
        else:
            p_text = text_transform_fn(p.text) if p.text else ""

        converted_pages.append(
            PageData(
                page_number=p.page_number,
                text=p_text,
                spans=tuple(p_spans),
                tables=tuple(p_page_tables),
                metadata=p.metadata,
            )
        )

    if reconstruct_text_from_spans and any(p.spans for p in converted_pages):
        new_text = "\n".join(p.text for p in converted_pages if p.text)
    elif doc.text and doc.text.strip():
        new_text = text_transform_fn(doc.text)
    elif converted_tables:
        table_lines = []
        for t in converted_tables:
            if t.headers:
                table_lines.append(" ".join(str(c) for c in t.headers))
            for r in t.rows:
                table_lines.append(" ".join(str(c) for c in r))
        new_text = "\n".join(table_lines)
    elif converted_pages:
        new_text = "\n".join(p.text for p in converted_pages if p.text)
    else:
        new_text = ""

    # Multi-page table aggregation (Finding 13): preserve tables from all pages if doc-level tables were empty
    if converted_tables:
        all_doc_tables = tuple(converted_tables)
    elif converted_pages:
        all_doc_tables = tuple(tbl for cp in converted_pages for tbl in cp.tables)
    else:
        all_doc_tables = ()

    return CanonicalDocument(
        document_id=doc.document_id,
        source_input_id=doc.source_input_id,
        text=new_text,
        pages=tuple(converted_pages),
        tables=all_doc_tables,
        detected_type=detected_type,
        metadata=doc.metadata,
    )
