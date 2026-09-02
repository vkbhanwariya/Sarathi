"""Darshana — Safe Bounded Content Identification.

Produces typed factual identification evidence from byte signatures and content structure.
Uses a fixed bounded read size to inspect headers without loading full files into memory.
Does not extract content, run OCR, convert fonts, translate, or make business classification decisions.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import BinaryIO

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import InputRef, Request
from sarathi.shakti.darshana.facts import IdentificationFacts

_HEADER_READ_SIZE = 8192

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_TIFF_LE_MAGIC = b"II*\x00"
_TIFF_BE_MAGIC = b"MM\x00*"
_BMP_MAGIC = b"BM"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"

_EXCEL_STREAM_PATTERNS = (
    b"Workbook",
    b"Book",
    b"\x09\x08\x08\x00",  # BIFF8 BOF
    b"\x09\x08\x02\x00",  # BIFF5 BOF
    b"\x09\x04\x06\x00",  # BIFF4 BOF
    b"\x09\x02\x06\x00",  # BIFF2 BOF
)

_HTML_TAG_REGEX = re.compile(rb"<\s*(html|!doctype\s+html|head|body|table|tr|td|th)\b", re.IGNORECASE)
_HTML_TABLE_REGEX = re.compile(rb"<\s*table[^>]*>", re.IGNORECASE)
_SPREADSHEET_ML_REGEX = re.compile(
    rb"(urn:schemas-microsoft-com:office:spreadsheet|<\s*Workbook[^>]*xmlns[^>]*spreadsheet)",
    re.IGNORECASE,
)
_XML_PROLOG_REGEX = re.compile(rb"^\s*<\?xml\b", re.IGNORECASE)


def identify_file(path: Path | str) -> IdentificationFacts:
    """Identify a file from its content bytes using fixed safe bounded header inspection.

    Reads only the initial fixed header chunk (_HEADER_READ_SIZE) without loading
    the full file into memory. Filename extension is only a secondary hint.

    Args:
        path: Path to the target file.

    Returns:
        Typed IdentificationFacts describing the measured content characteristics.

    Raises:
        TypeError: If path is not a Path or str.
        DoshError(FailureCode.VALIDATION_FAILED): If file does not exist or is not a regular file.
        DoshError(FailureCode.EXECUTION_FAILED): On filesystem read errors.
    """
    if not isinstance(path, (Path, str)):
        raise TypeError(f"path must be a Path or str, got {type(path).__name__}.")

    target_path = Path(path)
    if not target_path.exists():
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Target file for identification does not exist.",
        )
    if not target_path.is_file():
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Target path for identification is not a regular file.",
        )

    ext_hint = target_path.suffix.lstrip(".").lower() if target_path.suffix else None

    try:
        with target_path.open("rb") as f:
            header_bytes = f.read(_HEADER_READ_SIZE)
            if header_bytes.startswith(_ZIP_MAGIC):
                f.seek(0)
                return _identify_zip_stream(f, ext_hint=ext_hint)
    except OSError as err:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Failed to read file for content identification.",
        ) from err

    return identify_bytes(header_bytes, extension_hint=ext_hint)


def identify_bytes(data: bytes | bytearray, *, extension_hint: str | None = None) -> IdentificationFacts:
    """Identify content format directly from safe byte evidence.

    Filename extension is only a hint; byte evidence always wins.

    Args:
        data: Initial byte chunk of the content.
        extension_hint: Optional extension hint (e.g. 'pdf', 'csv').

    Returns:
        Typed IdentificationFacts.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"data must be bytes or bytearray, got {type(data).__name__}.")

    clean_bytes = bytes(data)[:_HEADER_READ_SIZE]
    if len(clean_bytes) == 0:
        return IdentificationFacts(
            media_type="application/octet-stream",
            format_name="empty",
            is_binary=False,
            extension_hint=extension_hint,
        )

    # 1. PDF Detection (%PDF- within initial 1024 bytes)
    sample_1k = clean_bytes[:1024]
    if _PDF_MAGIC in sample_1k:
        return IdentificationFacts(
            media_type="application/pdf",
            format_name="pdf",
            is_binary=True,
            byte_signature="%PDF-",
            extension_hint=extension_hint,
        )

    # 2. Image formats
    if clean_bytes.startswith(_PNG_MAGIC):
        return IdentificationFacts(
            media_type="image/png",
            format_name="png",
            is_binary=True,
            byte_signature="PNG",
            extension_hint=extension_hint,
        )

    if clean_bytes.startswith(_JPEG_MAGIC):
        return IdentificationFacts(
            media_type="image/jpeg",
            format_name="jpeg",
            is_binary=True,
            byte_signature="JPEG",
            extension_hint=extension_hint,
        )

    if clean_bytes.startswith(_TIFF_LE_MAGIC) or clean_bytes.startswith(_TIFF_BE_MAGIC):
        return IdentificationFacts(
            media_type="image/tiff",
            format_name="tiff",
            is_binary=True,
            byte_signature="TIFF",
            extension_hint=extension_hint,
        )

    if clean_bytes.startswith(_BMP_MAGIC):
        return IdentificationFacts(
            media_type="image/bmp",
            format_name="bmp",
            is_binary=True,
            byte_signature="BM",
            extension_hint=extension_hint,
        )

    if len(clean_bytes) >= 12 and clean_bytes.startswith(b"RIFF") and clean_bytes[8:12] == b"WEBP":
        return IdentificationFacts(
            media_type="image/webp",
            format_name="webp",
            is_binary=True,
            byte_signature="WEBP",
            extension_hint=extension_hint,
        )

    # 3. OLE Compound File / Legacy Excel BIFF .xls
    # OLE magic alone proves compound container, not specifically Excel.
    # We require Excel stream / BOF signatures in the header buffer to identify as XLS.
    if clean_bytes.startswith(_OLE_MAGIC):
        if any(pat in clean_bytes for pat in _EXCEL_STREAM_PATTERNS):
            return IdentificationFacts(
                media_type="application/vnd.ms-excel",
                format_name="xls_legacy",
                is_binary=True,
                byte_signature="OLE_BIFF_XLS",
                extension_hint=extension_hint,
            )
        return IdentificationFacts(
            media_type="application/x-ole-storage",
            format_name="ole_compound",
            is_binary=True,
            byte_signature="OLE_CFB",
            extension_hint=extension_hint,
        )

    # Standalone raw BIFF stream without OLE header
    if (
        clean_bytes.startswith(b"\x09\x08")
        or clean_bytes.startswith(b"\x09\x04")
        or clean_bytes.startswith(b"\x09\x02")
    ):
        return IdentificationFacts(
            media_type="application/vnd.ms-excel",
            format_name="xls_legacy",
            is_binary=True,
            byte_signature="RAW_BIFF_XLS",
            extension_hint=extension_hint,
        )

    # 4. Zip-based OpenXML / Archive
    if clean_bytes.startswith(_ZIP_MAGIC):
        try:
            with zipfile.ZipFile(io.BytesIO(clean_bytes)) as zf:
                names = zf.namelist()
                if "[Content_Types].xml" in names:
                    if any(n.startswith("xl/") for n in names):
                        return IdentificationFacts(
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            format_name="xlsx",
                            is_binary=True,
                            byte_signature="ZIP_OPENXML_XLSX",
                            extension_hint=extension_hint,
                        )
                    if any(n.startswith("word/") for n in names):
                        return IdentificationFacts(
                            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            format_name="docx",
                            is_binary=True,
                            byte_signature="ZIP_OPENXML_DOCX",
                            extension_hint=extension_hint,
                        )
        except (zipfile.BadZipFile, EOFError):
            pass

        return IdentificationFacts(
            media_type="application/zip",
            format_name="zip",
            is_binary=True,
            byte_signature="PK_ZIP",
            extension_hint=extension_hint,
        )

    # 5. XML / SpreadsheetML / HTML Text Inspection
    sample_text = clean_bytes.lstrip()

    if _SPREADSHEET_ML_REGEX.search(sample_text):
        return IdentificationFacts(
            media_type="application/xml",
            format_name="spreadsheet_ml",
            is_binary=False,
            byte_signature="SPREADSHEET_ML",
            extension_hint=extension_hint,
        )

    if _HTML_TAG_REGEX.search(sample_text) or _HTML_TABLE_REGEX.search(sample_text):
        return IdentificationFacts(
            media_type="text/html",
            format_name="html",
            is_binary=False,
            byte_signature="HTML",
            extension_hint=extension_hint,
        )

    if _XML_PROLOG_REGEX.search(sample_text):
        return IdentificationFacts(
            media_type="application/xml",
            format_name="xml",
            is_binary=False,
            byte_signature="XML",
            extension_hint=extension_hint,
        )

    # 6. Plain Text / CSV Inspection
    is_text, encoding_hint = _verify_text_content(clean_bytes)
    if is_text:
        is_csv = _has_csv_structure(clean_bytes)
        media_type = "text/csv" if is_csv else "text/plain"
        format_name = "csv" if is_csv else "text"

        return IdentificationFacts(
            media_type=media_type,
            format_name=format_name,
            is_binary=False,
            encoding_hint=encoding_hint,
            extension_hint=extension_hint,
        )

    # 7. Unrecognized binary fallback
    return IdentificationFacts(
        media_type="application/octet-stream",
        format_name="binary",
        is_binary=True,
        extension_hint=extension_hint,
    )


def identify_input(input_ref: InputRef) -> InputRef:
    """Enrich an InputRef with verified media_type and factual identification metadata.

    Args:
        input_ref: Input reference to identify.

    Returns:
        A new InputRef carrying the verified media_type and factual metadata.

    Raises:
        TypeError: If input_ref is not an InputRef instance.
    """
    if not isinstance(input_ref, InputRef):
        raise TypeError(f"input_ref must be an InputRef instance, got {type(input_ref).__name__}.")

    facts = identify_file(input_ref.source_path)

    new_metadata = dict(input_ref.metadata)
    new_metadata["darshana_facts"] = {
        "media_type": facts.media_type,
        "format_name": facts.format_name,
        "is_binary": facts.is_binary,
        "byte_signature": facts.byte_signature,
        "encoding_hint": facts.encoding_hint,
    }

    return InputRef(
        input_id=input_ref.input_id,
        source_path=input_ref.source_path,
        display_name=input_ref.display_name,
        size_bytes=input_ref.size_bytes,
        media_type=facts.media_type,
        metadata=new_metadata,
    )


def identify_request(request: Request) -> Request:
    """Enrich a canonical Request by identifying each input via Darshana.

    Produces a new canonical Request where every input has its verified media_type
    and identification facts populated. This enriched Request enters Manthan for resolution.

    Args:
        request: The canonical processing request.

    Returns:
        A new canonical Request with all inputs identified and enriched.

    Raises:
        TypeError: If request is not a Request instance.
    """
    if not isinstance(request, Request):
        raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")

    enriched_inputs = tuple(identify_input(inp) for inp in request.inputs)

    return Request(
        request_id=request.request_id,
        requirement=request.requirement,
        inputs=enriched_inputs,
        profile=request.profile,
        custom_options=request.custom_options,
        output_root=request.output_root,
        preserve_partial=request.preserve_partial,
        cancellation_token=request.cancellation_token,
        metadata=request.metadata,
    )


def _identify_zip_stream(file_obj: BinaryIO, *, ext_hint: str | None = None) -> IdentificationFacts:
    """Bounded inspection of a seekable zip stream without uncompressing payloads."""
    try:
        with zipfile.ZipFile(file_obj) as zf:
            names = zf.namelist()
            if "[Content_Types].xml" in names:
                if any(n.startswith("xl/") for n in names):
                    return IdentificationFacts(
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        format_name="xlsx",
                        is_binary=True,
                        byte_signature="ZIP_OPENXML_XLSX",
                        extension_hint=ext_hint,
                    )
                if any(n.startswith("word/") for n in names):
                    return IdentificationFacts(
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        format_name="docx",
                        is_binary=True,
                        byte_signature="ZIP_OPENXML_DOCX",
                        extension_hint=ext_hint,
                    )
    except (zipfile.BadZipFile, EOFError):
        pass

    return IdentificationFacts(
        media_type="application/zip",
        format_name="zip",
        is_binary=True,
        byte_signature="PK_ZIP",
        extension_hint=ext_hint,
    )


def _verify_text_content(data: bytes) -> tuple[bool, str | None]:
    """Verify that bytes represent genuine text content and return proven encoding.

    Returns (is_text, encoding_hint). If not text or encoding is unproven, encoding_hint is None.
    """
    sample = data[:4096]
    if not sample:
        return False, None

    # BOM detection
    if sample.startswith(b"\xef\xbb\xbf"):
        try:
            sample[3:].decode("utf-8")
            return True, "utf-8-sig"
        except UnicodeDecodeError:
            return False, None
    if sample.startswith(b"\xff\xfe"):
        try:
            sample[2:].decode("utf-16-le")
            return True, "utf-16-le"
        except UnicodeDecodeError:
            return False, None
    if sample.startswith(b"\xfe\xff"):
        try:
            sample[2:].decode("utf-16-be")
            return True, "utf-16-be"
        except UnicodeDecodeError:
            return False, None

    # Try UTF-8 decoding
    try:
        decoded = sample.decode("utf-8")
        control_chars = sum(1 for ch in decoded if ord(ch) < 32 and ch not in "\t\n\r")
        if control_chars == 0 or control_chars / len(decoded) < 0.01:
            return True, "utf-8"
        return False, None
    except UnicodeDecodeError:
        pass

    # Try pure ASCII decoding
    try:
        decoded_ascii = sample.decode("ascii")
        control_chars = sum(1 for ch in decoded_ascii if ord(ch) < 32 and ch not in "\t\n\r")
        if control_chars == 0 or control_chars / len(decoded_ascii) < 0.01:
            return True, "ascii"
    except UnicodeDecodeError:
        pass

    return False, None


def _has_csv_structure(data: bytes) -> bool:
    """Detect if text bytes exhibit structured tabular CSV delimiters.

    Extension is only a hint and does NOT influence this decision;
    content must exhibit tabular delimiter structure across lines.
    """
    sample = data[:4096]
    lines = [line.strip() for line in sample.splitlines() if line.strip()][:10]
    if len(lines) >= 2:
        comma_counts = [line.count(b",") for line in lines]
        if comma_counts[0] > 0 and all(c == comma_counts[0] for c in comma_counts):
            return True
        tab_counts = [line.count(b"\t") for line in lines]
        if tab_counts[0] > 0 and all(t == tab_counts[0] for t in tab_counts):
            return True
        pipe_counts = [line.count(b"|") for line in lines]
        if pipe_counts[0] > 0 and all(p == pipe_counts[0] for p in pipe_counts):
            return True

    return False
