"""High-performance PDF layout analysis reader leveraging the Xberg Rust engine."""

from __future__ import annotations

from pathlib import Path

from sarathi.sankalpa import (
    CanonicalDocument,
    ProvenanceRecord,
    WarningRecord,
)
from sarathi.shakti.native_extraction.readers.xberg_reader import (
    is_xberg_available,
    read_document_with_xberg,
)


def is_layout_package_available() -> bool:
    """Return True if layout engine (Xberg) is installed and operational."""
    return is_xberg_available()


def read_pdf_with_layout(
    data: bytes,
    input_id: str,
    skip_header_footer: bool = False,
    convert_legacy_fonts: bool = True,
    password: str | None = None,
    source_path: Path | str | None = None,
) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...], tuple[WarningRecord, ...]]:
    """Extract structured document content, reading order, and tables using Xberg Rust layout analysis."""
    return read_document_with_xberg(
        data=data,
        input_id=input_id,
        mime_type="application/pdf",
        skip_header_footer=skip_header_footer,
        password=password,
        source_path=source_path,
    )
