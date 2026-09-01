"""Shruti — Native Extraction Executable Capability."""

from __future__ import annotations

import csv
from typing import Any
import xml.etree.ElementTree as ET
from zipfile import BadZipFile

import openpyxl.utils.exceptions
import pymupdf
import python_calamine
import xlrd

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    Capability,
    CapabilityDeclaration,
    CanonicalDocument,
    ExecutionContext,
    ProvenanceRecord,
    Request,
    Result,
    WarningRecord,
)
from sarathi.shakti.native_extraction.detector import DetectedFormat, detect_content_format
from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.native_extraction.readers import (
    read_csv_or_text,
    read_html_table,
    read_pdf,
    read_spreadsheet_ml,
    read_xls_legacy,
    read_xlsx,
)

_PARSE_EXCEPTIONS = (
    pymupdf.FileDataError,
    pymupdf.EmptyFileError,
    openpyxl.utils.exceptions.InvalidFileException,
    BadZipFile,
    python_calamine.CalamineError,
    xlrd.biffh.XLRDError,
    ET.ParseError,
    csv.Error,
    UnicodeDecodeError,
)


class NativeExtractionCapability:
    """Canonical executable capability for Shruti Native Extraction."""

    def __init__(self, declaration: CapabilityDeclaration = CAPABILITY_DECLARATION) -> None:
        self.declaration: CapabilityDeclaration = declaration

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute byte-first native extraction across request inputs.

        Returns canonical Document/Table data on success, escalates to OCR if native
        content is empty or unreadable, and raises DoshError(FailureCode.UNSUPPORTED)
        on unsupported binary content.
        """
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")
        if prior_result is not None and not isinstance(prior_result, Result):
            raise TypeError(f"prior_result must be a Result instance or None, got {type(prior_result).__name__}.")

        extracted_docs: list[CanonicalDocument] = []
        all_provenance: list[ProvenanceRecord] = []
        all_warnings: list[WarningRecord] = []
        needs_ocr = False

        for inp in request.inputs:
            # Read input file bytes
            try:
                data = inp.source_path.read_bytes()
            except OSError as exc:
                # File I/O error or missing file
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Failed to read source input file.",
                ) from exc

            # Detect format by inspecting content bytes
            fmt = detect_content_format(data, inp.source_path)

            if fmt == DetectedFormat.UNKNOWN:
                # If file is empty, escalate to OCR
                if len(data) == 0:
                    needs_ocr = True
                    all_warnings.append(
                        WarningRecord(
                            code="EMPTY_INPUT",
                            message="Input file is empty. Escalating to OCR.",
                            stage="read_native",
                        )
                    )
                    empty_doc = CanonicalDocument(
                        document_id=f"doc-{inp.input_id}",
                        source_input_id=inp.input_id,
                    )
                    extracted_docs.append(empty_doc)
                    continue

                # Genuinely unsupported binary format
                raise DoshError(
                    code=FailureCode.UNSUPPORTED,
                    message="Unsupported content format for native extraction.",
                )

            # Route to concrete native readers with honest parse error handling
            try:
                if fmt == DetectedFormat.PDF:
                    doc, provs, warns = read_pdf(data, inp.input_id)
                elif fmt == DetectedFormat.XLSX:
                    doc, provs, warns = read_xlsx(data, inp.input_id)
                elif fmt == DetectedFormat.XLS_LEGACY:
                    doc, provs, warns = read_xls_legacy(data, inp.input_id)
                elif fmt == DetectedFormat.HTML_TABLE:
                    doc, provs, warns = read_html_table(data, inp.input_id)
                elif fmt == DetectedFormat.SPREADSHEET_ML:
                    doc, provs, warns = read_spreadsheet_ml(data, inp.input_id)
                elif fmt == DetectedFormat.CSV_OR_TEXT:
                    doc, provs, warns = read_csv_or_text(data, inp.input_id)
                else:
                    raise DoshError(
                        code=FailureCode.UNSUPPORTED,
                        message="Unsupported content format for native extraction.",
                    )

                extracted_docs.append(doc)
                all_provenance.extend(provs)
                all_warnings.extend(warns)

                # Quality check: verify whether usable text or table data exists
                has_usable_text = bool(doc.text and doc.text.strip()) or any(
                    bool(p.text and p.text.strip()) for p in doc.pages
                )
                has_usable_tables = any(
                    len(t.rows) > 0 or len(t.headers) > 0 for t in doc.tables
                ) or any(
                    any(len(t.rows) > 0 or len(t.headers) > 0 for t in p.tables) for p in doc.pages
                )

                if not has_usable_text and not has_usable_tables:
                    # Empty native content (e.g. scanned PDF with no text stream) -> escalate to OCR
                    needs_ocr = True
                    all_warnings.append(
                        WarningRecord(
                            code="NATIVE_EXTRACTION_EMPTY",
                            message="No usable native text or tables found in document. Escalating to OCR.",
                            stage="read_native",
                        )
                    )

            except DoshError:
                raise
            except _PARSE_EXCEPTIONS:
                # Corrupted or unparseable document -> escalate to OCR
                needs_ocr = True
                all_warnings.append(
                    WarningRecord(
                        code="NATIVE_PARSE_ERROR",
                        message="Failed to parse document content natively. Escalating to OCR.",
                        stage="read_native",
                    )
                )
                corrupt_doc = CanonicalDocument(
                    document_id=f"doc-{inp.input_id}",
                    source_input_id=inp.input_id,
                )
                extracted_docs.append(corrupt_doc)

        result_data: Any = extracted_docs[0] if len(extracted_docs) == 1 else tuple(extracted_docs)

        return Result(
            data=result_data,
            warnings=tuple(all_warnings),
            provenance=tuple(all_provenance),
            next_requirement="ocr" if needs_ocr else None,
        )
