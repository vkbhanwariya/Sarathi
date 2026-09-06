"""Constants, namespaces, regex patterns, and typography defaults for OpenXML DOCX export."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

# OpenXML Namespaces
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

ET.register_namespace("w", _W_NS)
ET.register_namespace("r", _R_NS)

# Devanagari Unicode Blocks: standard Devanagari, Vedic Extensions, Devanagari Extended
_DEVANAGARI_CHAR_RE = re.compile(r"[\u0900-\u097F\u1CD0-\u1CFF\uA8E0-\uA8FF]")

# Typography constants per canonical Sarathi policy
_HINDI_FONT = "Nirmala UI"
_ENGLISH_FONT = "Times New Roman"
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
