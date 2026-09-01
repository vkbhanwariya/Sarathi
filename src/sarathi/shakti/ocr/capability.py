"""Executable Capability for OCR Phase 1."""

from __future__ import annotations

from typing import Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    Capability,
    CapabilityDeclaration,
    CanonicalDocument,
    ConfidenceValue,
    ExecutionContext,
    ExecutionProfile,
    ProvenanceRecord,
    Request,
    Result,
    WarningRecord,
)
from sarathi.shakti.ocr.engine import extract_images_from_bytes, ocr_page_image
from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION


def _is_usable_document(doc: CanonicalDocument) -> bool:
    """Check whether a CanonicalDocument contains usable text or table data."""
    has_text = bool(doc.text and doc.text.strip()) or any(
        bool(p.text and p.text.strip()) for p in doc.pages
    )
    has_tables = bool(doc.tables and len(doc.tables) > 0) or any(
        bool(p.tables and len(p.tables) > 0) for p in doc.pages
    )
    return has_text or has_tables


class OCRCapability:
    """Canonical executable capability for OCR Phase 1 (Instant profile)."""

    def __init__(self, declaration: CapabilityDeclaration = CAPABILITY_DECLARATION) -> None:
        self.declaration: CapabilityDeclaration = declaration

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute RapidOCR on inputs requiring OCR, preserving existing native outputs."""
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")
        if prior_result is not None and not isinstance(prior_result, Result):
            raise TypeError(f"prior_result must be a Result instance or None, got {type(prior_result).__name__}.")

        # Validate that execution profile is supported
        if request.profile != ExecutionProfile.INSTANT:
            raise DoshError(
                code=FailureCode.UNSUPPORTED,
                message=f"Profile '{request.profile.value}' is not supported by OCR Phase 1 (Instant only).",
            )

        # Inspect prior_result for existing usable native documents
        prior_docs: dict[str, CanonicalDocument] = {}
        if prior_result is not None and prior_result.data is not None:
            if isinstance(prior_result.data, CanonicalDocument):
                prior_docs[prior_result.data.source_input_id] = prior_result.data
            elif isinstance(prior_result.data, (tuple, list)):
                for item in prior_result.data:
                    if isinstance(item, CanonicalDocument):
                        prior_docs[item.source_input_id] = item

        final_docs: list[CanonicalDocument] = []
        all_provenance: list[ProvenanceRecord] = list(prior_result.provenance) if prior_result else []
        all_warnings: list[WarningRecord] = list(prior_result.warnings) if prior_result else []

        for inp in request.inputs:
            # Check if this input was already extracted natively and is usable
            if inp.input_id in prior_docs and _is_usable_document(prior_docs[inp.input_id]):
                final_docs.append(prior_docs[inp.input_id])
                continue

            # Input requires OCR
            try:
                data = inp.source_path.read_bytes()
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Failed to read source input file.",
                ) from exc

            # Extract page images from PDF or image formats
            images = extract_images_from_bytes(data)

            if not images:
                if len(data) == 0:
                    # Empty file
                    all_warnings.append(
                        WarningRecord(
                            code="OCR_EMPTY_INPUT",
                            message="Input file is empty.",
                            stage="ocr",
                        )
                    )
                    empty_doc = CanonicalDocument(
                        document_id=f"doc-{inp.input_id}",
                        source_input_id=inp.input_id,
                        detected_type="ocr_document",
                    )
                    final_docs.append(empty_doc)
                    continue

                # Unrecognized binary format
                raise DoshError(
                    code=FailureCode.UNSUPPORTED,
                    message="Unsupported content format for OCR.",
                )

            # Perform OCR on each page image
            pages = []
            for page_idx, img in enumerate(images, 1):
                page_data, prov, _ = ocr_page_image(img, page_idx, inp.input_id)
                pages.append(page_data)
                all_provenance.append(prov)

            full_text = "\n\n".join(p.text for p in pages if p.text)
            ocr_doc = CanonicalDocument(
                document_id=f"doc-{inp.input_id}",
                source_input_id=inp.input_id,
                pages=tuple(pages),
                text=full_text,
                detected_type="ocr_document",
            )
            final_docs.append(ocr_doc)

        result_data: Any = final_docs[0] if len(final_docs) == 1 else tuple(final_docs)

        # Aggregate overall measured confidence across OCR pages
        scores: list[float] = []
        for doc in final_docs:
            for p in doc.pages:
                if "confidence" in p.metadata and isinstance(p.metadata["confidence"], (int, float)):
                    scores.append(float(p.metadata["confidence"]))

        overall_confidence: ConfidenceValue | None = None
        if scores:
            overall_confidence = ConfidenceValue(
                score=round(sum(scores) / len(scores), 4),
                method="rapidocr_mean",
                evidence={
                    "engine": "rapidocr-openvino",
                    "backend": "openvino",
                    "page_count": len(scores),
                },
            )

        return Result(
            data=result_data,
            confidence=overall_confidence,
            warnings=tuple(all_warnings),
            provenance=tuple(all_provenance),
            next_requirement=None,
        )
