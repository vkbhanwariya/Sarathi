"""End-to-end integration tests for dynamic pipeline continuation on scanned inputs."""

from pathlib import Path
from decimal import Decimal
import pytest

from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    Request,
    Result,
    TableData,
)
from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult


class ScannedNativeReaderMock:
    """Simulates native extraction on scanned/image document yielding empty text and table structure."""

    def __init__(self) -> None:
        self.call_count = 0

    def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
        self.call_count += 1
        empty_page = PageData(page_number=1, text="", tables=(), metadata={"is_scanned": True})
        doc = CanonicalDocument(
            document_id=f"doc-{request.inputs[0].input_id}",
            source_input_id=request.inputs[0].input_id,
            text="",
            pages=(empty_page,),
            tables=(),
            detected_type="scanned_pdf",
        )
        return Result(data=doc)


class ScannedOCRReaderMock:
    """Simulates OCR extraction on scanned document yielding recognized text/table."""

    def __init__(self, ocr_text: str = "", tables: tuple[TableData, ...] = ()) -> None:
        self.ocr_text = ocr_text
        self.tables = tables
        self.call_count = 0

    def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
        self.call_count += 1
        page = PageData(page_number=1, text=self.ocr_text, tables=self.tables)
        doc = CanonicalDocument(
            document_id=f"doc-ocr-{request.inputs[0].input_id}",
            source_input_id=request.inputs[0].input_id,
            text=self.ocr_text,
            pages=(page,),
            tables=self.tables,
            detected_type="ocr_document",
        )
        return Result(data=doc)


def test_bank_statement_scanned_continuation_e2e(tmp_path: Path) -> None:
    """Proves exact execution order: read_native -> ocr -> bank_statements on scanned input.

    Final result must be BankStatementConsolidationResult, not intermediate OCR document.
    Native extraction must not be re-run.
    """
    input_file = tmp_path / "scanned_statement.pdf"
    input_file.write_bytes(b"%PDF-1.4 scanned dummy content")

    darpana = Darpana(capacity=1000)
    execution_order: list[str] = []

    native_mock = ScannedNativeReaderMock()
    
    ocr_table = TableData(
        name="transactions",
        headers=("Txn Date", "Description", "Debit", "Credit", "Balance"),
        rows=(
            ("Txn Date", "Description", "Debit", "Credit", "Balance"),
            ("01/08/2026", "OPENING BALANCE", "", "", "10000.00"),
            ("05/08/2026", "SALARY CREDIT", "", "50000.00", "60000.00"),
            ("10/08/2026", "ELECTRICITY BILL", "2500.00", "", "57500.00"),
            ("15/08/2026", "CLOSING BALANCE", "", "", "57500.00"),
        ),
    )
    ocr_text = "STATE BANK OF INDIA\nAccount Statement\nAccount Number: 12345678901\n"
    ocr_mock = ScannedOCRReaderMock(ocr_text=ocr_text, tables=(ocr_table,))

    from sarathi.shakti.bank_statements import BankStatementCapability

    class TrackingBankStatementCapability(BankStatementCapability):
        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("bank_statements")
            return super().execute(request, context, prior_result=prior_result)

    class TrackingNativeCapability:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("read_native")
            return native_mock.execute(request, context, prior_result)

    class TrackingOCRCapability:
        def __init__(self) -> None:
            from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("ocr")
            return ocr_mock.execute(request, context, prior_result)

    capabilities = {
        "read_native": TrackingNativeCapability(),
        "ocr": TrackingOCRCapability(),
        "bank_statements": TrackingBankStatementCapability(darpana=darpana),
    }

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        input_root=tmp_path / "Input",
        capabilities=capabilities,
        darpana=darpana,
    )

    inp = InputRef(
        input_id="inp-scanned-1",
        source_path=input_file,
        display_name="scanned_statement.pdf",
        size_bytes=input_file.stat().st_size,
    )
    req = Request(
        request_id="req-scanned-bank",
        requirement="bank_statements",
        inputs=(inp,),
        profile=ExecutionProfile.INSTANT,
    )

    result = agni.execute(req)

    # 1. Verify exact execution order: read_native -> bank_statements -> ocr -> bank_statements
    assert execution_order == ["read_native", "bank_statements", "ocr", "bank_statements"]
    assert native_mock.call_count == 1  # Not re-run!
    assert ocr_mock.call_count == 1

    # 2. Verify final output is BankStatementConsolidationResult, not OCR document
    assert isinstance(result.data, BankStatementConsolidationResult)
    consolidation: BankStatementConsolidationResult = result.data
    assert len(consolidation.statements) == 1
    stmt = consolidation.statements[0]
    assert len(stmt.transactions) == 2
    assert stmt.opening_balance == Decimal("10000.00")
    assert stmt.closing_balance == Decimal("57500.00")

    # 3. Verify committed artifacts exist
    assert any(a.path.name.endswith(".parquet") for a in result.artifacts)
    assert any(a.path.name.endswith(".xlsx") for a in result.artifacts)


def test_font_conversion_scanned_continuation_e2e(tmp_path: Path) -> None:
    """Proves exact execution order: read_native -> ocr -> font_conversion on scanned legacy font input."""
    input_file = tmp_path / "scanned_font.pdf"
    input_file.write_bytes(b"%PDF-1.4 scanned font content")

    darpana = Darpana(capacity=1000)
    execution_order: list[str] = []

    native_mock = ScannedNativeReaderMock()
    # Scanned OCR text with legacy Kruti Dev encoding characters
    ocr_text = "यह Hkkjrh; jktuhfr dk vfHkUu vax gSA"
    ocr_mock = ScannedOCRReaderMock(ocr_text=ocr_text)

    from sarathi.shakti.font_conversion import FontConversionCapability

    class TrackingFontCapability(FontConversionCapability):
        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("font_conversion")
            return super().execute(request, context, prior_result=prior_result)

    class TrackingNativeCapability:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("read_native")
            return native_mock.execute(request, context, prior_result)

    class TrackingOCRCapability:
        def __init__(self) -> None:
            from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("ocr")
            return ocr_mock.execute(request, context, prior_result)

    capabilities = {
        "read_native": TrackingNativeCapability(),
        "ocr": TrackingOCRCapability(),
        "font_conversion": TrackingFontCapability(darpana=darpana),
    }

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        input_root=tmp_path / "Input",
        capabilities=capabilities,
        darpana=darpana,
    )

    inp = InputRef(
        input_id="inp-scanned-font",
        source_path=input_file,
        display_name="scanned_font.pdf",
        size_bytes=input_file.stat().st_size,
    )
    req = Request(
        request_id="req-scanned-font",
        requirement="font_conversion",
        inputs=(inp,),
        profile=ExecutionProfile.INSTANT,
    )

    result = agni.execute(req)

    # 1. Verify exact execution order: read_native -> font_conversion -> ocr -> font_conversion
    assert execution_order == ["read_native", "font_conversion", "ocr", "font_conversion"]
    assert native_mock.call_count == 1
    assert ocr_mock.call_count == 1

    # 2. Verify converted output is CanonicalDocument with converted Unicode text
    assert isinstance(result.data, CanonicalDocument)
    doc: CanonicalDocument = result.data
    assert "भारतीय राजनीति" in doc.text
