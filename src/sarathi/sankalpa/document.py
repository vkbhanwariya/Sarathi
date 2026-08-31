"""Document Contracts for Sarathi V2.

Defines the canonical format-agnostic and domain-agnostic document representation:
- TextSpan: A localized or segmented piece of text with optional geometry/evidence.
- TableData: Tabular rows and headers extracted from a document.
- PageData: Page-level text, spans, and tables.
- CanonicalDocument: High-level document container exchanged across capabilities.

Does NOT embed PDF, OCR, spreadsheet, bank, translation, or capability-specific logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Mapping, Sequence


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
            if math.isnan(self.confidence) or math.isinf(self.confidence):
                raise ValueError(f"confidence cannot be NaN or Inf, got {self.confidence}.")
            if not (0.0 <= self.confidence <= 1.0):
                raise ValueError(f"confidence must be a ratio in range [0.0, 1.0], got {self.confidence}.")
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
