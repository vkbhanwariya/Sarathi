"""Tests for Protected Span Masking and Restoration in Roopa."""

from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.protector import TextProtector
from sarathi.shakti.font_conversion.validator import FontConversionValidator


def test_protect_arbitrary_english_phrases_and_convert_adjacent_legacy() -> None:
    """Verify arbitrary English phrases are preserved byte-for-byte while adjacent legacy spans convert."""
    protector = TextProtector()
    converter = FontConverter()
    validator = FontConversionValidator()

    sample = (
        "Vendor Name: Hkkjr ljdkj | Invoice Number: INV-998811 | "
        "Customer Reference: REF-SBI-2026 | Payment Details: LVsV cSad | "
        "Branch Office: fnYyh"
    )

    protected, spans = protector.protect(sample)
    converted = converter.convert(protected, "krutidev010")
    final_text = protector.restore(converted, spans)

    # English phrases preserved
    assert "Vendor Name:" in final_text
    assert "Invoice Number:" in final_text
    assert "Customer Reference:" in final_text
    assert "Payment Details:" in final_text
    assert "Branch Office:" in final_text
    assert "INV-998811" in final_text
    assert "REF-SBI-2026" in final_text

    # Legacy spans converted
    assert "भारत सरकार" in final_text
    assert "स्टेट बैंक" in final_text
    assert "दिल्ली" in final_text

    assert validator.validate_protection_integrity(final_text, spans) is True


def test_protect_dates_amounts_identifiers_and_unicode_devanagari() -> None:
    """Verify dates, currency amounts, identifiers, and already-Unicode Devanagari round-trip untouched."""
    protector = TextProtector()
    converter = FontConverter()
    validator = FontConversionValidator()

    sample = "दिनांक 15/08/2026 को ₹ 1,50,000.50 जमा (100%) ID: ACC_9988_TXN नमस्ते भारत"
    protected, spans = protector.protect(sample)
    converted = converter.convert(protected, "krutidev010")
    final_text = protector.restore(converted, spans)

    assert final_text == sample
    assert validator.validate_protection_integrity(final_text, spans) is True
