"""Tests for Microsoft Azure Cloud Plugin (Document Intelligence, Translator, and Kavacha gating)."""

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
from sarathi.shakti.azure.client import AzureClient
from sarathi.shakti.azure.ocr import AzureOCRCapability
from sarathi.shakti.azure.plugin import (
    AZURE_OCR_DECLARATION,
    AZURE_SECURITY,
    AZURE_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.azure.provider import AzureProvider
from sarathi.shakti.azure.translation import AzureTranslationCapability


class TestAzurePluginMetadata:
    """Verify Azure plugin declarations and reviewable Kavacha security contracts."""

    def test_plugin_metadata_integrity(self) -> None:
        assert PLUGIN_INFO.plugin_id == "sarathi.shakti.azure"
        assert "azure_ocr" in PLUGIN_INFO.capabilities
        assert "azure_translation" in PLUGIN_INFO.capabilities

    def test_security_declaration_requires_network_and_secrets(self) -> None:
        sec = AZURE_SECURITY
        assert sec.network_access is True
        assert sec.external_processing is True
        assert sec.local_processing_only is False
        assert "AZURE_API_KEY" in sec.required_secrets
        assert "AZURE_ENDPOINT" in sec.required_secrets

    def test_ocr_and_translation_declarations(self) -> None:
        assert AZURE_OCR_DECLARATION.capability_id == "azure_ocr"
        assert ExecutionProfile.LAYOUT_PRESERVING in AZURE_OCR_DECLARATION.supported_profiles
        assert AZURE_TRANSLATION_DECLARATION.capability_id == "azure_translation"
        assert ExecutionProfile.INSTANT in AZURE_TRANSLATION_DECLARATION.supported_profiles


class TestAzureProvider:
    """Verify Azure provider lifecycle and readiness checks."""

    def test_provider_readiness_without_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AZURE_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_ENDPOINT", raising=False)
        monkeypatch.delenv("AZURE_TRANSLATOR_KEY", raising=False)
        provider = AzureProvider()
        ready = provider.readiness()
        assert ready["azure_ocr"].status == ReadinessStatus.DEPENDENCY_UNAVAILABLE
        assert ready["azure_ocr"].ready is False

    def test_provider_readiness_with_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_API_KEY", "test_azure_key_123")
        monkeypatch.setenv("AZURE_ENDPOINT", "https://test.cognitiveservices.azure.com")
        monkeypatch.setenv("AZURE_TRANSLATOR_KEY", "test_trans_key")
        provider = AzureProvider()
        ready = provider.readiness()
        assert ready["azure_ocr"].status == ReadinessStatus.READY
        assert ready["azure_ocr"].ready is True
        assert ready["azure_translation"].status == ReadinessStatus.READY
        assert ready["azure_translation"].ready is True

    def test_provider_create_capabilities(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_API_KEY", "test_key")
        monkeypatch.setenv("AZURE_ENDPOINT", "https://test.cognitiveservices.azure.com")
        provider = AzureProvider()
        services = PluginServices(darpana=MagicMock())
        caps = provider.create_capabilities(services)
        assert "azure_ocr" in caps
        assert "azure_translation" in caps
        assert isinstance(caps["azure_ocr"], AzureOCRCapability)
        assert isinstance(caps["azure_translation"], AzureTranslationCapability)


class TestAzureClient:
    """Verify Azure REST client transport, headers, and error mappings."""

    def test_missing_credentials_raises_dependency_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AZURE_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_ENDPOINT", raising=False)
        client = AzureClient(api_key=None, endpoint=None)
        with pytest.raises(DoshError) as exc_info:
            client.analyze_layout(b"dummy")
        assert exc_info.value.code == FailureCode.DEPENDENCY_UNAVAILABLE

    def test_http_401_raises_security_denied_without_token_leak(self) -> None:
        client = AzureClient(api_key="secret_azure_token_xyz", endpoint="https://myaccount.cognitiveservices.azure.com")

        class MockResponse:
            status_code = 401
            text = '{"error": "Access denied"}'

        with patch("httpx.Client.post", return_value=MockResponse()):
            with pytest.raises(DoshError) as exc_info:
                client.analyze_layout(b"data")
            assert exc_info.value.code == FailureCode.SECURITY_DENIED
            assert "secret_azure_token_xyz" not in exc_info.value.message

    def test_http_429_raises_resource_unavailable(self) -> None:
        client = AzureClient(api_key="valid_key", endpoint="https://myaccount.cognitiveservices.azure.com")

        class MockResponse:
            status_code = 429
            text = '{"error": "Too Many Requests"}'

        with patch("httpx.Client.post", return_value=MockResponse()):
            with pytest.raises(DoshError) as exc_info:
                client.analyze_layout(b"data")
            assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE


class TestAzureOCRCapability:
    """Verify Azure OCR execution, confidence matrix, table parsing, and artifacts."""

    def test_ocr_execution_and_confidence_matrix(self, tmp_path: Path) -> None:
        img_file = tmp_path / "doc.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\nFakeData")

        mock_analyze_result = {
            "content": "Line one header\n\nLine two content",
            "pages": [
                {
                    "pageNumber": 1,
                    "lines": [
                        {"content": "Line one header"},
                        {"content": "Line two content"},
                    ],
                    "words": [
                        {"content": "Line", "confidence": 0.99, "polygon": [0, 0, 10, 0, 10, 5, 0, 5]},
                        {"content": "one", "confidence": 0.95, "polygon": [12, 0, 20, 0, 20, 5, 12, 5]},
                    ],
                }
            ],
            "tables": [
                {
                    "rowCount": 2,
                    "columnCount": 2,
                    "cells": [
                        {"rowIndex": 0, "columnIndex": 0, "content": "ID"},
                        {"rowIndex": 0, "columnIndex": 1, "content": "Amount"},
                        {"rowIndex": 1, "columnIndex": 0, "content": "A1"},
                        {"rowIndex": 1, "columnIndex": 1, "content": "500"},
                    ],
                }
            ],
        }

        mock_client = MagicMock(spec=AzureClient)
        mock_client.analyze_layout.return_value = mock_analyze_result
        mock_darpana = MagicMock()

        cap = AzureOCRCapability(client=mock_client, darpana=mock_darpana)
        req = Request(
            request_id="req-az-ocr-1",
            requirement="azure_ocr",
            inputs=(InputRef("inp-1", img_file, "doc.png", 100),),
            profile=ExecutionProfile.LAYOUT_PRESERVING,
        )
        ctx = ExecutionContext("run-1", "req-az-ocr-1", "tr-1", "sp-1")

        result = cap.execute(req, ctx)

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data
        assert "Line one header" in doc.text
        assert len(doc.pages) == 1

        # Table verification
        assert len(doc.pages[0].tables) == 1
        assert doc.pages[0].tables[0].headers == ("ID", "Amount")
        assert doc.pages[0].tables[0].rows == (("A1", "500"),)

        # Confidence matrix verification
        assert result.confidence is not None
        assert result.confidence.score == round((0.99 + 0.95) / 2, 4)
        assert result.confidence.method == "azure_mean"
        assert doc.pages[0].metadata["confidence"] == round((0.99 + 0.95) / 2, 4)
        assert doc.pages[0].metadata["min_confidence"] == 0.95
        assert doc.pages[0].metadata["max_confidence"] == 0.99

        # Telemetry verification
        assert mock_darpana.record_pramana.call_count >= 1

        # Artifacts verification
        art_names = {p.intent.name for p in result.artifact_payloads}
        assert any(n.endswith("_azure_ocr.txt") for n in art_names)
        assert any(n.endswith("_azure_ocr.docx") for n in art_names)

    def test_ocr_observes_cancellation_token(self, tmp_path: Path) -> None:
        token = CancellationToken()
        token.cancel()

        img_file = tmp_path / "doc.png"
        img_file.write_bytes(b"data")

        cap = AzureOCRCapability()
        req = Request(
            request_id="req-cancel",
            requirement="azure_ocr",
            inputs=(InputRef("inp-1", img_file, "doc.png", 10),),
            cancellation_token=token,
        )
        ctx = ExecutionContext("run-1", "req-cancel", "tr-1", "sp-1", cancellation_token=token)

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, ctx)
        assert exc_info.value.code == FailureCode.OPERATION_CANCELLED


class TestAzureTranslationCapability:
    """Verify Azure translation execution, direction mapping, and artifact creation."""

    def test_translation_execution_and_response_synthesis(self) -> None:
        mock_client = MagicMock(spec=AzureClient)
        mock_client.translate_text.return_value = "The bank issued the notification."

        cap = AzureTranslationCapability(client=mock_client)

        prior_doc = CanonicalDocument(
            document_id="doc-hi-az",
            source_input_id="inp-1",
            text="बैंक ने अधिसूचना जारी की।",
            pages=(
                PageData(
                    page_number=1,
                    text="बैंक ने अधिसूचना जारी की।",
                    metadata={"source_page": "kept"},
                ),
            ),
            detected_type="ocr_document",
            metadata={"existing": "kept"},
        )
        prior = Result(data=prior_doc)

        req = Request(
            request_id="req-az-tr-1",
            requirement="azure_translation",
            inputs=(InputRef("inp-1", Path("doc.txt"), "doc.txt", 50),),
            metadata={"direction": "hi-en"},
        )
        ctx = ExecutionContext("run-1", "req-az-tr-1", "tr-1", "sp-1")

        result = cap.execute(req, ctx, prior_result=prior)

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data
        assert doc.text == "The bank issued the notification."
        assert doc.metadata["direction"] == "hi->en"
        assert doc.metadata["existing"] == "kept"
        assert doc.source_input_id == "inp-1"
        assert doc.detected_type == "ocr_document"
        assert doc.pages[0].metadata["source_page"] == "kept"

        art_names = {p.intent.name for p in result.artifact_payloads}
        assert any(n.endswith("_azure_translated.txt") for n in art_names)
        assert any(n.endswith("_azure_translated.docx") for n in art_names)
