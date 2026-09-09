"""Statutory and legal document metadata extraction capability."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import pymupdf

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    CapabilityDeclaration,
    ExecutionContext,
    ProvenanceRecord,
    Request,
    Result,
    WarningRecord,
)
from sarathi.shakti.statutory.extractor import extract_statutory_entities
from sarathi.shakti.statutory.models import StatutoryEntities
from sarathi.shakti.statutory.plugin import CAPABILITY_DECLARATION

if TYPE_CHECKING:
    from sarathi.darpana import Darpana


class StatutoryCapability:
    """Instance-owned capability for extracting statutory and legal metadata."""

    def __init__(
        self,
        declaration: CapabilityDeclaration = CAPABILITY_DECLARATION,
        darpana: Darpana | None = None,
    ) -> None:
        self.declaration: CapabilityDeclaration = declaration
        self._darpana: Darpana | None = darpana

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute statutory entity extraction on the given request and context."""
        start_time = time.monotonic()

        text_items: list[tuple[str, str]] = []  # (doc_id, text)

        # 1. Prior result handoff (e.g. from read_native or ocr)
        if prior_result is not None and prior_result.data is not None:
            if isinstance(prior_result.data, CanonicalDocument):
                text_items.append((prior_result.data.document_id, prior_result.data.text))
            elif isinstance(prior_result.data, (tuple, list)):
                for d in prior_result.data:
                    if isinstance(d, CanonicalDocument):
                        text_items.append((d.document_id, d.text))

        # 2. Standalone direct input reading
        if not text_items and request and request.inputs:
            for inp in request.inputs:
                doc_id = inp.input_id
                try:
                    data = inp.source_path.read_bytes()
                except OSError as exc:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message=f"Failed to read source file for '{doc_id}': {exc}",
                    ) from exc

                if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
                    try:
                        doc = pymupdf.open(stream=data, filetype="pdf")
                        pages_text = [p.get_text() for p in doc]
                        doc.close()
                        text_items.append((doc_id, "\n".join(pages_text)))
                    except Exception as exc:
                        raise DoshError(
                            code=FailureCode.PARSE_FAILED,
                            message=f"Failed to extract text from PDF for '{doc_id}': {exc}",
                        ) from exc
                else:
                    text_items.append((doc_id, data.decode("utf-8", errors="replace")))

        if not text_items:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="No input documents available for statutory extraction.",
            )

        extracted_docs: list[CanonicalDocument] = []
        artifacts: list[ArtifactPayload] = []
        all_warnings: list[WarningRecord] = []
        doc_types: list[str] = []

        for doc_id, text in text_items:
            entities: StatutoryEntities = extract_statutory_entities(text)
            entities_dict = entities.to_dict()
            doc_types.append(entities.doc_type.value)

            json_bytes = json.dumps(entities_dict, indent=2, ensure_ascii=False).encode("utf-8")
            stem = doc_id.rsplit(".", 1)[0]
            artifacts.append(
                ArtifactPayload(
                    intent=ArtifactIntent(
                        name=f"{stem}_statutory.json",
                        role="statutory_metadata",
                        media_type="application/json",
                    ),
                    content=json_bytes,
                )
            )

            canonical_doc = CanonicalDocument(
                document_id=doc_id,
                source_input_id=doc_id,
                detected_type=entities.doc_type.value,
                metadata={"statutory_entities": entities_dict},
            )
            extracted_docs.append(canonical_doc)

            for correction in entities.ocr_corrections:
                all_warnings.append(
                    WarningRecord(
                        code="OCR_CORRECTION_APPLIED",
                        message=correction,
                        stage="statutory",
                    )
                )

        duration_ns = int((time.monotonic() - start_time) * 1_000_000_000)
        prov = ProvenanceRecord(
            stage="statutory",
            evidence={
                "documents_processed": len(extracted_docs),
                "doc_types": doc_types,
                "duration_ns": duration_ns,
            },
        )

        return Result(
            data=tuple(extracted_docs) if len(extracted_docs) > 1 else extracted_docs[0],
            artifact_payloads=tuple(artifacts),
            provenance=(prov,),
            warnings=tuple(all_warnings),
        )
