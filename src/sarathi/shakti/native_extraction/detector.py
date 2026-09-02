"""Actual content format detection for Shruti Native Extraction."""

from __future__ import annotations

import re
import zipfile
from enum import Enum
from pathlib import Path


class DetectedFormat(Enum):
    PDF = "pdf"
    XLSX = "xlsx"
    XLS_LEGACY = "xls_legacy"
    HTML_TABLE = "html_table"
    SPREADSHEET_ML = "spreadsheet_ml"
    CSV_OR_TEXT = "csv_or_text"
    UNKNOWN = "unknown"


# Signatures and patterns
_PDF_MAGIC = b"%PDF-"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"

_HTML_TABLE_REGEX = re.compile(rb"<\s*table[^>]*>", re.IGNORECASE)
_HTML_TAG_REGEX = re.compile(rb"<\s*(html|doctype|head|body|table|tr|td|th)\b", re.IGNORECASE)
_SPREADSHEET_ML_REGEX = re.compile(
    rb"(urn:schemas-microsoft-com:office:spreadsheet|<\s*Workbook[^>]*xmlns[^>]*spreadsheet)",
    re.IGNORECASE,
)
_XML_PROLOG_REGEX = re.compile(rb"^\s*<\?xml\b", re.IGNORECASE)


def detect_content_format(data: bytes, file_path: Path | None = None) -> DetectedFormat:
    """Detect the actual content format using initial bytes, structure, and signatures.

    File extensions are only consulted as secondary hints after byte inspection.
    """
    if not data or len(data) == 0:
        return DetectedFormat.UNKNOWN

    # 1. PDF detection (%PDF- in first 1024 bytes)
    header_1k = data[:1024]
    if _PDF_MAGIC in header_1k:
        return DetectedFormat.PDF

    # 2. OLE / Legacy BIFF .xls detection
    if data.startswith(_OLE_MAGIC) or data.startswith(b"\x09\x08"):
        return DetectedFormat.XLS_LEGACY

    # 3. ZIP / XLSX / XLSM detection
    if data.startswith(_ZIP_MAGIC):
        try:
            import io

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                namelist = zf.namelist()
                if "[Content_Types].xml" in namelist and any(
                    "xl/workbook" in name or "xl/worksheets" in name for name in namelist
                ):
                    return DetectedFormat.XLSX
                # If it's a generic zip without spreadsheet structure, treat as unknown
        except zipfile.BadZipFile:
            pass

    # 4. XML / HTML inspection on text-like signatures
    sample_text = data[:8192].lstrip()

    # SpreadsheetML XML inspection
    if _SPREADSHEET_ML_REGEX.search(sample_text):
        return DetectedFormat.SPREADSHEET_ML

    # HTML table inspection (e.g. HTML disguised as .xls or web table export)
    if _HTML_TABLE_REGEX.search(sample_text) and _HTML_TAG_REGEX.search(sample_text):
        return DetectedFormat.HTML_TABLE

    # Generic HTML document without table
    if _HTML_TAG_REGEX.search(sample_text):
        return DetectedFormat.HTML_TABLE

    # 5. Plain text or CSV detection
    # If the bytes are valid printable text or UTF-8 / ASCII / UTF-16
    if _is_text_content(data):
        return DetectedFormat.CSV_OR_TEXT

    return DetectedFormat.UNKNOWN


def _is_text_content(data: bytes) -> bool:
    """Check whether bytes represent printable textual/CSV data without high ratio of control bytes."""
    sample = data[:4096]
    # Check for UTF-8 / ASCII BOMs
    if sample.startswith(b"\xef\xbb\xbf") or sample.startswith(b"\xff\xfe") or sample.startswith(b"\xfe\xff"):
        return True

    # Reject if too many null bytes (binary indicator)
    null_count = sample.count(b"\x00")
    if null_count > len(sample) * 0.1 and len(sample) > 10:
        return False

    # Check for common text delimiters and printable ASCII/UTF-8 characters
    printable_count = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b <= 126 or b >= 128)
    return printable_count >= len(sample) * 0.85
