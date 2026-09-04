"""Tests for Mapping Coverage, Residual Legacy Glyph Detection, and Devanagari Structural Validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result
from sarathi.shakti.font_conversion.capability import FontConversionCapability
from sarathi.shakti.font_conversion.detector import load_font_profiles
from sarathi.shakti.font_conversion.validator import (
    calculate_mapping_coverage,
    validate_devanagari_structure,
)


def test_calculate_mapping_coverage() -> None:
    """Verify mapping coverage correctly measures mapped vs unmapped character tokens."""
    profiles = load_font_profiles()
    kruti = profiles["krutidev010"]

    # Fully mapped legacy text: "Hkkjr ljdkj"
    full_metrics = calculate_mapping_coverage("Hkkjr ljdkj", kruti)
    assert full_metrics.mapping_coverage > 0.95
    assert full_metrics.unmapped_tokens == 0

    # Unmapped foreign tokens mixed in: e.g. Chinese characters
    mixed_metrics = calculate_mapping_coverage("Hkkjr 漢字", kruti)
    assert mixed_metrics.mapping_coverage < 0.95
    assert mixed_metrics.unmapped_tokens > 0


def test_structural_validation_orphan_halants() -> None:
    """Verify validator detects orphan halants/virama at boundary."""
    # Orphan halant at word start
    valid, defects = validate_devanagari_structure("्क")
    assert not valid
    assert "ORPHAN_MATRA_OR_VIRAMA_AT_BOUNDARY" in defects

    # Orphan halant followed by space
    valid2, defects2 = validate_devanagari_structure("क् ा")
    assert not valid2
    assert "ORPHAN_MATRA_OR_VIRAMA_AT_BOUNDARY" in defects2


def test_structural_validation_double_matras() -> None:
    """Verify validator detects consecutive conflicting vowel signs (double matras)."""
    valid, defects = validate_devanagari_structure("काा")
    assert not valid
    assert "CONSECUTIVE_DEPENDENT_MATRAS" in defects

    valid2, defects2 = validate_devanagari_structure("केै")
    assert not valid2
    assert "CONSECUTIVE_DEPENDENT_MATRAS" in defects2


def test_structural_validation_orphan_matras() -> None:
    """Verify validator detects vowel signs (matras) occurring without preceding base consonant."""
    valid, defects = validate_devanagari_structure("ाक")
    assert not valid
    assert "ORPHAN_MATRA_OR_VIRAMA_AT_BOUNDARY" in defects


def test_structural_defect_blocks_clean_success_in_capability() -> None:
    """Verify capability raises classified DoshError when converted text has structural defects."""
    cap = FontConversionCapability()

    # Legacy text with valid KrutiDev signature 'Hk' plus consecutive double matras 'dkk' -> 'काा'
    defect_legacy_text = "Hkkjr dkk"
    doc = CanonicalDocument(
        document_id="doc-defect",
        source_input_id="inp-defect",
        text=defect_legacy_text,
    )
    req = Request(
        request_id="req-defect",
        requirement="font_conversion",
        inputs=(InputRef("inp-defect", Path("sample.txt"), "sample.txt", 10),),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-def", "req-def", "t-def", "s-def")

    with pytest.raises(DoshError) as exc_info:
        cap.execute(req, ctx, prior_result=Result(data=doc))

    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "structural Devanagari defect" in exc_info.value.message


def test_residual_legacy_glyph_detection() -> None:
    """Verify validator flags untranslated legacy KrutiDev/DevLys glyphs like ñ, ò, ú, etc."""
    residual_text = "भारत ñ सरकार"
    valid, defects = validate_devanagari_structure(residual_text)
    assert not valid
    assert any("RESIDUAL_LEGACY_GLYPHS" in d for d in defects)
