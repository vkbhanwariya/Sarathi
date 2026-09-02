"""Tests for Protected Span Masking and Restoration in Roopa."""

from sarathi.shakti.font_conversion.protector import TextProtector
from sarathi.shakti.font_conversion.validator import FontConversionValidator


def test_protect_and_restore_latin_and_identifiers() -> None:
    protector = TextProtector()
    validator = FontConversionValidator()

    sample = "State Bank of India (SBI), Account: TXN-998811, Email: user@sbi.co.in, Web: https://sbi.co.in"
    protected, spans = protector.protect(sample)
    restored = protector.restore(protected, spans)

    assert restored == sample
    assert validator.validate_protection_integrity(restored, spans) is True


def test_protect_and_restore_dates_amounts_and_unicode() -> None:
    protector = TextProtector()
    validator = FontConversionValidator()

    sample = "दिनांक 01/01/2026 को ₹ 1,50,000.50 जमा (100%) नमस्ते भारत"
    protected, spans = protector.protect(sample)
    restored = protector.restore(protected, spans)

    assert restored == sample
    assert validator.validate_protection_integrity(restored, spans) is True
