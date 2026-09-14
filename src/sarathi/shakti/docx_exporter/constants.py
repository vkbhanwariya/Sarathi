"""Constants, namespaces, regex patterns, and typography defaults for OpenXML DOCX export."""

from __future__ import annotations

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

_NON_DELETABLE_RUN_CHILDREN = frozenset({
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
})

__all__ = [
    "_DEFAULT_HALF_PT",
    "_DEVANAGARI_CHAR_RE",
    "_DOCX_MIME_TYPE",
    "_ENGLISH_FONT",
    "_HINDI_FONT",
    "_NON_DELETABLE_RUN_CHILDREN",
    "_R_NS",
    "_W_NS",
]
