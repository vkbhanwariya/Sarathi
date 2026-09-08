"""Tests for Google Gemini Cloud Plugin (OCR, Translation, Client, and Kavacha gating)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    PluginServices,
    ReadinessStatus,
    Request,
    Result,
)
from sarathi.shakti.gemini.client import GeminiClient
from sarathi.shakti.gemini.ocr import GeminiOCRCapability
from sarathi.shakti.gemini.plugin import (
    GEMINI_OCR_DECLARATION,
    GEMINI_SECURITY,
    GEMINI_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.gemini.provider import GeminiProvider
from sarathi.shakti.gemini.translation import GeminiTranslationCapability


class TestGeminiPluginMetadata:
    """Verify Gemini plugin declarations and reviewable Kavacha security contracts."""

    def test_plugin_metadata_integrity(self) -> None:
        assert PLUGIN_INFO.plugin_id == "sarathi.shakti.gemini"
        assert "gemini_ocr" in PLUGIN_INFO.capabilities
        assert "gemini_translation" in PLUGIN_INFO.capabilities

    def test_security_declaration_requires_network_and_secrets(self) -> None:
        sec = GEMINI_SECURITY
        assert sec.network_access is True
        assert sec.external_processing is True
        assert sec.local_processing_only is False
        assert "GEMINI_API_KEY" in sec.required_secrets

    def test_ocr_and_translation_declarations(self) -> None:
        assert GEMINI_OCR_DECLARATION.capability_id == "gemini_ocr"
        assert ExecutionProfile.LAYOUT_PRESERVING in GEMINI_OCR_DECLARATION.supported_profiles
        assert GEMINI_TRANSLATION_DECLARATION.capability_id == "gemini_translation"
        assert ExecutionProfile.INSTANT in GEMINI_TRANSLATION_DECLARATION.supported_profiles


class TestGeminiProvider:
    """Verify Gemini provider lifecycle and readiness checks."""

    def test_provider_readiness_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        provider = GeminiProvider()
        ready = provider.readiness()
        assert ready["gemini_ocr"].status == ReadinessStatus.DEPENDENCY_UNAVAILABLE
        assert ready["gemini_ocr"].ready is False

    def test_provider_readiness_with_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key_123")
        provider = GeminiProvider()
        ready = provider.readiness()
        assert ready["gemini_ocr"].status == ReadinessStatus.READY
        assert ready["gemini_ocr"].ready is True

    def test_provider_create_capabilities(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key_123")
        provider = GeminiProvider()
        services = PluginServices(darpana=MagicMock())
        caps = provider.create_capabilities(services)
        assert "gemini_ocr" in caps
        assert "gemini_translation" in caps
        assert isinstance(caps["gemini_ocr"], GeminiOCRCapability)
        assert isinstance(caps["gemini_translation"], GeminiTranslationCapability)


class TestGeminiClient:
    """Verify Gemini REST client transport, authentication headers, and zero-leak boundaries."""

    def test_missing_api_key_raises_dependency_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        client = GeminiClient(api_key=None)
        with pytest.raises(DoshError) as exc_info:
            client.process_ocr(b"dummy")
        assert exc_info.value.code == FailureCode.DEPENDENCY_UNAVAILABLE

    def test_http_403_raises_security_denied_without_token_leak(self) -> None:
        client = GeminiClient(api_key="secret_gemini_token_xyz")

        class MockResponse:
            status_code = 403
            text = '{"error": "Forbidden: invalid API key"}'

        with patch("httpx.Client.post", return_value=MockResponse()):
            with pytest.raises(DoshError) as exc_info:
                client._post("gemini-2.5-flash", {"contents": []})
            assert exc_info.value.code == FailureCode.SECURITY_DENIED
            assert "secret_gemini_token_xyz" not in exc_info.value.message

    def test_http_429_raises_resource_unavailable(self) -> None:
        client = GeminiClient(api_key="valid_key")

        class MockResponse:
            status_code = 429
            text = '{"error": "Rate limit exceeded"}'

        with patch("httpx.Client.post", return_value=MockResponse()):
            with pytest.raises(DoshError) as exc_info:
                client._post("gemini-2.5-flash", {"contents": []})
            assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE


class TestGeminiOCRCapability:
    """Verify Gemini OCR execution, confidence matrix, table extraction, and telemetry."""

    def test_ocr_execution_and_confidence_matrix(self, tmp_path: Path) -> None:
        img_file = tmp_path / "doc.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\nFakeData")

        mock_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": "# Order Title\n\nMain content paragraph.\n\n| Case | Year |\n|---|---|\n| 101 | 2026 |"
                            }
                        ]
                    },
                    "avgLogprobs": -0.05,
                }
            ]
        }
        mock_client = MagicMock(spec=GeminiClient)
        mock_client.process_ocr.return_value = mock_response
        mock_darpana = MagicMock()

        cap = GeminiOCRCapability(client=mock_client, darpana=mock_darpana)
        req = Request(
            request_id="req-gem-ocr-1",
            requirement="gemini_ocr",
            inputs=(InputRef("inp-1", img_file, "doc.png", 100),),
            profile=ExecutionProfile.LAYOUT_PRESERVING,
        )
        ctx = ExecutionContext("run-1", "req-gem-ocr-1", "tr-1", "sp-1")

        result = cap.execute(req, ctx)

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data
        assert "Main content paragraph." in doc.text
        assert len(doc.pages) == 1

        # Table verification
        assert len(doc.pages[0].tables) == 1
        assert doc.pages[0].tables[0].headers == ("Case", "Year")
        assert doc.pages[0].tables[0].rows == (("101", "2026"),)

        # Confidence matrix verification
        assert result.confidence is not None
        assert 0.90 <= result.confidence.score <= 1.0
        assert result.confidence.method == "gemini_mean"
        assert doc.pages[0].metadata["confidence"] == result.confidence.score
        assert doc.pages[0].metadata["min_confidence"] == result.confidence.score

        # Telemetry verification
        assert mock_darpana.record_pramana.call_count >= 1

        # Artifacts verification
        art_names = {p.intent.name for p in result.artifact_payloads}
        assert any(n.endswith("_gemini_ocr.txt") for n in art_names)
        assert any(n.endswith("_gemini_ocr.docx") for n in art_names)

    def test_ocr_observes_cancellation_token(self, tmp_path: Path) -> None:
        token = CancellationToken()
        token.cancel()

        img_file = tmp_path / "doc.png"
        img_file.write_bytes(b"data")

        cap = GeminiOCRCapability()
        req = Request(
            request_id="req-cancel",
            requirement="gemini_ocr",
            inputs=(InputRef("inp-1", img_file, "doc.png", 10),),
            cancellation_token=token,
        )
        ctx = ExecutionContext("run-1", "req-cancel", "tr-1", "sp-1", cancellation_token=token)

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, ctx)
        assert exc_info.value.code == FailureCode.OPERATION_CANCELLED


class TestGeminiTranslationCapability:
    """Verify Gemini translation execution, direction mapping, and artifact creation."""

    def test_translation_execution_and_response_synthesis(self) -> None:
        mock_client = MagicMock(spec=GeminiClient)
        mock_client.chat_translate.return_value = "The court delivered the judgment."

        cap = GeminiTranslationCapability(client=mock_client)

        prior_doc = CanonicalDocument(
            document_id="doc-hi-gem",
            text="न्यायालय ने निर्णय सुनाया।",
            pages=(PageData(page_number=1, text="न्यायालय ने निर्णय सुनाया।"),),
        )
        prior = Result(data=prior_doc)

        req = Request(
            request_id="req-gem-tr-1",
            requirement="gemini_translation",
            inputs=(InputRef("inp-1", Path("doc.txt"), "doc.txt", 50),),
            metadata={"direction": "hi-en"},
        )
        ctx = ExecutionContext("run-1", "req-gem-tr-1", "tr-1", "sp-1")

        result = cap.execute(req, ctx, prior_result=prior)

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data
        assert doc.text == "The court delivered the judgment."
        assert doc.metadata["direction"] == "Hindi->English"

        art_names = {p.intent.name for p in result.artifact_payloads}
        assert any(n.endswith("_gemini_translated.txt") for n in art_names)
        assert any(n.endswith("_gemini_translated.docx") for n in art_names)
