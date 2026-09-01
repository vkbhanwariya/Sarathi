"""Comprehensive unit and adversarial tests for Darshana — Intake Identification."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    DeviceRequirement,
    DeviceType,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
    SecurityDeclaration,
)
from sarathi.shakti.darshana import (
    CAPABILITY_DECLARATION,
    DarshanaCapability,
    IdentificationFacts,
    PLUGIN_INFO,
    identify_bytes,
    identify_file,
    identify_input,
    identify_request,
)


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-001",
        request_id="req-001",
        trace_id="tr-001",
        span_id="sp-001",
        profile=ExecutionProfile.INSTANT,
    )


class TestDarshanaFactsContract:
    def test_facts_creation_and_immutability(self) -> None:
        facts = IdentificationFacts(
            media_type="application/pdf",
            format_name="pdf",
            is_binary=True,
            byte_signature="%PDF-",
            encoding_hint=None,
            extension_hint="pdf",
            metadata={"pages": 5},
        )
        assert facts.media_type == "application/pdf"
        assert facts.format_name == "pdf"
        assert facts.is_binary is True
        assert facts.byte_signature == "%PDF-"
        assert facts.extension_hint == "pdf"
        assert facts.metadata["pages"] == 5

        with pytest.raises(AttributeError):
            facts.media_type = "image/png"  # type: ignore

    def test_facts_type_validation(self) -> None:
        with pytest.raises(TypeError, match="media_type must be a string"):
            IdentificationFacts(media_type=123, format_name="pdf", is_binary=True)  # type: ignore

        with pytest.raises(TypeError, match="format_name must be a string"):
            IdentificationFacts(media_type="application/pdf", format_name=None, is_binary=True)  # type: ignore

        with pytest.raises(TypeError, match="is_binary must be a bool"):
            IdentificationFacts(media_type="application/pdf", format_name="pdf", is_binary="yes")  # type: ignore

        with pytest.raises(TypeError, match="byte_signature must be a string"):
            IdentificationFacts(media_type="application/pdf", format_name="pdf", is_binary=True, byte_signature=123)  # type: ignore


class TestContentEvidenceVsExtensionHint:
    def test_pdf_magic_wins_over_png_extension(self, tmp_path: Path) -> None:
        fake_png = tmp_path / "document.png"
        fake_png.write_bytes(b"%PDF-1.7\nSample pdf content bytes")

        facts = identify_file(fake_png)
        assert facts.media_type == "application/pdf"
        assert facts.format_name == "pdf"
        assert facts.is_binary is True
        assert facts.byte_signature == "%PDF-"
        assert facts.extension_hint == "png"

    def test_png_magic_wins_over_pdf_extension(self, tmp_path: Path) -> None:
        fake_pdf = tmp_path / "image.pdf"
        fake_pdf.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")

        facts = identify_file(fake_pdf)
        assert facts.media_type == "image/png"
        assert facts.format_name == "png"
        assert facts.is_binary is True
        assert facts.byte_signature == "PNG"
        assert facts.extension_hint == "pdf"

    def test_ordinary_text_named_csv_remains_text(self, tmp_path: Path) -> None:
        fake_csv = tmp_path / "narrative.csv"
        fake_csv.write_text("This is an ordinary narrative paragraph without any delimiters.\nSecond paragraph.\n")

        facts = identify_file(fake_csv)
        assert facts.media_type == "text/plain"
        assert facts.format_name == "text"
        assert facts.is_binary is False
        assert facts.extension_hint == "csv"

    def test_structured_csv_identified_as_csv(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("id,name,age\n1,Alice,30\n2,Bob,25\n")

        facts = identify_file(csv_file)
        assert facts.media_type == "text/csv"
        assert facts.format_name == "csv"
        assert facts.is_binary is False

    def test_generic_ole_without_excel_stream_is_not_xls(self, tmp_path: Path) -> None:
        generic_ole = tmp_path / "fake_excel.xls"
        # OLE header without Workbook / BIFF signatures
        ole_header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 500
        generic_ole.write_bytes(ole_header)

        facts = identify_file(generic_ole)
        assert facts.media_type == "application/x-ole-storage"
        assert facts.format_name == "ole_compound"
        assert facts.is_binary is True
        assert facts.extension_hint == "xls"

    def test_ole_with_workbook_stream_identified_as_xls(self, tmp_path: Path) -> None:
        real_xls = tmp_path / "sheet.xls"
        ole_with_biff = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 50 + b"Workbook" + b"\x00" * 400
        real_xls.write_bytes(ole_with_biff)

        facts = identify_file(real_xls)
        assert facts.media_type == "application/vnd.ms-excel"
        assert facts.format_name == "xls_legacy"
        assert facts.is_binary is True
        assert facts.byte_signature == "OLE_BIFF_XLS"

    def test_high_byte_binary_is_not_text(self, tmp_path: Path) -> None:
        bin_file = tmp_path / "random.bin"
        # High-byte binary data with invalid UTF-8 / control bytes
        bin_data = bytes([0x80, 0xFF, 0xFE, 0x01, 0x02, 0x88, 0x99, 0xAA, 0xBB, 0xCC] * 20)
        bin_file.write_bytes(bin_data)

        facts = identify_file(bin_file)
        assert facts.media_type == "application/octet-stream"
        assert facts.format_name == "binary"
        assert facts.is_binary is True
        assert facts.encoding_hint is None


class TestBoundedIdentification:
    def test_bounded_read_does_not_load_large_files(self, tmp_path: Path) -> None:
        large_file = tmp_path / "large.pdf"
        # Write 1 MB of zeros with PDF header
        with large_file.open("wb") as f:
            f.write(b"%PDF-1.4\n")
            f.write(b"\x00" * (1024 * 1024))

        facts = identify_file(large_file)
        assert facts.media_type == "application/pdf"
        assert facts.format_name == "pdf"


class TestRequestAndInputEnrichment:
    def test_identify_input_enriches_input_ref(self, tmp_path: Path) -> None:
        sample_file = tmp_path / "report.pdf"
        sample_file.write_bytes(b"%PDF-1.7\nSample data")

        initial_input = InputRef(
            input_id="inp-001",
            source_path=sample_file,
            display_name="report.pdf",
            size_bytes=len(sample_file.read_bytes()),
            media_type=None,
        )

        enriched = identify_input(initial_input)
        assert enriched.input_id == "inp-001"
        assert enriched.media_type == "application/pdf"
        assert "darshana_facts" in enriched.metadata
        assert enriched.metadata["darshana_facts"]["format_name"] == "pdf"

    def test_identify_request_enriches_entire_request(self, tmp_path: Path) -> None:
        file1 = tmp_path / "doc1.pdf"
        file1.write_bytes(b"%PDF-1.7\nDoc 1")
        file2 = tmp_path / "doc2.png"
        file2.write_bytes(b"\x89PNG\r\n\x1a\nDoc 2")

        inp1 = InputRef(input_id="inp-1", source_path=file1, display_name="doc1.pdf", size_bytes=file1.stat().st_size)
        inp2 = InputRef(input_id="inp-2", source_path=file2, display_name="doc2.png", size_bytes=file2.stat().st_size)

        req = Request(
            request_id="req-100",
            requirement="ocr",
            inputs=(inp1, inp2),
        )

        enriched_req = identify_request(req)
        assert enriched_req.request_id == "req-100"
        assert enriched_req.inputs[0].media_type == "application/pdf"
        assert enriched_req.inputs[1].media_type == "image/png"


class TestDarshanaCapabilityExecution:
    def test_darshana_capability_public_type_validation(self) -> None:
        cap = DarshanaCapability()

        with pytest.raises(TypeError, match="request must be a Request instance"):
            cap.execute("invalid_request", None)  # type: ignore

        req = Request(
            request_id="req-1",
            requirement="identify",
            inputs=(InputRef(input_id="i1", source_path=Path("dummy.txt"), display_name="dummy.txt", size_bytes=0),),
        )

        with pytest.raises(TypeError, match="context must be an ExecutionContext instance"):
            cap.execute(req, "invalid_context")  # type: ignore

        ctx = ExecutionContext(
            run_id="run-001",
            request_id="req-001",
            trace_id="tr-001",
            span_id="sp-001",
            profile=ExecutionProfile.INSTANT,
        )

        with pytest.raises(TypeError, match="prior_result must be a Result instance or None"):
            cap.execute(req, ctx, prior_result="not_a_result")  # type: ignore

    def test_darshana_capability_successful_execution(self, tmp_path: Path, context: ExecutionContext) -> None:
        doc_path = tmp_path / "document.pdf"
        doc_path.write_bytes(b"%PDF-1.4\nTest PDF")

        inp = InputRef(
            input_id="inp-01",
            source_path=doc_path,
            display_name="document.pdf",
            size_bytes=doc_path.stat().st_size,
        )

        req = Request(
            request_id="req-ident",
            requirement="identify",
            inputs=(inp,),
        )

        cap = DarshanaCapability()
        result = cap.execute(req, context)

        assert isinstance(result.data, tuple)
        assert len(result.data) == 1
        assert result.data[0].detected_type == "application/pdf"
        assert len(result.provenance) == 1
        assert result.provenance[0].stage == "identify"
        assert result.provenance[0].plugin_id == "shakti.darshana"
        assert result.provenance[0].capability_id == "identify"
