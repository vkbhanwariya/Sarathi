"""Native extraction concrete format readers façade with lazy format loading."""

from __future__ import annotations

from typing import Any

__all__ = [
    "read_csv_or_text",
    "read_docx",
    "read_html_table",
    "read_pdf",
    "read_spreadsheet_ml",
    "read_xls_legacy",
    "read_xlsx",
]


def __getattr__(name: str) -> Any:
    if name == "read_csv_or_text":
        from sarathi.shakti.native_extraction.readers.delimited import read_csv_or_text

        return read_csv_or_text
    if name == "read_docx":
        from sarathi.shakti.native_extraction.readers.docx import read_docx

        return read_docx
    if name == "read_html_table":
        from sarathi.shakti.native_extraction.readers.html import read_html_table

        return read_html_table
    if name == "read_pdf":
        from sarathi.shakti.native_extraction.readers.pdf import read_pdf

        return read_pdf
    if name in ("read_spreadsheet_ml", "read_xls_legacy", "read_xlsx"):
        from sarathi.shakti.native_extraction.readers import spreadsheet

        return getattr(spreadsheet, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
