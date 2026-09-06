"""Native extraction concrete format readers façade."""

from __future__ import annotations

from sarathi.shakti.native_extraction.readers.delimited import read_csv_or_text
from sarathi.shakti.native_extraction.readers.docx import read_docx
from sarathi.shakti.native_extraction.readers.html import read_html_table
from sarathi.shakti.native_extraction.readers.pdf import read_pdf
from sarathi.shakti.native_extraction.readers.spreadsheet import (
    read_spreadsheet_ml,
    read_xls_legacy,
    read_xlsx,
)

__all__ = [
    "read_csv_or_text",
    "read_docx",
    "read_html_table",
    "read_pdf",
    "read_spreadsheet_ml",
    "read_xls_legacy",
    "read_xlsx",
]
