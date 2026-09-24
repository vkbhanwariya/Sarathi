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


def test_extract_factual_tokens_prioritized_masking_prevents_subtoken_leak() -> None:
    """Masking higher-order entities prevents their inner fragments from being double-counted."""
    text = "Visit https://portal.in/tax/2024/999 for PAN ABCDE1234F on 15/03/2025."
    tokens = extract_factual_tokens(text)
    # URL is matched as a whole
    assert "https://portal.in/tax/2024/999" in tokens
    # PAN is matched as a whole
    assert "abcde1234f" in tokens
    # Date is matched as a whole
    assert "15/03/2025" in tokens
    # URL and Date inner year 2024 / 999 must NOT be leaked as standalone numbers
    assert "2024" not in tokens
    assert "999" not in tokens
    # PAN number 1234 must NOT be leaked as a standalone number
    assert "1234" not in tokens


def test_validate_factual_equivalence_flags_percentage_discrepancy() -> None:
    source = "The tax rate is 5% on base."
    target = "The tax rate is 9% on base."
    warnings = validate_factual_equivalence(source, target)
    missing = [w.context.get("token") for w in warnings if w.context]
    assert "5%" in missing


def test_validate_factual_equivalence_flags_small_currency_discrepancy() -> None:
    source = "Handling charge is Rs. 50."
    target = "Handling charge is Rs. 75."
    warnings = validate_factual_equivalence(source, target)
    missing = [w.context.get("token") for w in warnings if w.context]
    assert "50" in missing or "₹50" in missing


def test_validate_factual_equivalence_flags_signed_number_discrepancy() -> None:
    source = "Adjustment amount is +100."
    target = "Adjustment amount is -100."
    warnings = validate_factual_equivalence(source, target)
    missing = [w.context.get("token") for w in warnings if w.context]
    assert "+100" in missing
