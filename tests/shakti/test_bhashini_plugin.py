"""Tests for Bhashini Cloud Plugin (Chitrakshar OCR, IndicTrans2, and Kavacha gating)."""

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
from sarathi.shakti.bhashini.client import BhashiniClient
from sarathi.shakti.bhashini.ocr import BhashiniOCRCapability
from sarathi.shakti.bhashini.plugin import (
    BHASHINI_OCR_DECLARATION,
    BHASHINI_SECURITY,
    BHASHINI_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.bhashini.provider import BhashiniProvider
from sarathi.shakti.bhashini.translation import BhashiniTranslationCapability


class TestBhashiniPluginMetadata:
    """Verify Bhashini plugin declarations and reviewable Kavacha security contracts."""

    def test_plugin_metadata_integrity(self) -> None:
        assert PLUGIN_INFO.plugin_id == "sarathi.shakti.bhashini"
        assert "bhashini_ocr" in PLUGIN_INFO.capabilities
        assert "bhashini_translation" in PLUGIN_INFO.capabilities

    def test_security_declaration_requires_network_and_secrets(self) -> None:
        sec = BHASHINI_SECURITY
        assert sec.network_access is True
        assert sec.external_processing is True
        assert sec.local_processing_only is False
        assert "BHASHINI_USER_ID" in sec.required_secrets
        assert "BHASHINI_API_KEY" in sec.required_secrets
        assert "BHASHINI_INFERENCE_KEY" in sec.required_secrets

    def test_ocr_and_translation_declarations(self) -> None:
        assert BHASHINI_OCR_DECLARATION.capability_id == "bhashini_ocr"
        assert ExecutionProfile.LAYOUT_PRESERVING in BHASHINI_OCR_DECLARATION.supported_profiles
        assert BHASHINI_TRANSLATION_DECLARATION.capability_id == "bhashini_translation"
        assert ExecutionProfile.INSTANT in BHASHINI_TRANSLATION_DECLARATION.supported_profiles


class TestBhashiniProvider:
    """Verify Bhashini provider lifecycle and readiness checks."""

    def test_provider_readiness_without_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BHASHINI_USER_ID", raising=False)
        monkeypatch.delenv("BHASHINI_API_KEY", raising=False)
        monkeypatch.delenv("BHASHINI_INFERENCE_KEY", raising=False)
        provider = BhashiniProvider()
        ready = provider.readiness()
        assert ready["bhashini_ocr"].status == ReadinessStatus.DEPENDENCY_UNAVAILABLE
        assert ready["bhashini_ocr"].ready is False

    def test_provider_readiness_with_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BHASHINI_USER_ID", "usr-123")
        monkeypatch.setenv("BHASHINI_API_KEY", "key-456")
        monkeypatch.setenv("BHASHINI_INFERENCE_KEY", "inf-789")
        provider = BhashiniProvider()
        ready = provider.readiness()
        assert ready["bhashini_ocr"].status == ReadinessStatus.READY
        assert ready["bhashini_ocr"].ready is True
        assert ready["bhashini_translation"].status == ReadinessStatus.READY
        assert ready["bhashini_translation"].ready is True

    def test_provider_create_capabilities(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BHASHINI_USER_ID", "usr-123")
        monkeypatch.setenv("BHASHINI_API_KEY", "key-456")
        monkeypatch.setenv("BHASHINI_INFERENCE_KEY", "inf-789")
        provider = BhashiniProvider()
        services = PluginServices(darpana=MagicMock())
        caps = provider.create_capabilities(services)
        assert "bhashini_ocr" in caps
        assert "bhashini_translation" in caps
        assert isinstance(caps["bhashini_ocr"], BhashiniOCRCapability)
        assert isinstance(caps["bhashini_translation"], BhashiniTranslationCapability)


class TestBhashiniClient:
    """Verify Bhashini REST client transport, headers, and error mappings."""

    def test_missing_credentials_raises_dependency_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BHASHINI_USER_ID", raising=False)
        monkeypatch.delenv("BHASHINI_API_KEY", raising=False)
        monkeypatch.delenv("BHASHINI_INFERENCE_KEY", raising=False)
        client = BhashiniClient(user_id=None, api_key=None, inference_key=None)
        with pytest.raises(DoshError) as exc_info:
            client.process_ocr(b"dummy")
        assert exc_info.value.code == FailureCode.DEPENDENCY_UNAVAILABLE

    def test_http_401_raises_security_denied_without_token_leak(self) -> None:
        client = BhashiniClient(user_id="usr_abc", api_key="secret_bhashini_key_123", inference_key="inf_xyz")

        class MockResponse:
            status_code = 401
            text = '{"message": "Invalid credentials"}'

        with patch("httpx.Client.post", return_value=MockResponse()):
            with pytest.raises(DoshError) as exc_info:
                client.process_ocr(b"data")
            assert exc_info.value.code == FailureCode.SECURITY_DENIED
            assert "secret_bhashini_key_123" not in exc_info.value.message

    def test_http_429_raises_resource_unavailable(self) -> None:
        client = BhashiniClient(user_id="usr_abc", api_key="valid_key", inference_key="inf_key")

        class MockResponse:
            status_code = 429
            text = '{"message": "Rate limit exceeded"}'

        with patch("httpx.Client.post", return_value=MockResponse()):
            with pytest.raises(DoshError) as exc_info:
                client.process_ocr(b"data")
            assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE


class TestBhashiniOCRCapability:
    """Verify Bhashini OCR execution, confidence matrix, table parsing, and artifacts."""

    def test_ocr_execution_and_confidence_matrix(self, tmp_path: Path) -> None:
        img_file = tmp_path / "doc.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\nFakeData")

        mock_response = {
            "pipelineResponse": [
                {
                    "taskType": "ocr",
                    "output": [
                        {
                            "target": "# आधिकारिक नोटिस\n\nदिनांक 05 सितम्बर 2026\n\n| क्रम | नाम |\n|---|---|\n| 1 | राकेश |",
                            "confidence": 0.94,
                        }
                    ],
                }
            ]
        }

        mock_client = MagicMock(spec=BhashiniClient)
        mock_client.process_ocr.return_value = mock_response
        mock_darpana = MagicMock()

        cap = BhashiniOCRCapability(client=mock_client, darpana=mock_darpana)
        req = Request(
            request_id="req-bh-ocr-1",
            requirement="bhashini_ocr",
            inputs=(InputRef("inp-1", img_file, "doc.png", 100),),
            profile=ExecutionProfile.LAYOUT_PRESERVING,
        )
        ctx = ExecutionContext("run-1", "req-bh-ocr-1", "tr-1", "sp-1")

        result = cap.execute(req, ctx)

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data
        assert "आधिकारिक नोटिस" in doc.text
        assert len(doc.pages) == 1

        # Table verification
        assert len(doc.pages[0].tables) == 1
        assert doc.pages[0].tables[0].headers == ("क्रम", "नाम")
        assert doc.pages[0].tables[0].rows == (("1", "राकेश"),)

        # Confidence matrix verification
        assert result.confidence is not None
        assert result.confidence.score == 0.94
        assert result.confidence.method == "bhashini_mean"
        assert doc.pages[0].metadata["confidence"] == 0.94

        # Telemetry verification
        assert mock_darpana.record_pramana.call_count >= 1

        # Artifacts verification
        art_names = {p.intent.name for p in result.artifact_payloads}
        assert any(n.endswith("_bhashini_ocr.txt") for n in art_names)
        assert any(n.endswith("_bhashini_ocr.docx") for n in art_names)

    def test_ocr_observes_cancellation_token(self, tmp_path: Path) -> None:
        token = CancellationToken()
        token.cancel()

        img_file = tmp_path / "doc.png"
        img_file.write_bytes(b"data")

        cap = BhashiniOCRCapability()
        req = Request(
            request_id="req-cancel",
            requirement="bhashini_ocr",
            inputs=(InputRef("inp-1", img_file, "doc.png", 10),),
            cancellation_token=token,
        )
        ctx = ExecutionContext("run-1", "req-cancel", "tr-1", "sp-1", cancellation_token=token)

        with pytest.raises(DoshError) as exc_info:
            cap.execute(req, ctx)
        assert exc_info.value.code == FailureCode.OPERATION_CANCELLED


class TestBhashiniTranslationCapability:
    """Verify Bhashini translation execution, direction mapping, and artifact creation."""

    def test_translation_execution_and_response_synthesis(self) -> None:
        mock_client = MagicMock(spec=BhashiniClient)
        mock_client.translate_text.return_value = "The official liquidator submitted the application."

        cap = BhashiniTranslationCapability(client=mock_client)

        prior_doc = CanonicalDocument(
            document_id="doc-hi-bh",
            source_input_id="inp-1",
            text="परिसमापक ने आवेदन प्रस्तुत किया।",
            pages=(
                PageData(
                    page_number=1,
                    text="परिसमापक ने आवेदन प्रस्तुत किया।",
                    metadata={"source_page": "kept"},
                ),
            ),
            detected_type="ocr_document",
            metadata={"existing": "kept"},
        )
        prior = Result(data=prior_doc)

        req = Request(
            request_id="req-bh-tr-1",
            requirement="bhashini_translation",
            inputs=(InputRef("inp-1", Path("doc.txt"), "doc.txt", 50),),
            metadata={"direction": "hi-en"},
        )
        ctx = ExecutionContext("run-1", "req-bh-tr-1", "tr-1", "sp-1")

        result = cap.execute(req, ctx, prior_result=prior)

        assert isinstance(result.data, CanonicalDocument)
        doc: CanonicalDocument = result.data
        assert doc.text == "The official liquidator submitted the application."
        assert doc.metadata["direction"] == "hi->en"
        assert doc.metadata["existing"] == "kept"
        assert doc.source_input_id == "inp-1"
        assert doc.detected_type == "ocr_document"
        assert doc.pages[0].metadata["source_page"] == "kept"

        art_names = {p.intent.name for p in result.artifact_payloads}
        assert any(n.endswith("_bhashini_translated.txt") for n in art_names)
        assert any(n.endswith("_bhashini_translated.docx") for n in art_names)
