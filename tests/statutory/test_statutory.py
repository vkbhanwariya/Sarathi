"""Tests for Statutory and Legal Document Metadata Intelligence."""

from __future__ import annotations

import json

import pytest

from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    Request,
    Result,
)
from sarathi.shakti.statutory import (
    StatutoryDocumentType,
    StatutoryProvider,
    extract_statutory_entities,
    verify_cin,
    verify_cnr,
    verify_din,
    verify_gstin,
    verify_pan,
    verify_tan,
)
from sarathi.shakti.statutory.capability import StatutoryCapability
from sarathi.shakti.statutory.checksums import calculate_gstin_check_digit
from sarathi.shakti.statutory.extractor import repair_gstin_candidate, repair_pan_candidate


class TestStatutoryChecksums:
    """Validate statutory identifier checksums and syntax rules."""

    def test_verify_pan(self) -> None:
        # Valid individual PAN (4th char P = Personal)
        assert verify_pan("ABCPE1234F")
        # Valid company PAN (4th char C = Company)
        assert verify_pan("XYZCA5678Z")
        # Invalid 4th character (D, Z not in valid entity types)
        assert not verify_pan("ABCDE1234F")
        assert not verify_pan("ABCDZ1234F")
        # Invalid length
        assert not verify_pan("ABCDE1234")
        assert not verify_pan("ABCDE12345F")
        # Invalid characters
        assert not verify_pan("12345ABCDE")
        assert not verify_pan(None)

    def test_verify_tan(self) -> None:
        assert verify_tan("DELA12345B")
        assert not verify_tan("DEL12345B")
        assert not verify_tan("DELAA12345")
        assert not verify_tan(None)

    def test_verify_gstin(self) -> None:
        # Calculate valid checksum for a sample GSTIN prefix
        prefix = "27ABCPE1234F1Z"
        check_digit = calculate_gstin_check_digit(prefix)
        assert check_digit is not None
        valid_gstin = prefix + check_digit

        assert verify_gstin(valid_gstin)

        # Corrupted checksum digit
        corrupt_check = "0" if check_digit != "0" else "1"
        assert not verify_gstin(prefix + corrupt_check)

        # Invalid state code (00 is invalid)
        assert not verify_gstin("00ABCPE1234F1Z" + check_digit)

        # 14th character must be Z
        assert not verify_gstin("27ABCPE1234F1A5")
        assert not verify_gstin(None)

    def test_verify_cin(self) -> None:
        # Valid Listed & Unlisted Indian corporate CINs
        assert verify_cin("L17110MH1973PLC019786")
        assert verify_cin("U72200DL2005PTC138842")
        assert verify_cin("U74999KA2016PTC098765")

        # Invalid state code (XX)
        assert not verify_cin("U72200XX2005PTC138842")
        # Invalid year (out of bounds)
        assert not verify_cin("U72200DL1700PTC138842")
        # Invalid ownership code (XYZ)
        assert not verify_cin("U72200DL2005XYZ138842")
        assert not verify_cin(None)

    def test_verify_cnr(self) -> None:
        assert verify_cnr("DLHC010123452026")
        assert verify_cnr("MHCC02-004567-2025")
        assert not verify_cnr("DLHC01012345")
        assert not verify_cnr(None)

    def test_verify_din(self) -> None:
        assert verify_din("01234567")
        assert not verify_din("1234567")
        assert not verify_din("012345678")
        assert not verify_din(None)


class TestOCRErrorTolerantRepairs:
    """Validate automatic repair of positional OCR confusion errors."""

    def test_repair_pan_candidate(self) -> None:
        # OCR read 'O' instead of '0' in digit position 8
        # Correct PAN: ABCPE1230F (4th=P valid entity type)
        corrupt_pan = "ABCPE123OF"  # Position 8: 'O' should be '0'
        repaired, changed = repair_pan_candidate(corrupt_pan)
        assert changed
        assert repaired == "ABCPE1230F"
        assert verify_pan(repaired)

    def test_repair_gstin_candidate(self) -> None:
        prefix = "27ABCPE1234F1Z"
        check_digit = calculate_gstin_check_digit(prefix)
        assert check_digit is not None

        # Simulate OCR reading 'O' as state code, and '2' as 'Z'
        corrupt = "O7ABCPE1234F12" + check_digit
        repaired, changed = repair_gstin_candidate(corrupt)
        assert changed
        # Should repair 1st char to 0 (making state 07) and 14th char to Z
        assert repaired[13] == "Z"


class TestStatutoryExtraction:
    """Test full statutory text extraction on realistic synthetic documents."""

    def test_extract_gst_invoice(self) -> None:
        prefix1 = "27ABCPE1234F1Z"
        ch1 = calculate_gstin_check_digit(prefix1) or "5"
        sup_gst = prefix1 + ch1

        prefix2 = "07XYZAB5678C1Z"
        ch2 = calculate_gstin_check_digit(prefix2) or "3"
        buy_gst = prefix2 + ch2

        doc_text = f"""
        TAX INVOICE
        Supplier: Acme Technologies Pvt Ltd
        GSTIN: {sup_gst}
        Invoice No: INV-2026-0891
        Date of Invoice: 15/07/2026

        Buyer Details:
        Client Solutions Ltd
        GSTIN / UIN: {buy_gst}

        HSN/SAC: 998313
        Total Taxable Value: 1,50,000.00
        CGST (9%): 13,500.00
        SGST (9%): 13,500.00
        Total Invoice Value: 1,77,000.00
        """

        entities = extract_statutory_entities(doc_text)
        assert entities.doc_type == StatutoryDocumentType.GST_INVOICE
        assert entities.confidence >= 0.90
        assert entities.gst is not None
        assert entities.gst.supplier_gstin == sup_gst
        assert entities.gst.buyer_gstin == buy_gst
        assert entities.gst.invoice_number == "INV-2026-0891"
        assert entities.gst.invoice_date == "15/07/2026"
        assert entities.gst.state_code == "27"
        assert entities.gst.supplier_pan == "ABCPE1234F"

    def test_extract_income_tax_acknowledgement(self) -> None:
        doc_text = """
        INCOME TAX DEPARTMENT - GOVERNMENT OF INDIA
        INDIAN INCOME TAX RETURN ACKNOWLEDGEMENT (ITR-V)

        Assessment Year: 2025-26
        PAN: AABCP1234C
        Name: Rajesh Sharma
        Status: Individual
        Ack No: 123456789012345
        Total Income: 12,40,000
        """

        entities = extract_statutory_entities(doc_text)
        assert entities.doc_type == StatutoryDocumentType.INCOME_TAX_ACK
        assert entities.income_tax is not None
        assert entities.income_tax.pan == "AABCP1234C"
        assert entities.income_tax.assessment_year == "2025-26"
        assert entities.income_tax.ack_number == "123456789012345"
        assert entities.income_tax.is_valid_checksum

    def test_extract_mca_filing(self) -> None:
        doc_text = """
        MINISTRY OF CORPORATE AFFAIRS
        GOVERNMENT OF INDIA
        CERTIFICATE OF INCORPORATION

        Corporate Identity Number (CIN): U72200DL2025PTC123456
        Company Name: TechNova Solutions Private Limited
        Date of Incorporation: 10/01/2025
        Director DIN: 08765432
        """

        entities = extract_statutory_entities(doc_text)
        assert entities.doc_type == StatutoryDocumentType.MCA_COI
        assert entities.mca is not None
        assert entities.mca.cin == "U72200DL2025PTC123456"
        assert entities.mca.roc_code == "DL"
        assert "08765432" in entities.mca.dins
        assert entities.mca.is_valid_checksum

    def test_extract_ecourts_order(self) -> None:
        doc_text = """
        IN THE HIGH COURT OF DELHI AT NEW DELHI
        CNR NO. DLHC010123452026

        WP(C) No. 4512 of 2026

        BHARAT PETROLEUM CORPORATION LTD
        VERSUS
        UNION OF INDIA & ORS

        BEFORE:
        HON'BLE MR. JUSTICE VIKRAMADITYA SEN, JUDGE

        ORDER:
        Notice issued. List on next hearing date.
        """

        entities = extract_statutory_entities(doc_text)
        assert entities.doc_type == StatutoryDocumentType.ECOURTS_ORDER
        assert entities.ecourts is not None
        assert entities.ecourts.cnr_number == "DLHC010123452026"
        assert entities.ecourts.court_name == "High Court of Delhi"
        assert "BHARAT PETROLEUM CORPORATION LTD" in entities.ecourts.petitioners[0]
        assert "UNION OF INDIA" in entities.ecourts.respondents[0]
        assert "VIKRAMADITYA SEN" in entities.ecourts.judges[0]

    def test_ocr_confusion_correction_audit(self) -> None:
        # Corrupt PAN with 'O' in digit position 8: "AABCP123OC" → repaired to "AABCP1230C"
        corrupt_text = "Taxpayer PAN: AABCP123OC submitted to Income Tax Dept"
        entities = extract_statutory_entities(corrupt_text)
        assert entities.income_tax is not None
        assert entities.income_tax.pan == "AABCP1230C"
        assert len(entities.ocr_corrections) > 0
        assert "AABCP1230C" in entities.ocr_corrections[0]

    def test_din_proximity_requirement(self) -> None:
        # A document mentioning Director in the header but having an unrelated 8-digit number 200 chars away
        text = """
        Board of Directors Annual Review 2026.
        Discussion held on quarterly financial metrics and upcoming roadmap.
        Ref postal dispatch order code: 87654321.
        """
        entities = extract_statutory_entities(text)
        assert "87654321" not in entities.raw_identifiers["dins"]

        # If adjacent to Director/DIN keyword, it should be extracted
        text_with_din = "Director DIN: 08765432 signed the register."
        entities_din = extract_statutory_entities(text_with_din)
        assert "08765432" in entities_din.raw_identifiers["dins"]

    def test_gstin_role_attribution_proximity(self) -> None:
        prefix1 = "07XYZAB5678C1Z"
        ch1 = calculate_gstin_check_digit(prefix1) or "3"
        buyer_gst = prefix1 + ch1

        prefix2 = "27ABCPE1234F1Z"
        ch2 = calculate_gstin_check_digit(prefix2) or "5"
        supplier_gst = prefix2 + ch2

        # Buyer listed FIRST in text
        text = f"""
        Billed To / Buyer:
        Global Tech Ltd
        GSTIN: {buyer_gst}

        Sold By / Supplier:
        Alpha Supplies Corp
        GSTIN: {supplier_gst}
        Invoice No: INV-101
        Date: 12/08/2026
        """
        entities = extract_statutory_entities(text)
        assert entities.gst is not None
        assert entities.gst.buyer_gstin == buyer_gst
        assert entities.gst.supplier_gstin == supplier_gst

    def test_bare_pan_without_tax_context_not_income_tax_ack(self) -> None:
        # An employment onboarding form with an employee PAN but no income tax filing context
        text = "Employee Personal Data Sheet. Name: John Doe. PAN: ABCPE1234F. Date of Joining: 01/01/2026."
        entities = extract_statutory_entities(text)
        assert entities.income_tax is not None
        assert entities.income_tax.pan == "ABCPE1234F"
        assert entities.doc_type == StatutoryDocumentType.UNKNOWN
        assert entities.confidence <= 0.70


class TestStatutoryCapability:
    """Test full execution of the Statutory capability."""

    def test_capability_execution(self, tmp_path: pytest.TempPathFactory) -> None:
        text_content = """
        TAX INVOICE
        GSTIN: 27ABCPE1234F1ZB
        Invoice No: INV-999
        Dated: 01/08/2026
        """
        # Create a dummy file for InputRef (required by Request contract)
        dummy_file = tmp_path / "sample_invoice.txt"
        dummy_file.write_text(text_content, encoding="utf-8")
        dummy_input = InputRef(
            input_id="sample_invoice.txt",
            source_path=dummy_file,
            display_name="sample_invoice.txt",
            size_bytes=len(text_content),
        )

        # Test 1: Execution via prior_result (from OCR or Native Extraction)
        prior_doc = CanonicalDocument(
            document_id="sample_invoice.txt",
            source_input_id="sample_invoice.txt",
            text=text_content,
        )
        prior_res = Result(
            data=prior_doc,
        )
        context = ExecutionContext(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
        )
        req = Request(
            request_id="req-1",
            requirement="statutory",
            inputs=(dummy_input,),
        )
        capability = StatutoryCapability()
        result = capability.execute(req, context, prior_result=prior_res)

        assert isinstance(result.data, CanonicalDocument)
        doc = result.data
        assert "statutory_entities" in doc.metadata

        # Verify JSON artifact was emitted
        assert len(result.artifact_payloads) == 1
        artifact = result.artifact_payloads[0]
        assert artifact.intent.name == "sample_invoice_statutory.json"
        data = json.loads(artifact.content.decode("utf-8"))
        assert data["doc_type"] == "gst_invoice"
        assert data["gst"]["invoice_number"] == "INV-999"

        # Test 2: Execution via standalone input file
        sample_file = tmp_path / "invoice.txt"
        sample_file.write_text(text_content, encoding="utf-8")
        inp = InputRef(
            input_id="inp-1",
            source_path=sample_file,
            display_name="invoice.txt",
            size_bytes=len(text_content),
        )
        req2 = Request(
            request_id="req-2",
            requirement="statutory",
            inputs=(inp,),
        )
        res2 = capability.execute(req2, context)
        assert isinstance(res2.data, CanonicalDocument)
        assert len(res2.artifact_payloads) == 1

    def test_capability_progress_callback(self, tmp_path: pytest.TempPathFactory) -> None:
        calls = []

        def dummy_cb(**kwargs):
            calls.append(kwargs)

        sample_file = tmp_path / "invoice.txt"
        sample_file.write_text("TAX INVOICE\nGSTIN: 27ABCPE1234F1ZB", encoding="utf-8")
        inp = InputRef(
            input_id="inp-cb",
            source_path=sample_file,
            display_name="invoice.txt",
            size_bytes=len(sample_file.read_bytes()),
        )
        req = Request(
            request_id="req-cb",
            requirement="statutory",
            inputs=(inp,),
            custom_options={"progress_callback": dummy_cb},
        )
        context = ExecutionContext(
            run_id="run-cb",
            request_id="req-cb",
            trace_id="tr-cb",
            span_id="sp-cb",
        )
        capability = StatutoryCapability()
        res = capability.execute(req, context)

        assert res.data is not None
        assert len(calls) == 1
        assert calls[0]["input_id"] == "inp-cb"
        assert calls[0]["stage"] == "Statutory & Legal Extraction"
        assert calls[0]["page_number"] == 1

    def test_provider_readiness(self) -> None:
        provider = StatutoryProvider()
        readiness = provider.readiness()
        assert "statutory" in readiness
        assert readiness["statutory"].ready

    def test_statutory_extraction_from_table_only_document(self) -> None:
        """Verify statutory identifiers are extracted from doc.tables when doc.text is empty."""
        from sarathi.sankalpa import TableData

        table = TableData(
            headers=("Item", "Party", "Tax Identifier"),
            rows=(
                ("Goods", "Alpha Corp", "GSTIN: 27ABCPE1234F1ZB"),
                ("Services", "Beta Person", "PAN: ABCPE1234F"),
            ),
        )
        doc = CanonicalDocument(
            document_id="doc-table-statutory",
            text="",  # Empty text, all content in table
            tables=(table,),
        )
        req = Request(
            request_id="req-tbl",
            requirement="statutory",
            inputs=(InputRef(input_id="inp-1", source_path="dummy.csv", display_name="dummy.csv", size_bytes=10),),
        )
        context = ExecutionContext(
            run_id="run-tbl",
            request_id="req-tbl",
            trace_id="tr-tbl",
            span_id="sp-tbl",
        )
        capability = StatutoryCapability()
        res = capability.execute(req, context, prior_result=Result(data=doc))
        assert res.data is not None
        assert isinstance(res.data, CanonicalDocument)
        meta = res.data.metadata.get("statutory_entities", {})
        raw_ids = meta.get("raw_identifiers", {})
        assert "27ABCPE1234F1ZB" in raw_ids.get("gstins", ())
        assert "ABCPE1234F" in raw_ids.get("pans", ())


def test_bug_S4_statutory_ocr_repair_warning() -> None:
    """S4: An ID accepted only after repair_gstin_candidate produces a WarningRecord with code

    STATUTORY_ID_OCR_REPAIRED and original/repaired values in its context.
    An unrepaired valid ID produces none.
    """
    prefix = "27ABCPE1234F1Z"
    check_digit = calculate_gstin_check_digit(prefix)
    assert check_digit is not None
    valid_gstin = prefix + check_digit

    # 1. Unrepaired valid ID produces no warning
    valid_text = f"TAX INVOICE with GSTIN: {valid_gstin}"
    entities_valid = extract_statutory_entities(valid_text)
    assert entities_valid.gst is not None
    assert entities_valid.gst.supplier_gstin == valid_gstin
    repair_warnings = [w for w in getattr(entities_valid, "warnings", ()) if w.code == "STATUTORY_ID_OCR_REPAIRED"]
    assert len(repair_warnings) == 0

    # 2. Corrupted GSTIN accepted only after repair
    prefix_07 = "07ABCPE1234F1Z"
    check_07 = calculate_gstin_check_digit(prefix_07)
    assert check_07 is not None
    corrupt_gstin = "O7ABCPE1234F12" + check_07
    repaired_expected, changed = repair_gstin_candidate(corrupt_gstin)
    assert changed
    assert verify_gstin(repaired_expected)

    corrupt_text = f"TAX INVOICE with GSTIN: {corrupt_gstin}"
    entities_repaired = extract_statutory_entities(corrupt_text)
    assert entities_repaired.gst is not None
    assert entities_repaired.gst.supplier_gstin == repaired_expected

    repair_warnings_rep = [
        w for w in getattr(entities_repaired, "warnings", ()) if w.code == "STATUTORY_ID_OCR_REPAIRED"
    ]
    assert len(repair_warnings_rep) == 1, (
        f"Expected exactly 1 STATUTORY_ID_OCR_REPAIRED warning, got {repair_warnings_rep}"
    )
    w = repair_warnings_rep[0]
    assert w.code == "STATUTORY_ID_OCR_REPAIRED"
    assert w.context.get("original") == corrupt_gstin
    assert w.context.get("repaired") == repaired_expected
