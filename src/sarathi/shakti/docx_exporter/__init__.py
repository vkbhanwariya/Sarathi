"""Canonical OpenXML DOCX Document Exporter and Transformer for Sarathi Shakti.

Provides standardized bilingual document export and in-place DOCX transformation:
- Hindi (Devanagari): Nirmala UI, 12 pt (w:sz=24)
- English / Latin: Times New Roman, 12 pt (w:sz=24)
- Preserves bold, italic, shadow, alignment, tables, and headers.
"""

from __future__ import annotations

from sarathi.shakti.docx_exporter.builder import (
    _format_paragraph_xml,
    _format_run_xml,
    _format_table_xml,
    build_docx_payload,
)
from sarathi.shakti.docx_exporter.constants import (
    _DEFAULT_HALF_PT,
    _DEVANAGARI_CHAR_RE,
    _DOCX_MIME_TYPE,
    _ENGLISH_FONT,
    _HINDI_FONT,
    _NON_DELETABLE_RUN_CHILDREN,
    _R_NS,
    _W_NS,
)
from sarathi.shakti.docx_exporter.scripts import segment_text_by_script
from sarathi.shakti.docx_exporter.styles import DocxStyleResolver
from sarathi.shakti.docx_exporter.transformer import (
    _apply_font_to_rpr,
    _get_run_visual_style,
    _merge_adjacent_compatible_runs,
    _serialize_xml_preserving_namespaces,
    _transform_xml_tree,
    transform_docx_artifact,
)

__all__ = [
    "DocxStyleResolver",
    "_DEFAULT_HALF_PT",
    "_DEVANAGARI_CHAR_RE",
    "_DOCX_MIME_TYPE",
    "_ENGLISH_FONT",
    "_HINDI_FONT",
    "_NON_DELETABLE_RUN_CHILDREN",
    "_R_NS",
    "_W_NS",
    "_apply_font_to_rpr",
    "_format_paragraph_xml",
    "_format_run_xml",
    "_format_table_xml",
    "_get_run_visual_style",
    "_merge_adjacent_compatible_runs",
    "_serialize_xml_preserving_namespaces",
    "_transform_xml_tree",
    "build_docx_payload",
    "segment_text_by_script",
    "transform_docx_artifact",
]
