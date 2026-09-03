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


def test_krutidev_statement_vocabulary_does_not_falsely_mask_as_latin() -> None:
    """Verify Kruti Dev words with standard ASCII letters are not falsely masked as Latin words."""
    protector = TextProtector()
    converter = FontConverter()
    validator = FontConversionValidator()

    sample = (
        "c;ku foosd tSu iq= izdk'k pUn tSu mez 48 Ok\"kZ] fuoklh& ih&22] "
        "jkt vkaxu] ,u-vkj-vkbZ dkWyksuh] gYnh ?kkVh ekxZ] izrki uxj] t;iqj&302033 "
        "(Flat No.-1411, Al Kawthar Tower, Sharjah, United Arab Emirates) "
        "eksckbZy uEcj 8003178518 Jh eqds'k"
    )

    protected, spans = protector.protect(sample)
    converted = converter.convert(protected, "krutidev010")
    final_text = protector.restore(converted, spans)

    # Devanagari conversions
    assert "बयान" in final_text
    assert "विवेक" in final_text
    assert "जैन" in final_text
    assert "पुत्र" in final_text
    assert "प्रकाश" in final_text
    assert "चन्द" in final_text
    assert "उम्र" in final_text
    assert "वर्ष" in final_text
    assert "राज आंगन" in final_text
    assert "जयपुर" in final_text
    assert "श्री" in final_text
    assert "मुकेश" in final_text

    # No unmapped Kruti Dev remnants
    assert "foosd" not in final_text
    assert "tSu" not in final_text
    assert "pUn" not in final_text
    assert "mez" not in final_text
    assert "cयान" not in final_text

    # English parenthesized address preserved
    assert "Flat No.-1411, Al Kawthar Tower, Sharjah, United Arab Emirates" in final_text
    assert "8003178518" in final_text

    assert validator.validate_protection_integrity(final_text, spans) is True
