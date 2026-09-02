"""Executable Capability for Darshana Intake Identification."""

from __future__ import annotations

from sarathi.sankalpa import (
    CanonicalDocument,
    CapabilityDeclaration,
    ExecutionContext,
    ProvenanceRecord,
    Request,
    Result,
)
from sarathi.shakti.darshana.identifier import identify_file
from sarathi.shakti.darshana.plugin import CAPABILITY_DECLARATION


class DarshanaCapability:
    """Canonical executable capability for Darshana Intake Identification."""

    def __init__(
        self,
        declaration: CapabilityDeclaration = CAPABILITY_DECLARATION,
    ) -> None:
        if not isinstance(declaration, CapabilityDeclaration):
            raise TypeError(f"declaration must be a CapabilityDeclaration, got {type(declaration).__name__}.")
        self.declaration: CapabilityDeclaration = declaration

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute intake identification on request inputs.

        Validates all public boundary arguments before inspecting inputs or filesystem.

        Args:
            request: Processing request.
            context: Execution context.
            prior_result: Optional result from a prior stage.

        Returns:
            Result containing identification provenance and document facts.

        Raises:
            TypeError: On invalid input types.
            DoshError: On identification failure.
        """
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")
        if prior_result is not None and not isinstance(prior_result, Result):
            raise TypeError(f"prior_result must be a Result instance or None, got {type(prior_result).__name__}.")

        prior_documents = prior_result.data if (prior_result and isinstance(prior_result.data, tuple)) else ()
        documents: list[CanonicalDocument] = list(prior_documents)
        provenance_records: list[ProvenanceRecord] = list(prior_result.provenance) if prior_result else []

        for inp in request.inputs:
            facts = identify_file(inp.source_path)

            prov = ProvenanceRecord(
                stage="identify",
                plugin_id="shakti.darshana",
                capability_id="identify",
                source_input_id=inp.input_id,
                evidence={
                    "media_type": facts.media_type,
                    "format_name": facts.format_name,
                    "is_binary": facts.is_binary,
                    "byte_signature": facts.byte_signature,
                    "encoding_hint": facts.encoding_hint,
                },
            )
            provenance_records.append(prov)

            doc = CanonicalDocument(
                document_id=f"doc-ident-{inp.input_id}",
                source_input_id=inp.input_id,
                detected_type=facts.media_type,
                pages=(),
                text="",
                metadata={
                    "darshana_facts": {
                        "media_type": facts.media_type,
                        "format_name": facts.format_name,
                        "is_binary": facts.is_binary,
                        "byte_signature": facts.byte_signature,
                        "encoding_hint": facts.encoding_hint,
                    }
                },
            )
            documents.append(doc)

        return Result(
            data=tuple(documents),
            provenance=tuple(provenance_records),
            warnings=prior_result.warnings if prior_result else (),
        )
