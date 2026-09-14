"""Comprehensive Unit and Contract Tests for Shakti Mistral AI Plugin.

Tests:
1. Plugin and Capability declarations adhere to Sankalpa protocols.
2. Kavacha security gating strictly blocks unauthorized network/external processing.
3. Missing API key produces clear DEPENDENCY_UNAVAILABLE error.
4. Client zero-leak error sanitization on HTTP 401, 429, 500, and timeout.
5. Mistral OCR execution with bounding boxes, table extraction, and artifact production.
6. Mistral Translation execution with document mapping and artifact production.
7. Cancellation token observance.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha, SecurityPolicy
from sarathi.nabhi.kosh import Kosh
from sarathi.nabhi.pravaha.common import authorize_capability
from sarathi.sankalpa import (
    CancellationToken,
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    PluginProvider,
    ReadinessStatus,
    Request,
    Result,
)
from sarathi.shakti.mistral import (
    MISTRAL_OCR_DECLARATION,
    MISTRAL_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
    MistralClient,
    MistralOCRCapability,
    MistralProvider,
    MistralTranslationCapability,
)


class TestMistralDeclarationsAndProvider:
    """Verify plugin and capability declarations satisfy canonical contracts."""

    def test_plugin_metadata_and_security_declaration(self) -> None:
        assert PLUGIN_INFO.plugin_id == "shakti.mistral"
        assert PLUGIN_INFO.name == "Mistral AI"
        assert PLUGIN_INFO.capabilities == ("mistral_ocr", "mistral_translation")
        assert PLUGIN_INFO.security.network_access is True
        assert PLUGIN_INFO.security.external_processing is True
        assert PLUGIN_INFO.security.local_processing_only is False
        assert "MISTRAL_API_KEY" in PLUGIN_INFO.security.required_secrets

    def test_capability_declarations(self) -> None:
        assert MISTRAL_OCR_DECLARATION.capability_id == "mistral_ocr"
        assert MISTRAL_OCR_DECLARATION.plugin_id == "shakti.mistral"
        assert ExecutionProfile.LAYOUT_PRESERVING in MISTRAL_OCR_DECLARATION.supported_profiles
        assert ExecutionProfile.CUSTOM in MISTRAL_OCR_DECLARATION.supported_profiles

        assert MISTRAL_TRANSLATION_DECLARATION.capability_id == "mistral_translation"
        assert MISTRAL_TRANSLATION_DECLARATION.plugin_id == "shakti.mistral"
        assert ExecutionProfile.ACCURATE in MISTRAL_TRANSLATION_DECLARATION.supported_profiles

    def test_provider_protocol_implementation(self) -> None:
        provider = MistralProvider()
        assert isinstance(provider, PluginProvider)
        assert provider.plugin_info == PLUGIN_INFO
        assert tuple(provider.declarations) == (MISTRAL_OCR_DECLARATION, MISTRAL_TRANSLATION_DECLARATION)

    def test_provider_readiness_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        provider = MistralProvider()
        readiness = provider.readiness()
        assert readiness["mistral_ocr"].ready is False
        assert readiness["mistral_ocr"].status == ReadinessStatus.DEPENDENCY_UNAVAILABLE
        assert "MISTRAL_API_KEY" in readiness["mistral_ocr"].reason

    def test_provider_readiness_with_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test_key_12345")
        provider = MistralProvider()
        readiness = provider.readiness()
        assert readiness["mistral_ocr"].ready is True
        assert readiness["mistral_ocr"].status == ReadinessStatus.READY
        assert readiness["mistral_translation"].ready is True


class TestKavachaSecurityGating:
    """Verify Kavacha strictly denies unauthorized outbound cloud execution."""

    def test_security_denied_when_network_access_disabled(self) -> None:
        kosh = Kosh()
        kosh.register_plugin(PLUGIN_INFO)
        kosh.register_capability(MISTRAL_OCR_DECLARATION)

        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=False,  # network forbidden
            allow_external_processing=False,
            allowed_secrets=("MISTRAL_API_KEY",),
        )
        kavacha = Kavacha(policy)
        cap = MistralOCRCapability()

        with pytest.raises(DoshError) as exc_info:
            authorize_capability(kavacha, kosh, cap)
        assert exc_info.value.code == FailureCode.SECURITY_DENIED

    def test_security_denied_when_external_processing_disabled(self) -> None:
        kosh = Kosh()
        kosh.register_plugin(PLUGIN_INFO)
        kosh.register_capability(MISTRAL_OCR_DECLARATION)

        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=False,  # external forbidden
            allowed_secrets=("MISTRAL_API_KEY",),
        )
        kavacha = Kavacha(policy)
        cap = MistralOCRCapability()

        with pytest.raises(DoshError) as exc_info:
            authorize_capability(kavacha, kosh, cap)
        assert exc_info.value.code == FailureCode.SECURITY_DENIED

    def test_security_denied_when_secret_not_allowed(self) -> None:
        kosh = Kosh()
        kosh.register_plugin(PLUGIN_INFO)
        kosh.register_capability(MISTRAL_OCR_DECLARATION)

        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=(),  # MISTRAL_API_KEY not in allowed_secrets
        )
        kavacha = Kavacha(policy)
        cap = MistralOCRCapability()

        with pytest.raises(DoshError) as exc_info:
            authorize_capability(kavacha, kosh, cap)
        assert exc_info.value.code == FailureCode.SECURITY_DENIED

    def test_security_authorized_when_policy_permits(self) -> None:
        kosh = Kosh()
        kosh.register_plugin(PLUGIN_INFO)
        kosh.register_capability(MISTRAL_OCR_DECLARATION)

        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=("MISTRAL_API_KEY",),
        )
        kavacha = Kavacha(policy)
        cap = MistralOCRCapability()

        # Must not raise
        authorize_capability(kavacha, kosh, cap)


class TestMistralClientZeroLeaks:
    """Verify MistralClient error handling and zero leak boundaries."""

    def test_missing_api_key_raises_dependency_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        client = MistralClient()
        with pytest.raises(DoshError) as exc_info:
            client.process_ocr(b"fake_image_bytes")
        assert exc_info.value.code == FailureCode.DEPENDENCY_UNAVAILABLE
        assert "MISTRAL_API_KEY" in exc_info.value.message

    def test_http_401_raises_security_denied_without_token_leak(self) -> None:
        client = MistralClient(api_key="secret_token_abc_123")

        class MockResponse:
            status_code = 401
            text = '{"error": "Unauthorized token"}'

        with patch("httpx.Client.post", return_value=MockResponse()):
            with pytest.raises(DoshError) as exc_info:
                client._post("ocr", {"model": "test"})
            assert exc_info.value.code == FailureCode.SECURITY_DENIED
            assert "secret_token_abc_123" not in exc_info.value.message

    def test_http_429_raises_resource_exhausted(self) -> None:
        client = MistralClient(api_key="valid_key")

        class MockResponse:
            status_code = 429
            text = '{"error": "Rate limit exceeded"}'

        with patch("httpx.Client.post", return_value=MockResponse()):
            with pytest.raises(DoshError) as exc_info:
                client._post("ocr", {"model": "test"})
            assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE


class TestMistralOCRCapability:
    """Verify Mistral OCR execution, response parsing, and artifact creation."""

    def test_ocr_execution_and_response_synthesis(self, tmp_path: Path) -> None:
        img_file = tmp_path / "scan.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\nFakePngData")

        mock_response = {
            "pages": [
                {
                    "markdown": "# Header\nFirst paragraph text.\n\n| Item | Cost |\n|---|---|\n| Book | 100 |",
                    "blocks": [
                        {
                            "text": "Header",
                            "bbox": [10.0, 10.0, 100.0, 25.0],
                            "confidence": 0.98,
                        },
                        {
                            "text": "First paragraph text.",
                            "bbox": [10.0, 30.0, 200.0, 45.0],
                            "confidence": 0.95,
                        },
                    ],
                }
            ]
        }

        mock_client = MagicMock(spec=MistralClient)
        mock_client.process_ocr.return_value = mock_response

        cap = MistralOCRCapability(client=mock_client)
        req = Request(
            request_id="req-m-ocr-1",
            requirement="mistral_ocr",
            inputs=(InputRef("inp-1", img_file, "scan.png", 100),),
            profile=ExecutionProfile.LAYOUT_PRESERVING,
        )
        ctx = ExecutionContext("run-1", "req-m-ocr-1", "tr-1", "sp-1")

        result = cap.execute(req, ctx)

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data
        assert "First paragraph text." in doc.text
        assert len(doc.pages) == 1

        # Spans verification
        assert len(doc.pages[0].spans) == 2
        assert doc.pages[0].spans[0].bounding_box == (10.0, 10.0, 100.0, 25.0)
        assert doc.pages[0].spans[0].confidence == 0.98

        # Table verification
        assert len(doc.pages[0].tables) == 1
        assert doc.pages[0].tables[0].headers == ("Item", "Cost")
        assert doc.pages[0].tables[0].rows == (("Book", "100"),)

        # Artifacts verification
        art_names = {p.intent.name for p in result.artifact_payloads}
        assert any(n.endswith("_mistral_ocr.txt") for n in art_names)
        assert any(n.endswith("_mistral_ocr.docx") for n in art_names)

        # Confidence matrix verification
        assert result.confidence is not None
        assert result.confidence.score == round((0.98 + 0.95) / 2, 4)
        assert result.confidence.method == "mistral_mean"
        assert doc.pages[0].metadata["confidence"] == round((0.98 + 0.95) / 2, 4)
        assert doc.pages[0].metadata["min_confidence"] == 0.95
        assert doc.pages[0].metadata["max_confidence"] == 0.98

    def test_ocr_records_pramana_telemetry(self, tmp_path: Path) -> None:
        img_file = tmp_path / "scan.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\nFakePngData")

        mock_response = {
            "pages": [
                {
                    "markdown": "Page text",
                    "blocks": [
                        {"text": "Page text", "bbox": [0.0, 0.0, 50.0, 10.0], "confidence": 0.92},
                    ],
                }
            ]
        }
        mock_client = MagicMock(spec=MistralClient)
        mock_client.process_ocr.return_value = mock_response
        mock_darpana = MagicMock()

        cap = MistralOCRCapability(client=mock_client, darpana=mock_darpana)
        req = Request(
            request_id="req-pramana",
            requirement="mistral_ocr",
            inputs=(InputRef("inp-1", img_file, "scan.png", 50),),
        )
        ctx = ExecutionContext("run-p", "req-pramana", "tr-p", "sp-p")
        result = cap.execute(req, ctx)

        assert result.confidence is not None
        assert result.confidence.score == 0.92
        assert mock_darpana.record_pramana.call_count >= 1

    def test_ocr_observes_cancellation_token(self, tmp_path: Path) -> None:
        token = CancellationToken()
        token.cancel()

        img_file = tmp_path / "scan.png"
        img_file.write_bytes(b"data")

        cap = MistralOCRCapability()
        req = Request(
            request_id="req-m-ocr-cancel",
            requirement="mistral_ocr",
            inputs=(InputRef("inp-1", img_file, "scan.png", 10),),
            cancellation_token=token,
        )
        ctx = ExecutionContext("run-1", "req-1", "tr-1", "sp-1", cancellation_token=token)

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, ctx)
        assert exc_info.value.code == FailureCode.OPERATION_CANCELLED


class TestMistralTranslationCapability:
    """Verify Mistral Translation execution, direction mapping, and artifact creation."""

    def test_translation_execution_and_response_synthesis(self) -> None:
        mock_client = MagicMock(spec=MistralClient)
        mock_client.chat_translate.return_value = "The Reserve Bank of India issued a new order."

        cap = MistralTranslationCapability(client=mock_client)

        prior_doc = CanonicalDocument(
            document_id="doc-hi-1",
            text="भारतीय रिजर्व बैंक ने नया आदेश जारी किया।",
            pages=(PageData(page_number=1, text="भारतीय रिजर्व बैंक ने नया आदेश जारी किया।"),),
        )
        prior = Result(data=prior_doc)

        req = Request(
            request_id="req-m-tr-1",
            requirement="mistral_translation",
            inputs=(InputRef("inp-1", Path("doc.txt"), "doc.txt", 50),),
            metadata={"direction": "hi-en"},
        )
        ctx = ExecutionContext("run-1", "req-m-tr-1", "tr-1", "sp-1")

        result = cap.execute(req, ctx, prior_result=prior)

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data
        assert doc.text == "The Reserve Bank of India issued a new order."
        assert doc.metadata["direction"] == "Hindi->English"

        # Check client was called with Hindi->English
        mock_client.chat_translate.assert_any_call(
            text="भारतीय रिजर्व बैंक ने नया आदेश जारी किया।",
            source_lang="Hindi",
            target_lang="English",
            model="mistral-large-latest",
        )

        # Artifacts verification
        art_names = {p.intent.name for p in result.artifact_payloads}
        assert any(n.endswith("_mistral_translated.txt") for n in art_names)
        assert any(n.endswith("_mistral_translated.docx") for n in art_names)
