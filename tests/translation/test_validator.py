"""Tests for Post-Translation Factual-Equivalence and Quality Validator."""

from __future__ import annotations

from sarathi.shakti.translation.models import TranslationDirection
from sarathi.shakti.translation.validator import (
    extract_factual_tokens,
    validate_factual_equivalence,
)


def test_extract_factual_tokens_finds_dates_amounts_and_ids() -> None:
    text = "Order dated 15/03/2025 regarding GSTIN 27A4CPC9123M1Z9 and amount Rs. 1,50,000 to user@example.com."
    tokens = extract_factual_tokens(text)
    assert "15/03/2025" in tokens
    assert "27a4cpc9123m1z9" in tokens
    assert "150000" in tokens
    assert "user@example.com" in tokens


def test_extract_factual_tokens_normalizes_devanagari_numerals() -> None:
    text = "दिनांक १५/०३/२०२५ को १,५०,००० रुपये"
    tokens = extract_factual_tokens(text)
    assert "15/03/2025" in tokens
    assert "150000" in tokens


def test_validate_factual_equivalence_passes_when_all_facts_preserved() -> None:
    source = "दिनांक १५/०३/२०२५ को रु. १,५०,००० का भुगतान पैन ABCDE1234F में किया गया।"
    target = "On date 15/03/2025, payment of Rs. 1,50,000 was made to PAN ABCDE1234F."
    warnings = validate_factual_equivalence(source, target, direction=TranslationDirection.HI_TO_EN)
    assert len(warnings) == 0


def test_validate_factual_equivalence_flags_missing_statutory_id_or_amount() -> None:
    source = "दिनांक १५/०३/२०२५ को रु. १,५०,००० का भुगतान पैन ABCDE1234F में किया गया।"
    # Target dropped the PAN and changed the amount
    target = "On date 15/03/2025, payment was made."
    warnings = validate_factual_equivalence(source, target, direction=TranslationDirection.HI_TO_EN)
    codes = [w.code for w in warnings]
    assert "TRANSLATION_FACTUAL_DISCREPANCY" in codes
    missing_tokens = [w.context.get("token") for w in warnings if w.context]
    assert "abcde1234f" in missing_tokens
    assert "150000" in missing_tokens


def test_validate_factual_equivalence_flags_untranslated_residue() -> None:
    source = "यह एक पूरी तरह से लंबा हिंदी पाठ है जो अनुवादित नहीं हुआ।"
    # Target English is mostly untranslated Hindi script
    target = "This is a sentence containing यह एक पूरी तरह से लंबा हिंदी पाठ है जो अनुवादित नहीं हुआ।"
    warnings = validate_factual_equivalence(source, target, direction=TranslationDirection.HI_TO_EN)
    codes = [w.code for w in warnings]
    assert "UNTRANSLATED_SEGMENT_DETECTED" in codes
