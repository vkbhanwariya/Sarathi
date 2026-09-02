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
        return Result(data=doc, next_requirement="ocr")


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

    # 1. Verify exact execution order: read_native -> ocr -> bank_statements
    assert execution_order == ["read_native", "ocr", "bank_statements"]
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

    # 1. Verify exact execution order: read_native -> ocr -> font_conversion
    assert execution_order == ["read_native", "ocr", "font_conversion"]
    assert native_mock.call_count == 1
    assert ocr_mock.call_count == 1

    # 2. Verify converted output is CanonicalDocument with converted Unicode text
    assert isinstance(result.data, CanonicalDocument)
    doc: CanonicalDocument = result.data
    assert "भारतीय राजनीति" in doc.text


def test_generic_arbitrary_capability_continuation(tmp_path: Path) -> None:
    """Proves generic continuation with arbitrary capability IDs (no domain names hardcoded)."""
    from sarathi.sankalpa import CapabilityDeclaration, PluginInfo, SecurityDeclaration

    input_file = tmp_path / "generic_input.txt"
    input_file.write_text("generic input data", encoding="utf-8")

    execution_trace: list[str] = []

    class InitCap:
        def __init__(self) -> None:
            self.declaration = CapabilityDeclaration(
                capability_id="init_cap",
                plugin_id="plugin.init",
                version="1.0.0",
                supported_profiles=(ExecutionProfile.INSTANT,),
            )

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_trace.append("init_cap")
            return Result(data={"stage": "init_done"}, next_requirement="beta_cap")

    class AlphaCap:
        def __init__(self) -> None:
            self.declaration = CapabilityDeclaration(
                capability_id="alpha_cap",
                plugin_id="plugin.alpha",
                version="1.0.0",
                prerequisites=("init_cap",),
                supported_profiles=(ExecutionProfile.INSTANT,),
            )

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_trace.append("alpha_cap")
            return Result(data={"final_result": "alpha_completed", "prior": prior_result.data if prior_result else None})

    class BetaCap:
        def __init__(self) -> None:
            self.declaration = CapabilityDeclaration(
                capability_id="beta_cap",
                plugin_id="plugin.beta",
                version="1.0.0",
                supported_profiles=(ExecutionProfile.INSTANT,),
            )

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_trace.append("beta_cap")
            return Result(data={"beta_processed": True, "input_received": prior_result.data if prior_result else None})

    init = InitCap()
    alpha = AlphaCap()
    beta = BetaCap()

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        input_root=tmp_path / "Input",
        capabilities={
            "init_cap": init,
            "alpha_cap": alpha,
            "beta_cap": beta,
        },
    )

    req = Request(
        request_id="req-generic-cont",
        requirement="alpha_cap",
        inputs=(InputRef("inp-gen", input_file, "generic_input.txt", input_file.stat().st_size),),
        profile=ExecutionProfile.INSTANT,
    )

    result = agni.execute(req)

    assert execution_trace == ["init_cap", "beta_cap", "alpha_cap"]
    assert isinstance(result.data, dict)
    assert result.data["final_result"] == "alpha_completed"
    assert result.data["prior"]["beta_processed"] is True


def test_translation_font_conversion_continuation_e2e(tmp_path: Path) -> None:
    """Proves exact execution order: read_native -> translation -> font_conversion -> translation.

    When translation detects legacy font encoding (e.g. KrutiDev), it hands off to font_conversion
    with resume_self=True. Font conversion converts the text to Unicode, and translation resumes
    to translate the converted text. Native extraction is NOT rerun.
    """
    input_file = tmp_path / "legacy_krutidev.txt"
    input_file.write_text("Hkkjrh; jktuhfr", encoding="utf-8")  # KrutiDev for "भारतीय राजनीति"

    execution_order: list[str] = []

    class MockNativeCap:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("read_native")
            doc = CanonicalDocument(
                document_id="doc-kruti-1",
                source_input_id=request.inputs[0].input_id,
                text="Hkkjrh; jktuhfr",
                pages=(PageData(page_number=1, text="Hkkjrh; jktuhfr", tables=()),),
                tables=(),
            )
            return Result(data=doc)

    class MockFontConvCap:
        def __init__(self) -> None:
            from sarathi.shakti.font_conversion.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("font_conversion")
            # Converts KrutiDev text to Unicode
            doc = CanonicalDocument(
                document_id="doc-unicode-1",
                source_input_id=request.inputs[0].input_id,
                text="भारतीय राजनीति",
                pages=(PageData(page_number=1, text="भारतीय राजनीति", tables=()),),
                tables=(),
            )
            return Result(data=doc)

    class MockTranslationCap:
        def __init__(self) -> None:
            from sarathi.shakti.translation.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("translation")
            doc: CanonicalDocument = prior_result.data if prior_result else None  # type: ignore
            # On first invocation, detects legacy KrutiDev -> hands off to font_conversion
            if "Hkkjrh;" in doc.text:
                return Result(data=doc, next_requirement="font_conversion", resume_self=True)
            # On resumed invocation, translates the converted Unicode text
            trans_doc = CanonicalDocument(
                document_id="doc-translated-1",
                source_input_id=request.inputs[0].input_id,
                text="Indian Politics",
                pages=(PageData(page_number=1, text="Indian Politics", tables=()),),
                tables=(),
            )
            return Result(data=trans_doc)

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        capabilities={
            "read_native": MockNativeCap(),
            "font_conversion": MockFontConvCap(),
            "translation": MockTranslationCap(),
        },
    )

    req = Request(
        request_id="req-trans-roopa",
        requirement="translation",
        inputs=(InputRef("inp-1", input_file, "legacy_krutidev.txt", input_file.stat().st_size),),
    )

    res = agni.execute(req)

    # Verify exact execution sequence
    assert execution_order == ["read_native", "translation", "font_conversion", "translation"]
    assert isinstance(res.data, CanonicalDocument)
    assert res.data.text == "Indian Politics"


def test_font_conversion_ocr_continuation_e2e(tmp_path: Path) -> None:
    """Proves exact execution order: read_native -> font_conversion -> ocr -> font_conversion."""
    input_file = tmp_path / "scanned_font.pdf"
    input_file.write_bytes(b"%PDF-1.4 scanned")

    execution_order: list[str] = []

    class MockNativeEmptyCap:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("read_native")
            doc = CanonicalDocument(
                document_id="doc-empty-1",
                source_input_id=request.inputs[0].input_id,
                text="",
                pages=(PageData(page_number=1, text="", tables=()),),
                tables=(),
            )
            return Result(data=doc)

    class MockOCRCap:
        def __init__(self) -> None:
            from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("ocr")
            doc = CanonicalDocument(
                document_id="doc-ocr-1",
                source_input_id=request.inputs[0].input_id,
                text="Hkkjrh; jktuhfr",
                pages=(PageData(page_number=1, text="Hkkjrh; jktuhfr", tables=()),),
                tables=(),
            )
            return Result(data=doc)

    class MockFontConvCap:
        def __init__(self) -> None:
            from sarathi.shakti.font_conversion.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("font_conversion")
            doc: CanonicalDocument = prior_result.data if prior_result else None  # type: ignore
            if not doc.text.strip():
                return Result(data=doc, next_requirement="ocr", resume_self=True)
            conv_doc = CanonicalDocument(
                document_id="doc-conv-1",
                source_input_id=request.inputs[0].input_id,
                text="भारतीय राजनीति",
                pages=(PageData(page_number=1, text="भारतीय राजनीति", tables=()),),
                tables=(),
            )
            return Result(data=conv_doc)

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        capabilities={
            "read_native": MockNativeEmptyCap(),
            "font_conversion": MockFontConvCap(),
            "ocr": MockOCRCap(),
        },
    )

    req = Request(
        request_id="req-font-ocr",
        requirement="font_conversion",
        inputs=(InputRef("inp-1", input_file, "scanned_font.pdf", 16),),
    )

    res = agni.execute(req)

    assert execution_order == ["read_native", "font_conversion", "ocr", "font_conversion"]
    assert res.data.text == "भारतीय राजनीति"


def test_translation_ocr_continuation_e2e(tmp_path: Path) -> None:
    """Proves exact execution order: read_native -> translation -> ocr -> translation."""
    input_file = tmp_path / "scanned_trans.pdf"
    input_file.write_bytes(b"%PDF-1.4 scanned")

    execution_order: list[str] = []

    class MockNativeEmptyCap:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("read_native")
            doc = CanonicalDocument(
                document_id="doc-empty-1",
                source_input_id=request.inputs[0].input_id,
                text="",
                pages=(PageData(page_number=1, text="", tables=()),),
                tables=(),
            )
            return Result(data=doc)

    class MockOCRCap:
        def __init__(self) -> None:
            from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("ocr")
            doc = CanonicalDocument(
                document_id="doc-ocr-1",
                source_input_id=request.inputs[0].input_id,
                text="नमस्ते दुनिया",
                pages=(PageData(page_number=1, text="नमस्ते दुनिया", tables=()),),
                tables=(),
            )
            return Result(data=doc)

    class MockTranslationCap:
        def __init__(self) -> None:
            from sarathi.shakti.translation.plugin import CAPABILITY_DECLARATION
            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            execution_order.append("translation")
            doc: CanonicalDocument = prior_result.data if prior_result else None  # type: ignore
            if not doc.text.strip():
                return Result(data=doc, next_requirement="ocr", resume_self=True)
            trans_doc = CanonicalDocument(
                document_id="doc-trans-1",
                source_input_id=request.inputs[0].input_id,
                text="Hello World",
                pages=(PageData(page_number=1, text="Hello World", tables=()),),
                tables=(),
            )
            return Result(data=trans_doc)

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        capabilities={
            "read_native": MockNativeEmptyCap(),
            "translation": MockTranslationCap(),
            "ocr": MockOCRCap(),
        },
    )

    req = Request(
        request_id="req-trans-ocr",
        requirement="translation",
        inputs=(InputRef("inp-1", input_file, "scanned_trans.pdf", 16),),
    )

    res = agni.execute(req)

    assert execution_order == ["read_native", "translation", "ocr", "translation"]
    assert res.data.text == "Hello World"
