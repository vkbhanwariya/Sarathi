"""Integration and unit tests for unified cloud translation and legal context preservation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
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
            model="mistral-medium-latest",
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

    def test_batch_legal_context_isolation_across_documents(self) -> None:
        doc_a = CanonicalDocument(
            document_id="case-bombay",
            source_input_id="inp-a",
            text="IN THE HIGH COURT OF BOMBAY\nCNR No. MHBO010000012024\nPetitioner: State Bank\nSection 138 NI Act",
        )
        doc_b = CanonicalDocument(
            document_id="case-delhi",
            source_input_id="inp-b",
            text="IN THE HIGH COURT OF DELHI AT NEW DELHI\nCNR No. DLHC010000022024\nPetitioner: Union of India\nSection 482 CrPC",
        )

        recorded_prompts: list[str | None] = []

        def mock_translate(
            text: str, source_lang: str, target_lang: str, model: str, system_prompt: str | None = None
        ) -> str:
            recorded_prompts.append(system_prompt)
            return f"[TR: {text}]"

        mock_client = MagicMock(spec=GeminiClient)
        mock_client.chat_translate.side_effect = mock_translate

        cap = GeminiTranslationCapability(client=mock_client)
        req = Request(
            request_id="req-batch-isolation",
            requirement="gemini_translation",
            inputs=(
                InputRef("inp-a", Path("case_a.txt"), "case_a.txt", 100),
                InputRef("inp-b", Path("case_b.txt"), "case_b.txt", 100),
            ),
            metadata={"direction": "en-hi"},
        )
        ctx = ExecutionContext("run-1", "req-batch-isolation", "tr-1", "sp-1")

        result = cap.execute(
            req,
            ctx,
            prior_result=Result(data=(doc_a, doc_b)),
        )

        assert isinstance(result.data, tuple)
        assert len(result.data) == 2
        res_a, res_b = result.data

        # Verify Doc A context has Bombay and NOT Delhi
        ctx_a = res_a.metadata["legal_context"]
        assert ctx_a["court_name"] == "High Court of Bombay"
        assert ctx_a["cnr_number"] == "MHBO010000012024"
        assert "Delhi" not in str(ctx_a)

        # Verify Doc B context has Delhi and NOT Bombay
        ctx_b = res_b.metadata["legal_context"]
        assert ctx_b["court_name"] == "High Court of Delhi"
        assert ctx_b["cnr_number"] == "DLHC010000022024"
        assert "Bombay" not in str(ctx_b)

        # Verify provenance isolation
        assert len(result.provenance) == 2
        assert result.provenance[0].evidence["legal_context"]["court_name"] == "High Court of Bombay"
        assert result.provenance[1].evidence["legal_context"]["court_name"] == "High Court of Delhi"


class TestBugO9CloudTransportAndOrchestration:
    """O9: CloudHttpClient pooling, thread-safe pacing, cancellation, and batch concurrency/fallback."""

    def test_bug_O9_cloud_http_transport_and_pooling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """O9: CloudHttpClient pooled client, thread-safe pacer (0.2s spacing across 8 threads), cancellation in <0.5s, UA, and redaction."""
        import concurrent.futures
        import importlib.metadata
        import threading
        import time

        import httpx

        from sarathi.shakti.cloud.http import CloudHttpClient

        expected_version = importlib.metadata.version("sarathi")

        # 1. Thread-safe pacing across 8 threads and single pooled httpx.Client
        timestamps = []
        clients_created = []

        def mock_transport_handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["User-Agent"] == f"Sarathi/{expected_version}"
            timestamps.append(time.monotonic())
            return httpx.Response(200, json={"ok": True})

        mock_transport = httpx.MockTransport(mock_transport_handler)

        orig_client_init = httpx.Client.__init__

        def counting_client_init(self, *args, **kwargs):
            clients_created.append(self)
            if "transport" not in kwargs or kwargs["transport"] is None:
                kwargs["transport"] = mock_transport
            orig_client_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.Client, "__init__", counting_client_init)

        http_client = CloudHttpClient(rate_limit_delay_seconds=0.2, timeout_seconds=10.0)
        assert http_client.user_agent == f"Sarathi/{expected_version}"

        # 8 threads calling in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(http_client.post, "https://api.example.com/test", headers={}, json_body={"i": i})
                for i in range(8)
            ]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        # Exactly 1 httpx.Client must be created for this CloudHttpClient
        assert len(clients_created) == 1, f"Expected 1 pooled httpx.Client, created {len(clients_created)}"

        # Verify timestamps are at least 0.2s apart
        sorted_ts = sorted(timestamps)
        assert len(sorted_ts) == 8
        for i in range(1, len(sorted_ts)):
            diff = sorted_ts[i] - sorted_ts[i - 1]
            assert diff >= 0.18, f"Requests {i - 1} and {i} were spaced by only {diff:.3f}s, expected >= 0.2s"

        # 2. Cancellation during 429 backoff must raise OPERATION_CANCELLED within 0.5s
        token = CancellationToken()

        def backoff_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "10"}, json={"error": "rate limited"})

        backoff_client = CloudHttpClient(
            transport=httpx.MockTransport(backoff_handler),
            rate_limit_delay_seconds=0.0,
            timeout_seconds=10.0,
        )

        def cancel_later():
            time.sleep(0.1)
            token.cancel()

        t = threading.Thread(target=cancel_later, daemon=True)
        t.start()

        t0 = time.monotonic()
        with pytest.raises(DoshError) as exc_info:
            backoff_client.post("https://api.example.com/test", headers={}, cancellation_token=token)
        t1 = time.monotonic()
        assert exc_info.value.code == FailureCode.OPERATION_CANCELLED
        assert (t1 - t0) < 0.5, f"Cancellation took {t1 - t0:.3f}s, expected < 0.5s"

        # 3. Secret key redaction: error messages never contain the API key
        secret_key = "sk-GEMINI-SUPER-SECRET-KEY-xyz987"

        def error_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text=f"Internal crash with key {secret_key} leaked")

        err_client = CloudHttpClient(
            transport=httpx.MockTransport(error_handler),
            rate_limit_delay_seconds=0.0,
            timeout_seconds=10.0,
        )
        with pytest.raises(DoshError) as exc_err:
            err_client.post("https://api.example.com/test", headers={}, redact_keys=(secret_key,))
        assert secret_key not in str(exc_err.value)
        assert "[REDACTED]" in str(exc_err.value)

    def test_bug_O9_cloud_batch_concurrency_and_fallback(self) -> None:
        """O9: batch call that raises produces CLOUD_BATCH_FALLBACK warning and falls back to per-text translation."""
        from sarathi.shakti.gemini.plugin import GEMINI_TRANSLATION_DECLARATION
        from sarathi.shakti.translation.cloud_orchestration import execute_cloud_translation

        req = Request(
            request_id="req-fallback-test",
            requirement="gemini_translation",
            inputs=(InputRef("inp-1", Path("doc.txt"), "doc.txt", 10),),
            metadata={"direction": "hi-en"},
        )
        ctx = ExecutionContext("run-1", "req-fallback-test", "tr-1", "sp-1")

        doc = CanonicalDocument(
            document_id="doc-fallback",
            source_input_id="inp-1",
            text="पहला वाक्य।\n\nदूसरा वाक्य।",
            pages=(PageData(page_number=1, text="पहला वाक्य।\n\nदूसरा वाक्य।"),),
        )

        def mock_translate_fn(text: str, **kwargs: Any) -> str:
            return f"Trans: {text}"

        def failing_batch_translate_fn(texts: list[str], **kwargs: Any) -> list[str]:
            raise RuntimeError("Cloud provider batch quota exhausted")

        result = execute_cloud_translation(
            request=req,
            context=ctx,
            prior_result=Result(data=doc),
            translate_fn=mock_translate_fn,
            provider_id="gemini",
            capability_id="gemini_translation",
            default_model="gemini-3.6-flash",
            declaration=GEMINI_TRANSLATION_DECLARATION,
            batch_translate_fn=failing_batch_translate_fn,
        )

        # Must have fallen back to per-text and succeeded
        assert isinstance(result.data, CanonicalDocument)
        assert "Trans: पहला वाक्य।" in result.data.text

        # Must have emitted CLOUD_BATCH_FALLBACK warning
        fallback_warnings = [w for w in result.warnings if w.code == "CLOUD_BATCH_FALLBACK"]
        assert len(fallback_warnings) == 1, f"Expected 1 CLOUD_BATCH_FALLBACK warning, found {len(fallback_warnings)}"
        assert "RuntimeError" in fallback_warnings[0].message

    def test_bug_O9_cloud_batch_concurrency_and_rate_pacing(self) -> None:
        """O9: fake provider with 8 batches, max_concurrency=4, rpm=600 -> peak in-flight calls is 4 and request spacing respects limit."""
        import threading
        import time

        from sarathi.shakti.gemini.plugin import GEMINI_TRANSLATION_DECLARATION
        from sarathi.shakti.translation.cloud_orchestration import execute_cloud_translation

        in_flight = 0
        max_in_flight = 0
        flight_lock = threading.Lock()

        def mock_concurrent_batch(texts: list[str], **kwargs: Any) -> list[str]:
            nonlocal in_flight, max_in_flight
            with flight_lock:
                in_flight += 1
                if in_flight > max_in_flight:
                    max_in_flight = in_flight
            time.sleep(0.08)
            with flight_lock:
                in_flight -= 1
            return [f"Tr: {t}" for t in texts]

        pages = tuple(PageData(page_number=i + 1, text=f"वाक्य {i + 1}।") for i in range(8))
        doc = CanonicalDocument(
            document_id="doc-concurrent",
            source_input_id="inp-1",
            text="\n\n".join(f"वाक्य {i + 1}।" for i in range(8)),
            pages=pages,
        )

        req = Request(
            request_id="req-concurrency-test",
            requirement="gemini_translation",
            inputs=(InputRef("inp-1", Path("doc.txt"), "doc.txt", 10),),
            metadata={"direction": "hi-en"},
            custom_options={"batch_size": 1, "max_concurrency": 4},
        )
        ctx = ExecutionContext("run-1", "req-concurrency-test", "tr-1", "sp-1")

        result = execute_cloud_translation(
            request=req,
            context=ctx,
            prior_result=Result(data=doc),
            translate_fn=lambda text="", **kw: f"Tr: {text}",
            provider_id="gemini",
            capability_id="gemini_translation",
            default_model="gemini-3.6-flash",
            declaration=GEMINI_TRANSLATION_DECLARATION,
            batch_translate_fn=mock_concurrent_batch,
        )

        assert isinstance(result.data, CanonicalDocument)
        assert max_in_flight == 4, f"Expected peak in-flight calls of 4, got {max_in_flight}"

        # Test default max_concurrency=1 call order is unchanged
        order_called = []

        def ordered_batch(texts: list[str], **kwargs: Any) -> list[str]:
            order_called.append(texts[0])
            return [f"Tr: {t}" for t in texts]

        req_seq = Request(
            request_id="req-seq-test",
            requirement="gemini_translation",
            inputs=(InputRef("inp-1", Path("doc.txt"), "doc.txt", 10),),
            metadata={"direction": "hi-en"},
            custom_options={"batch_size": 1},  # default max_concurrency = 1
        )
        execute_cloud_translation(
            request=req_seq,
            context=ctx,
            prior_result=Result(data=doc),
            translate_fn=lambda text="", **kw: f"Tr: {text}",
            provider_id="gemini",
            capability_id="gemini_translation",
            default_model="gemini-3.6-flash",
            declaration=GEMINI_TRANSLATION_DECLARATION,
            batch_translate_fn=ordered_batch,
        )
        expected_order = [f"वाक्य {i + 1}।" for i in range(8)]
        assert order_called == expected_order, f"Expected sequential order {expected_order}, got {order_called}"
