"""Tests for Translation Span Protection and Restoration."""

from typing import Any

from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
from sarathi.shakti.translation.models import TranslationDirection
from sarathi.shakti.translation.protector import TranslationProtector


def test_factual_spans_and_identifiers_preserved_byte_for_byte(test_backend: Any) -> None:
    protector = TranslationProtector()
    engine = CTranslate2TranslationEngine(backend=test_backend, protector=protector)

    sample = (
        "दिनांक 15/08/2026 को खाता संख्या ACC-998811 में ₹ 1,50,000.50 जमा (100%) किए गए। "
        "विवरण https://sbi.co.in/txn तथा ईमेल contact@gov.in पर देखें।"
    )

    result = engine.translate(sample, direction=TranslationDirection.HI_TO_EN)
    translated = result.translated_text

    # Verify factual spans survive byte-for-byte
    assert "15/08/2026" in translated
    assert "ACC-998811" in translated
    assert "1,50,000.50" in translated
    assert "(100%)" in translated
    assert "https://sbi.co.in/txn" in translated
    assert "contact@gov.in" in translated


def test_span_protection_detects_corrupted_or_dropped_placeholders() -> None:
    """Verify restore_with_validation reports missing or duplicated placeholders."""
    from dataclasses import dataclass

    from sarathi.shakti.text.span_protection import BaseSpanProtector

    @dataclass
    class DummySpan:
        placeholder: str
        original_text: str

    protector = BaseSpanProtector()
    p0 = protector.format_placeholder(0)
    p1 = protector.format_placeholder(1)
    spans = [
        DummySpan(placeholder=p0, original_text="₹1000"),
        DummySpan(placeholder=p1, original_text="PAN-ABCDE1234F"),
    ]

    # Case 1: Model deleted p0 from output
    text_missing = f"The client paid and has PAN {p1}"
    restored, issues = protector.restore_with_validation(text_missing, spans)
    assert len(issues) == 1
    assert issues[0]["code"] == "PROTECTED_SPAN_MISSING"
    assert issues[0]["original_text"] == "₹1000"
    assert "PAN-ABCDE1234F" in restored

    # Case 2: Model duplicated p0 in output
    text_duplicated = f"The client paid {p0} twice: {p0}, with PAN {p1}"
    restored, issues = protector.restore_with_validation(text_duplicated, spans)
    assert len(issues) == 1
    assert issues[0]["code"] == "PROTECTED_SPAN_DUPLICATED"
    assert issues[0]["count"] == 2
    assert "₹1000 twice: ₹1000" in restored


def test_translation_protector_shields_glossary_terms() -> None:
    protector = TranslationProtector()
    glossary = {"High Court": "उच्च न्यायालय", "Supreme Court": "सर्वोच्च न्यायालय"}
    text = "The High Court issued an order to the Supreme Court."
    protected_text, spans = protector.protect(text, glossary_mappings=glossary)
    assert "High Court" not in protected_text
    assert "Supreme Court" not in protected_text
    assert len(spans) == 2


def test_translation_protector_numeric_placeholders_and_dictionary_words() -> None:
    """Verify TranslationProtector uses SentencePiece-safe numeric placeholders and ignores English words."""
    protector = TranslationProtector()

    # Verify placeholder format
    assert protector.format_placeholder(0) == "9990000"
    assert protector.format_placeholder(1) == "9990001"

    # Verify uppercase English words are NOT masked as IDs
    sample = "THE COURT ISSUED AN ORDER TO THE POLICE STATION IN DELHI REGARDING TABLE DATA."
    protected, spans = protector.protect(sample)
    assert "THE" in protected
    assert "COURT" in protected
    assert "ORDER" in protected
    assert "POLICE" in protected
    assert "TABLE" in protected
    assert len(spans) == 0

    # Verify alphanumeric IDs with numbers or hyphens ARE protected
    id_sample = "Case REF-2026, Account ACC-998811, Section 120B, DL12AB1234."
    protected_id, id_spans = protector.protect(id_sample)
    assert "REF-2026" not in protected_id
    assert "ACC-998811" not in protected_id
    assert "120B" not in protected_id
    assert "DL12AB1234" not in protected_id
    assert len(id_spans) == 4

    # Verify restoration byte-for-byte
    restored, issues = protector.restore_with_validation(protected_id, id_spans)
    assert issues == []
    assert restored == id_sample


def test_translation_protector_recovers_collapsed_digits() -> None:
    """Verify TranslationProtector recovers placeholders when NMT collapses or modifies 999 to 99."""
    from dataclasses import dataclass

    @dataclass
    class DummySpan:
        placeholder: str
        original_text: str

    protector = TranslationProtector()
    spans = [
        DummySpan(placeholder="9990003", original_text="5"),
        DummySpan(placeholder="9990004", original_text="PMLA-2002"),
    ]

    # Model collapsed 9990003 to 990003 and inserted spaces in 999 0004
    corrupted_output = "उचित कार्रवाई कर रहे हैं u/s990003of PMLA तथा नियम 9 9 9 0004 के तहत।"
    restored, issues = protector.restore_with_validation(corrupted_output, spans)

    assert issues == []
    assert "u/s5of PMLA" in restored
    assert "नियम PMLA-2002 के तहत" in restored
