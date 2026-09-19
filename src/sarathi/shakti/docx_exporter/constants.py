"""Constants, namespaces, regex patterns, and typography defaults for OpenXML DOCX export."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from sarathi.shakti.text.typography import (
    DEVANAGARI_FONT as _HINDI_FONT,
)
from sarathi.shakti.text.typography import (
    DEVANAGARI_RE as _DEVANAGARI_CHAR_RE,
)
from sarathi.shakti.text.typography import (
    ENGLISH_FONT as _ENGLISH_FONT,
)

# OpenXML Namespaces
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

ET.register_namespace("w", _W_NS)
ET.register_namespace("r", _R_NS)

# Typography constants per canonical Sarathi policy
_DEFAULT_HALF_PT = 24  # 12 pt baseline

_DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_NON_DELETABLE_RUN_CHILDREN = frozenset(
    {
        "tab",
        "br",
        "cr",
        "sym",
        "drawing",
        "fldChar",
        "instrText",
        "noBreakHyphen",
        "softHyphen",
        "commentReference",
        "annotationRef",
        "footnoteReference",
        "endnoteReference",
        "lastRenderedPageBreak",
        "ptab",
        "ruby",
    }
)

_INVALID_XML_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]|[\ud800-\udfff]")
_INVALID_XML_CHARS_NO_FF_RE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\ufffe\uffff]|[\ud800-\udfff]")


def sanitize_xml_text(text: str | None, preserve_form_feed: bool = False) -> str:
    """Sanitize text to guarantee strict XML 1.0 compatibility for WordprocessingML.

    Strips null bytes, disallowed ASCII control characters (0x00-0x08, 0x0B, 0x0E-0x1F, 0xFFFE, 0xFFFF),
    and Unicode surrogate code points (0xD800-0xDFFF).
    If preserve_form_feed is False, form feed (0x0C) is also stripped.
    If preserve_form_feed is True, form feed (0x0C) is preserved so callers can convert it to <w:br w:type="page"/>.
    """
    if not text:
        return ""
    pattern = _INVALID_XML_CHARS_NO_FF_RE if preserve_form_feed else _INVALID_XML_CHARS_RE
    return pattern.sub("", text)


__all__ = [
    "_DEFAULT_HALF_PT",
    "_DEVANAGARI_CHAR_RE",
    "_DOCX_MIME_TYPE",
    "_ENGLISH_FONT",
    "_HINDI_FONT",
    "_NON_DELETABLE_RUN_CHILDREN",
    "_R_NS",
    "_W_NS",
    "sanitize_xml_text",
]
