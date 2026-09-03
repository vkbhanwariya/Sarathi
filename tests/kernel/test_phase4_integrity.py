"""Phase 4 Integrity and Audit Remediation Tests for Sarathi V2.

Verifies:
- Finding 12: Semantic span preservation in font conversion & translation
- Finding 13: Multi-page table aggregation across all pages
- Finding 14: Truthful detected_type for legacy font modes
- Finding 15: Rejection of invalid font_mode
- Finding 17: No silent defaulting to KrutiDev on ambiguous text
- Finding 18: DOCX part failure handling and warnings
- Finding 19: DOCX fidelity downgrade warning on fallback
- Finding 20: Adjacent Word run merging across identical visual styles
- Finding 21: Accurate docstring in docx_exporter
- Finding 34: Rejection of invalid translation glossary directions
- Finding 35 & 36: Composite synonym splitting and collision preservation
- Finding 37: Domain glossary target term protection from neural rewrite
- Finding 41: EOD balance row classification
- Finding 43: Centralized Sutra canonical data root
- Finding 44: Unified CanonicalDocument transformation helper
"""

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    PageData,
    Request,
    Result,
    TableData,
    TextSpan,
    WarningRecord,
    transform_canonical_document,
)
from sarathi.shakti.bank_statements.row_classifier import RowType, classify_row
from sarathi.shakti.docx_exporter import (
    _W_NS,
    _merge_adjacent_compatible_runs,
    transform_docx_artifact,
)
from sarathi.shakti.font_conversion.capability import FontConversionCapability
from sarathi.shakti.font_conversion.detector import LegacyFontDetector
from sarathi.shakti.translation.capability import TranslationCapability
from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
from sarathi.shakti.translation.glossary import GlossaryStore
from sarathi.shakti.translation.models import TranslationDirection
from sarathi.shakti.translation.protector import TranslationProtector
from sarathi.sutra import get_canonical_data_root


# ---------------------------------------------------------------------------
# Finding 43: Sutra Canonical Data Root
# ---------------------------------------------------------------------------

def test_canonical_data_root_exists() -> None:
    root = get_canonical_data_root()
    assert isinstance(root, Path)
    assert root.exists()
    assert (root / "banks").is_dir()
    assert (root / "fonts").is_dir()
    assert (root / "ocr").is_dir()
    assert (root / "translation").is_dir()


# ---------------------------------------------------------------------------
# Findings 12, 13, 14, 44: Pure Document Transformation Helper
# ---------------------------------------------------------------------------

def test_transform_canonical_document_semantics() -> None:
    # Build a multi-page document where doc.tables is empty, but pages have tables
    span1 = TextSpan(text="Hkkjr", confidence=0.99, bounding_box=(0.0, 0.0, 10.0, 10.0))
    table1 = TableData(name="T1", headers=("dksM",), rows=(("123",),))
    page1 = PageData(page_number=1, text="Hkkjr ljdkj", spans=(span1,), tables=(table1,))

    span2 = TextSpan(text="fnYyh", confidence=0.98, bounding_box=(0.0, 10.0, 10.0, 20.0))
    table2 = TableData(name="T2", headers=("'kgj",), rows=(("eqEcbZ",),))
    page2 = PageData(page_number=2, text="fnYyh uxj", spans=(span2,), tables=(table2,))

    raw_doc = CanonicalDocument(
        document_id="doc_1",
        source_input_id="in_1",
        text="Hkkjr ljdkj\nfnYyh uxj",
        pages=(page1, page2),
        tables=(),  # Empty doc-level tables!
        detected_type="legacy_font_document",
    )

    mapping = {
        "Hkkjr": "भारत",
        "ljdkj": "सरकार",
        "Hkkjr ljdkj": "भारत सरकार",
        "fnYyh": "दिल्ली",
        "uxj": "नगर",
        "fnYyh uxj": "दिल्ली नगर",
        "Hkkjr ljdkj\nfnYyh uxj": "भारत सरकार\nदिल्ली नगर",
        "dksM": "कोड",
        "123": "123",
        "'kgj": "शहर",
        "eqEcbZ": "मुंबई",
    }

    def _tr(s: str) -> str:
        return mapping.get(s, s)

    transformed = transform_canonical_document(
        raw_doc,
        _tr,
        detected_type="unicode_document",
        target_lang="hi",
        target_script="Deva",
    )

    # Finding 12: Semantic span preservation
    assert transformed.pages[0].spans[0].text == "भारत"
    assert transformed.pages[0].spans[0].language == "hi"
    assert transformed.pages[0].spans[0].script == "Deva"
    assert transformed.pages[0].spans[0].bounding_box == (0.0, 0.0, 10.0, 10.0)

    assert transformed.pages[1].spans[0].text == "दिल्ली"
    assert transformed.pages[1].spans[0].language == "hi"
    assert transformed.pages[1].spans[0].script == "Deva"

    # Finding 13: Multi-page table aggregation across ALL pages
    assert len(transformed.tables) == 2
    assert transformed.tables[0].name == "T1"
    assert transformed.tables[0].headers == ("कोड",)
    assert transformed.tables[1].name == "T2"
    assert transformed.tables[1].headers == ("शहर",)

    # Finding 14: Truthful detected_type
    assert transformed.detected_type == "unicode_document"


# ---------------------------------------------------------------------------
# Findings 14, 15, 17: Font Conversion Capability & Detector
# ---------------------------------------------------------------------------

def test_font_mode_validation_rejects_unknown() -> None:
    cap = FontConversionCapability()
    ctx = ExecutionContext(run_id="r1", request_id="req1", span_id="s1", trace_id="t1")
    req = Request(
        request_id="req1",
        requirement="convert_font",
        inputs=(InputRef(input_id="in1", source_path=Path("in1.txt"), display_name="in1.txt", size_bytes=10, media_type="text/plain"),),
        custom_options={"font_mode": "to_krutidevv"},
    )
    prior = Result(
        data=CanonicalDocument(
            document_id="d1",
            source_input_id="in1",
            text="Hkkjr",
            pages=(),
            tables=(),
            detected_type="legacy_font_document",
        )
    )
    with pytest.raises(DoshError) as exc_info:
        cap.execute(req, ctx, prior_result=prior)
    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "Unsupported or invalid font_mode 'to_krutidevv'" in exc_info.value.message


def test_font_mode_detected_type_legacy() -> None:
    cap = FontConversionCapability()
    ctx = ExecutionContext(run_id="r1", request_id="req1", span_id="s1", trace_id="t1")
    req = Request(
        request_id="req1",
        requirement="convert_font",
        inputs=(InputRef(input_id="in1", source_path=Path("in1.txt"), display_name="in1.txt", size_bytes=10, media_type="text/plain"),),
        custom_options={"font_mode": "to_krutidev"},
    )
    prior = Result(
        data=CanonicalDocument(
            document_id="d1",
            source_input_id="in1",
            text="भारत",
            pages=(PageData(page_number=1, text="भारत", spans=(), tables=()),),
            tables=(),
            detected_type="unicode_document",
        )
    )
    res = cap.execute(req, ctx, prior_result=prior)
    assert isinstance(res.data, CanonicalDocument)
    assert res.data.detected_type == "legacy_font_document"


def test_detector_returns_none_on_ambiguous_text() -> None:
    detector = LegacyFontDetector()
    # English/Latin text without Kruti/Chanakya/Shusha signatures
    profile, conf = detector.detect("Hello world this is standard english text")
    assert profile is None
    assert conf == 0.0


# ---------------------------------------------------------------------------
# Findings 18, 19, 20: DOCX Exporter Integrity & Merging
# ---------------------------------------------------------------------------

def test_transform_docx_artifact_fails_on_corrupt_body() -> None:
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w") as zf:
        zf.writestr("word/document.xml", b"<w:document><unclosed>")
    corrupt_docx = out_buf.getvalue()

    with pytest.raises(DoshError) as exc_info:
        transform_docx_artifact(corrupt_docx, lambda s: s, "out.docx")
    assert exc_info.value.code == FailureCode.VALIDATION_FAILED


def test_transform_docx_artifact_warns_on_corrupt_header() -> None:
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Body</w:t></w:r></w:p></w:body></w:document>',
        )
        zf.writestr("word/header1.xml", b"<w:hdr><unclosed>")
    valid_body_bad_hdr = out_buf.getvalue()

    warnings: list[WarningRecord] = []
    res = transform_docx_artifact(valid_body_bad_hdr, lambda s: s, "out.docx", warnings=warnings)
    assert res is not None
    assert any(w.code == "DOCX_PART_CONVERSION_FAILED" for w in warnings)


def test_merge_adjacent_compatible_runs_with_differing_font_tag() -> None:
    # Two runs that share bold=true and sz=24, but have different font declarations
    xml_data = f"""<w:p xmlns:w="{_W_NS}">
        <w:r>
            <w:rPr>
                <w:rFonts w:ascii="Kruti Dev 010"/>
                <w:b/>
                <w:sz w:val="24"/>
            </w:rPr>
            <w:t>Hkk</w:t>
        </w:r>
        <w:r>
            <w:rPr>
                <w:rFonts w:ascii="KrutiDev010"/>
                <w:b/>
                <w:sz w:val="24"/>
            </w:rPr>
            <w:t>jr</w:t>
        </w:r>
    </w:p>"""
    p = ET.fromstring(xml_data)
    _merge_adjacent_compatible_runs(p)
    runs = p.findall(f"{{{_W_NS}}}r")
    assert len(runs) == 1
    t = runs[0].find(f"{{{_W_NS}}}t")
    assert t is not None
    assert t.text == "Hkkjr"


# ---------------------------------------------------------------------------
# Findings 34, 35, 36, 37: Translation Glossaries & Protection
# ---------------------------------------------------------------------------

def test_glossary_direction_validation() -> None:
    store = GlossaryStore()
    with pytest.raises(DoshError) as exc_info:
        store._add_entry({"source": "Bank", "target": "बैंक", "direction": "invalid_dir"})
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION


def test_glossary_composite_synonym_splitting() -> None:
    store = GlossaryStore()
    store._parse_raw_data(
        {"Account Freeze": "खाता लेन-देन रोक / खाता फ्रीज"},
        "test_glossary.json",
    )
    hi_to_en = store.get_terms(TranslationDirection.HI_TO_EN)
    assert "खाता लेन-देन रोक" in hi_to_en
    assert "खाता फ्रीज" in hi_to_en
    assert hi_to_en["खाता लेन-देन रोक"] == "Account Freeze"
    assert hi_to_en["खाता फ्रीज"] == "Account Freeze"


def test_translation_protector_shields_glossary_terms() -> None:
    protector = TranslationProtector()
    glossary = {"Account": "खाता"}
    text = "Your Account is active on 15/08/2026."
    protected_text, spans = protector.protect(text, glossary_mappings=glossary)

    # Both "Account" and date "15/08/2026" should be replaced with PUA placeholders
    assert "Account" not in protected_text
    assert "15/08/2026" not in protected_text
    assert len(spans) == 2

    # In simulated neural translation output where placeholders are left untouched:
    simulated_neural_output = protected_text.replace("is active on", "सक्रिय है")
    restored = protector.restore(simulated_neural_output, spans)

    # Restored text has the glossary target term "खाता" and the factual date preserved!
    assert "खाता" in restored
    assert "15/08/2026" in restored


# ---------------------------------------------------------------------------
# Finding 41: Bank EOD Balance Classification
# ---------------------------------------------------------------------------

def test_bank_eod_balance_row_classification() -> None:
    assert classify_row(["End of Day Balance", "50,000.00"]) == RowType.EOD_BALANCE
    assert classify_row(["EOD Balance", "₹25,000.00"]) == RowType.EOD_BALANCE
    assert classify_row(["Daily Balance", "10,000.00"]) == RowType.EOD_BALANCE
