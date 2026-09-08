"""Tests for Statutory and Legal Document Metadata Intelligence."""

from __future__ import annotations

import json
import pytest

from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.shakti.statutory import (
    ECourtsMetadata,
    GSTMetadata,
    IncomeTaxMetadata,
    MCAMetadata,
    StatutoryDocumentType,
    StatutoryEntities,
    StatutoryProvider,
    extract_statutory_entities,
    is_statutory_document,
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
        valid_gstin = prefix + check_digit

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

    def test_provider_readiness(self) -> None:
        provider = StatutoryProvider()
        readiness = provider.readiness()
        assert "statutory" in readiness
        assert readiness["statutory"].ready
