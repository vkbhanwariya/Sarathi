"""Integration and unit tests for unified cloud translation and legal context preservation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    PageData,
    Request,
    Result,
    TableData,
)
from sarathi.shakti.azure.client import AzureClient
from sarathi.shakti.azure.translation import AzureTranslationCapability
from sarathi.shakti.gemini.client import GeminiClient
from sarathi.shakti.gemini.translation import GeminiTranslationCapability
from sarathi.shakti.mistral.client import MistralClient
from sarathi.shakti.mistral.translation import MistralTranslationCapability
from sarathi.shakti.translation.cloud_orchestration import is_structural_placeholder


class TestStructuralPlaceholderHandling:
    """Verify structural tag detection and preservation invariants."""

    def test_is_structural_placeholder(self) -> None:
        assert is_structural_placeholder("{{TABLE:table_1}}") is True
        assert is_structural_placeholder("{{PAGE:1}}") is True
        assert is_structural_placeholder("<!-- TABLE:table_2 -->") is True
        assert is_structural_placeholder("--- Page 3 ---") is True
        assert is_structural_placeholder("[PAGE:4]") is True

        # Non-placeholders
        assert is_structural_placeholder("This is regular text.") is False
        assert is_structural_placeholder("The table shows financial results:") is False
        assert is_structural_placeholder("") is False
        assert is_structural_placeholder(None) is False


class TestCloudLegalTranslationCapabilities:
    """Verify unified cloud translation with legal grounding across Gemini, Mistral, and Azure."""

    @pytest.fixture
    def legal_document(self) -> CanonicalDocument:
        text = (
            "IN THE HIGH COURT OF DELHI AT NEW DELHI\n"
            "W.P.(C) 1234/2024 & CM APPL. 567/2024\n"
            "CNR No. DLHC010012342024\n\n"
            "RAJESH KUMAR ... PETITIONER\n"
            "VERSUS\n"
            "STATE OF NCT OF DELHI ... RESPONDENT\n\n"
            "CORAM: HON'BLE MR. JUSTICE SURESH KUMAR KAIT\n\n"
            "1. The petitioner seeks quashing of FIR registered under Section 482 CrPC and Section 420 IPC.\n"
            "{{TABLE:table_charges}}\n"
            "2. The impugned order passed by the learned Magistrate is contrary to law."
        )
        return CanonicalDocument(
            document_id="doc-legal-1",
            source_input_id="inp-1",
            text=text,
            pages=(
                PageData(
                    page_number=1,
                    text=text,
                    tables=(
                        TableData(
                            name="charges",
                            headers=("Section", "Act", "Cognizable"),
                            rows=(("420", "IPC", "Yes"), ("482", "CrPC", "N/A")),
                        ),
                    ),
                ),
            ),
        )

    def test_gemini_legal_translation_injects_judicial_prompt_and_preserves_placeholders(
        self,
        legal_document: CanonicalDocument,
    ) -> None:
        mock_client = MagicMock(spec=GeminiClient)
        # Verify placeholder is returned untranslated by mock translate
        mock_client.chat_translate.side_effect = lambda text, **kwargs: f"[TR: {text}]"

        cap = GeminiTranslationCapability(client=mock_client)
        req = Request(
            request_id="req-gem-legal",
            requirement="gemini_translation",
            inputs=(InputRef("inp-1", Path("case.txt"), "case.txt", 100),),
            metadata={"direction": "en-hi"},
        )
        ctx = ExecutionContext("run-1", "req-gem-legal", "tr-1", "sp-1")

        result = cap.execute(req, ctx, prior_result=Result(data=legal_document))

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data

        # Verify legal context metadata
        assert "legal_context" in doc.metadata
        legal_ctx = doc.metadata["legal_context"]
        assert legal_ctx["is_legal_document"] is True
        assert legal_ctx["court_name"] == "High Court of Delhi"
        assert legal_ctx["cnr_number"] == "DLHC010012342024"

        # Verify provenance evidence
        prov = result.provenance[0]
        assert prov.evidence["provider"] == "google_gemini"
        assert prov.evidence["legal_context"]["is_legal_document"] is True

        # Verify structural placeholder {{TABLE:table_charges}} was preserved untranslated
        assert "{{TABLE:table_charges}}" in doc.text
        # Verify client was called with system_prompt containing judicial grounding
        call_kwargs = mock_client.chat_translate.call_args.kwargs
        assert "system_prompt" in call_kwargs or "system_instruction" in call_kwargs
        sys_prompt = call_kwargs.get("system_prompt") or call_kwargs.get("system_instruction")
        assert "Senior Bilingual Judicial and Legal Translator" in sys_prompt
        assert "High Court of Delhi" in sys_prompt

    def test_mistral_legal_translation_injects_system_prompt_and_legal_evidence(
        self,
        legal_document: CanonicalDocument,
    ) -> None:
        mock_client = MagicMock(spec=MistralClient)
        mock_client.chat_translate.side_effect = lambda text, **kwargs: f"[MISTRAL: {text}]"

        cap = MistralTranslationCapability(client=mock_client)
        req = Request(
            request_id="req-mis-legal",
            requirement="mistral_translation",
            inputs=(InputRef("inp-1", Path("case.txt"), "case.txt", 100),),
            metadata={"direction": "en-hi"},
        )
        ctx = ExecutionContext("run-1", "req-mis-legal", "tr-1", "sp-1")

        result = cap.execute(req, ctx, prior_result=Result(data=legal_document))

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data

        # Verify provenance and legal context
        assert doc.metadata["provider"] == "mistral"
        assert doc.metadata["legal_context"]["is_legal_document"] is True
        assert "{{TABLE:table_charges}}" in doc.text

        # Verify system_prompt was passed
        mock_client.chat_translate.assert_any_call(
            text=ANY,
            source_lang="English",
            target_lang="Hindi",
            model="mistral-large-latest",
            system_prompt=ANY,
        )

    def test_azure_legal_translation_records_legal_provenance_and_artifacts(
        self,
        legal_document: CanonicalDocument,
    ) -> None:
        mock_client = MagicMock(spec=AzureClient)
        mock_client.translate_text.side_effect = lambda text, **kwargs: f"[AZURE: {text}]"

        cap = AzureTranslationCapability(client=mock_client)
        req = Request(
            request_id="req-az-legal",
            requirement="azure_translation",
            inputs=(InputRef("inp-1", Path("case.txt"), "case.txt", 100),),
            metadata={"direction": "en-hi"},
        )
        ctx = ExecutionContext("run-1", "req-az-legal", "tr-1", "sp-1")

        result = cap.execute(req, ctx, prior_result=Result(data=legal_document))

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data

        assert doc.metadata["provider"] == "azure"
        assert doc.metadata["legal_context"]["is_legal_document"] is True
        assert "{{TABLE:table_charges}}" in doc.text

        # Verify artifacts
        art_names = {p.intent.name for p in result.artifact_payloads}
        assert any(n.endswith("_azure_translated.txt") for n in art_names)
        assert any(n.endswith("_azure_translated.docx") for n in art_names)

    def test_binary_input_rejection_fail_closed(self, tmp_path: Path) -> None:
        pdf_file = tmp_path / "document.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 dummy binary")

        cap = GeminiTranslationCapability()
        req = Request(
            request_id="req-bin",
            requirement="gemini_translation",
            inputs=(InputRef("inp-bin", pdf_file, "document.pdf", 100),),
        )
        ctx = ExecutionContext("run-1", "req-bin", "tr-1", "sp-1")

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, ctx)
        assert exc_info.value.code == FailureCode.VALIDATION_FAILED
        assert "must be processed through an extraction stage" in exc_info.value.message

    def test_cancellation_token_observed(self, tmp_path: Path) -> None:
        token = CancellationToken()
        token.cancel()

        txt_file = tmp_path / "sample.txt"
        txt_file.write_text("Hello world", encoding="utf-8")

        cap = MistralTranslationCapability()
        req = Request(
            request_id="req-cancel",
            requirement="mistral_translation",
            inputs=(InputRef("inp-1", txt_file, "sample.txt", 11),),
            cancellation_token=token,
        )
        ctx = ExecutionContext("run-1", "req-cancel", "tr-1", "sp-1", cancellation_token=token)

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, ctx)
        assert exc_info.value.code == FailureCode.OPERATION_CANCELLED
