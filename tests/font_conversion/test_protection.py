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


def test_protect_unparenthesized_english_address_and_titlecase_firms() -> None:
    """Verify unparenthesized English addresses and M/s company names are protected and Devanagari structure is valid."""
    protector = TextProtector()
    converter = FontConverter()
    validator = FontConversionValidator()

    sample = (
        "esjs firkth dh daiuh M/s Tulip Global Pvt. Ltd. vkSj M/s Digi Mudra Connect "
        "Private Limited dk irk Flat No.-1411, Al Kawthar Tower, Al-Nahda, Sharjah, "
        "United Arab Emirates fLFkr edku esa gSA"
    )

    protected, spans = protector.protect(sample, is_explicit_legacy=False)
    converted = converter.convert(protected, "krutidev010")
    final_text = protector.restore(converted, spans)

    # English phrases and addresses preserved intact
    assert "M/s Tulip Global Pvt. Ltd." in final_text
    assert "M/s Digi Mudra Connect Private Limited" in final_text
    assert "Flat No.-1411, Al Kawthar Tower, Al-Nahda, Sharjah, United Arab Emirates" in final_text

    # KrutiDev converted to Devanagari
    assert "मेरे पिताजी" in final_text
    assert "कंपनी" in final_text or "कम्पनी" in final_text
    assert "स्थित" in final_text

    assert validator.validate_protection_integrity(final_text, spans) is True
    is_valid, defects = validator.validate_devanagari_structure(final_text)
    assert is_valid is True
    assert defects == []


def test_unlabelled_table_cell_with_multiline_mixed_content() -> None:
    """Verify multiline table cell with mixed English headers/rows and KrutiDev text converts cleanly."""
    from sarathi.shakti.font_conversion.capability import FontConversionCapability
    from sarathi.sankalpa import CanonicalDocument, TableData, Request, ExecutionContext, InputRef, Result

    cap = FontConversionCapability()
    req = Request(
        request_id="req-test-tbl",
        requirement="font_conversion",
        inputs=(InputRef("inp-1", "dummy.docx", "dummy.docx", 100),),
    )
    ctx = ExecutionContext("run-1", "req-1", "t-1", "s-1")

    cell_content = (
        "eSa c;ku djrk gw\xa1 fd esjs vkSj esjs ifjokj ds lnL;\n"
        "S.No. Name of Firm Key Holder Relationship with me\n"
        "1 M/s Digi Mudra Connect Pvt. Ltd. Prakash Chand Jain\n"
        "esjh lEiw.kZ tkudkjh ds fglkc ls mijksDr ds vykok"
    )
    table = TableData(name="test_table", headers=(), rows=((cell_content,),))
    doc = CanonicalDocument(
        document_id="doc-tbl",
        source_input_id="inp-1",
        text=cell_content,
        tables=(table,),
        detected_type="native_document",
    )

    res = cap.execute(req, ctx, prior_result=Result(data=(doc,)))

    conv_doc = res.data[0] if isinstance(res.data, (list, tuple)) else res.data
    conv_cell = conv_doc.tables[0].rows[0][0]
    assert "बयान करता हूँ" in conv_cell
    assert "S.No. Name of Firm Key Holder Relationship with me" in conv_cell
    assert "M/s Digi Mudra Connect Pvt. Ltd." in conv_cell
