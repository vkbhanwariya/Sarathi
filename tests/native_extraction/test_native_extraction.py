"""Unit tests for Shruti — Read / Native Extraction capability."""

import io
from pathlib import Path
import sys
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
    TableData,
)
from sarathi.shakti.native_extraction import (
    CAPABILITY_DECLARATION,
    NativeExtractionCapability,
    PLUGIN_INFO,
)
import openpyxl
import pymupdf


@pytest.fixture
def capability() -> NativeExtractionCapability:
    return NativeExtractionCapability()


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        request_id="req-1",
        trace_id="tr-1",
        span_id="sp-1",
    )


class TestNativeExtraction:
    def test_pdf_native_text_and_table_extraction(
        self, capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        pdf_path = tmp_path / "sample.pdf"
        doc_pdf = pymupdf.open()
        page = doc_pdf.new_page(width=595, height=842)
        page.insert_text((72, 72), "Bank Account Statement\nAccount Number: 123456789")
        doc_pdf.save(str(pdf_path))
        doc_pdf.close()

        req = Request(
            request_id="req-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-pdf",
                    source_path=pdf_path,
                    display_name="sample.pdf",
                    size_bytes=pdf_path.stat().st_size,
                ),
            ),
        )

        res = capability.execute(req, context)
        assert isinstance(res, Result)
        assert res.next_requirement is None  # Usable text found -> no OCR needed

        doc = res.data
        assert isinstance(doc, CanonicalDocument)
        assert doc.detected_type == "pdf"
        assert len(doc.pages) == 1
        assert "Bank Account Statement" in doc.pages[0].text
        assert "123456789" in doc.pages[0].text
        assert len(doc.pages[0].spans) > 0

        # Provenance verification
        assert len(res.provenance) == 1
        prov = res.provenance[0]
        assert prov.source_input_id == "inp-pdf"
        assert prov.stage == "read_native"
        assert prov.capability_id == "read_native"
        assert prov.evidence["reader"] == "pymupdf"

    def test_actual_bytes_override_misleading_extension(
        self, capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        # Create an HTML table with an .xls extension
        misleading_file = tmp_path / "report.xls"
        html_content = """
        <html>
        <body>
            <table id="Transactions">
                <tr><th>Date</th><th>Description</th><th>Amount</th></tr>
                <tr><td>2026-01-01</td><td>Salary</td><td>50000</td></tr>
                <tr><td>2026-01-02</td><td>Rent</td><td>15000</td></tr>
            </table>
        </body>
        </html>
        """
        misleading_file.write_text(html_content, encoding="utf-8")

        req = Request(
            request_id="req-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-html-xls",
                    source_path=misleading_file,
                    display_name="report.xls",
                    size_bytes=misleading_file.stat().st_size,
                ),
            ),
        )

        res = capability.execute(req, context)
        assert res.next_requirement is None
        doc = res.data
        assert isinstance(doc, CanonicalDocument)
        assert doc.detected_type == "html_table"
        assert len(doc.tables) == 1
        table = doc.tables[0]
        assert table.name == "Transactions"
        assert table.headers == ("Date", "Description", "Amount")
        assert len(table.rows) == 2
        assert table.rows[0] == ("2026-01-01", "Salary", "50000")
        assert table.rows[1] == ("2026-01-02", "Rent", "15000")
        assert res.provenance[0].evidence["reader"] == "beautifulsoup4"

    def test_xlsx_multi_sheet_extraction_retains_all_sheets(
        self, capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        xlsx_path = tmp_path / "multi_sheet.xlsx"
        wb = openpyxl.Workbook()
        ws1 = wb.active
        ws1.title = "Summary"
        ws1.append(["Metric", "Value"])
        ws1.append(["Total", 1000])

        ws2 = wb.create_sheet(title="Details")
        ws2.append(["ID", "Item", "Cost"])
        ws2.append([1, "Hardware", 400])
        ws2.append([2, "Software", 600])

        wb.save(str(xlsx_path))
        wb.close()

        req = Request(
            request_id="req-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-xlsx",
                    source_path=xlsx_path,
                    display_name="multi_sheet.xlsx",
                    size_bytes=xlsx_path.stat().st_size,
                ),
            ),
        )

        res = capability.execute(req, context)
        assert res.next_requirement is None
        doc = res.data
        assert isinstance(doc, CanonicalDocument)
        assert doc.detected_type == "xlsx"

        # Verify ALL sheets are present, not just the first or largest
        assert len(doc.tables) == 2
        table_names = [t.name for t in doc.tables]
        assert "Summary" in table_names
        assert "Details" in table_names

        summary_tab = next(t for t in doc.tables if t.name == "Summary")
        assert summary_tab.headers == ("Metric", "Value")
        assert summary_tab.rows[0] == ("Total", 1000)

        details_tab = next(t for t in doc.tables if t.name == "Details")
        assert details_tab.headers == ("ID", "Item", "Cost")
        assert len(details_tab.rows) == 2

        # Provenance for each sheet
        assert len(res.provenance) == 2
        sheets_in_prov = [p.evidence["sheet"] for p in res.provenance]
        assert "Summary" in sheets_in_prov
        assert "Details" in sheets_in_prov

    def test_csv_encoding_recovery_and_parsing(
        self, capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        csv_path = tmp_path / "latin1.csv"
        # Write CSV encoded in latin-1 with special characters (e.g. € or accented letters)
        content = "Namn;Stad;Belopp\nMüller;München;1200\nAndré;Genève;3400\n"
        csv_path.write_bytes(content.encode("iso-8859-1"))

        req = Request(
            request_id="req-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-csv",
                    source_path=csv_path,
                    display_name="latin1.csv",
                    size_bytes=csv_path.stat().st_size,
                ),
            ),
        )

        res = capability.execute(req, context)
        assert res.next_requirement is None
        doc = res.data
        assert isinstance(doc, CanonicalDocument)
        assert doc.detected_type == "csv_or_text"
        assert len(doc.tables) == 1
        table = doc.tables[0]
        assert "Namn" in table.headers or "Müller" in str(table.rows)
        assert "München" in str(table.rows)

    def test_spreadsheet_ml_xml_extraction(
        self, capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        xml_path = tmp_path / "spreadsheet.xml"
        xml_content = """<?xml version="1.0"?>
        <?mso-application progid="Excel.Sheet"?>
        <Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
         xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
         <Worksheet ss:Name="TaxReport">
          <Table>
           <Row>
            <Cell><Data ss:Type="String">Category</Data></Cell>
            <Cell><Data ss:Type="String">Amount</Data></Cell>
           </Row>
           <Row>
            <Cell><Data ss:Type="String">GST</Data></Cell>
            <Cell><Data ss:Type="Number">1800</Data></Cell>
           </Row>
          </Table>
         </Worksheet>
        </Workbook>"""
        xml_path.write_text(xml_content, encoding="utf-8")

        req = Request(
            request_id="req-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-xml",
                    source_path=xml_path,
                    display_name="spreadsheet.xml",
                    size_bytes=xml_path.stat().st_size,
                ),
            ),
        )

        res = capability.execute(req, context)
        assert res.next_requirement is None
        doc = res.data
        assert isinstance(doc, CanonicalDocument)
        assert doc.detected_type == "spreadsheet_ml"
        assert len(doc.tables) == 1
        table = doc.tables[0]
        assert table.name == "TaxReport"
        assert table.headers == ("Category", "Amount")
        assert table.rows == (("GST", "1800"),)

    def test_empty_native_output_requests_ocr(
        self, capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        # Create a PDF with a blank page (no text stream, simulates scanned page without OCR)
        blank_pdf_path = tmp_path / "scanned_blank.pdf"
        doc_pdf = pymupdf.open()
        doc_pdf.new_page(width=595, height=842)  # No text inserted
        doc_pdf.save(str(blank_pdf_path))
        doc_pdf.close()

        req = Request(
            request_id="req-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-blank",
                    source_path=blank_pdf_path,
                    display_name="scanned_blank.pdf",
                    size_bytes=blank_pdf_path.stat().st_size,
                ),
            ),
        )

        res = capability.execute(req, context)
        # Empty text must escalate to OCR
        assert res.next_requirement == "ocr"
        assert any(w.code == "NATIVE_EXTRACTION_EMPTY" for w in res.warnings)

    def test_corrupted_file_requests_ocr(
        self, capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        corrupt_path = tmp_path / "corrupt.pdf"
        corrupt_path.write_bytes(b"%PDF-1.4\ncorrupt damaged stream %%%")

        req = Request(
            request_id="req-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-corrupt",
                    source_path=corrupt_path,
                    display_name="corrupt.pdf",
                    size_bytes=corrupt_path.stat().st_size,
                ),
            ),
        )

        res = capability.execute(req, context)
        # Corrupted input must escalate to OCR rather than crashing
        assert res.next_requirement == "ocr"

    def test_unknown_binary_content_returns_controlled_unsupported_error(
        self, capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        bin_path = tmp_path / "binary.bin"
        bin_path.write_bytes(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00>\x00")

        req = Request(
            request_id="req-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-bin",
                    source_path=bin_path,
                    display_name="binary.bin",
                    size_bytes=bin_path.stat().st_size,
                ),
            ),
        )

        with pytest.raises(DoshError) as exc_info:
            capability.execute(req, context)

        assert exc_info.value.code is FailureCode.UNSUPPORTED

    def test_no_ocr_import_and_no_fabricated_confidence(
        self, capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
    ) -> None:
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("Plain text sample", encoding="utf-8")

        req = Request(
            request_id="req-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-txt",
                    source_path=txt_path,
                    display_name="test.txt",
                    size_bytes=txt_path.stat().st_size,
                ),
            ),
        )

        res = capability.execute(req, context)
        # Confidence must be unavailable (None), not fabricated
        assert res.confidence is None

        # Verify no OCR engine modules have been imported
        forbidden_modules = {"rapidocr", "pytesseract", "tesseract", "easyocr", "paddleocr"}
        for mod in forbidden_modules:
            assert mod not in sys.modules

    def test_plugin_and_capability_declarations(self) -> None:
        assert PLUGIN_INFO.plugin_id == "shakti.native_extraction"
        assert "read_native" in PLUGIN_INFO.capabilities
        assert CAPABILITY_DECLARATION.capability_id == "read_native"
        assert CAPABILITY_DECLARATION.plugin_id == "shakti.native_extraction"
