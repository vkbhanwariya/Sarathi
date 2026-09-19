"""Direct REST client for Microsoft Azure AI Services with sanitized error handling."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.cloud.http import CloudHttpClient, interruptible_sleep

_DEFAULT_API_VERSION = "2024-11-30"
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_TRANSLATOR_URL = "https://api.cognitive.microsofttranslator.com"


class AzureClient:
    """Direct REST transport for Azure Document Intelligence and Azure Translator."""

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        translator_key: str | None = None,
        translator_region: str | None = None,
        translator_endpoint: str = _DEFAULT_TRANSLATOR_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        poll_timeout_seconds: float = 600.0,
        rate_limit_delay_seconds: float = 0.0,
        requests_per_minute: float | None = None,
        http_client: CloudHttpClient | None = None,
        transport: Any | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("AZURE_API_KEY") or os.environ.get("AZURE_VISION_KEY")
        self._endpoint = (
            endpoint or os.environ.get("AZURE_ENDPOINT") or os.environ.get("AZURE_VISION_ENDPOINT") or ""
        ).rstrip("/")
        self._translator_key = translator_key or os.environ.get("AZURE_TRANSLATOR_KEY") or self._api_key
        self._translator_region = translator_region or os.environ.get("AZURE_TRANSLATOR_REGION")
        self._translator_endpoint = (translator_endpoint or _DEFAULT_TRANSLATOR_URL).rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._poll_timeout_seconds = poll_timeout_seconds
        self._http: CloudHttpClient = http_client or CloudHttpClient(
            base_url=self._endpoint,
            timeout_seconds=self._timeout_seconds,
            rate_limit_delay_seconds=rate_limit_delay_seconds,
            requests_per_minute=requests_per_minute,
            transport=transport,
        )

    @property
    def is_configured(self) -> bool:
        """Return True if at least API key and endpoint are present."""
        return bool(self._api_key and self._api_key.strip() and self._endpoint and self._endpoint.strip())

    def _get_ocr_credentials(self) -> tuple[str, str]:
        """Resolve and validate OCR credentials."""
        if not self._api_key or not self._api_key.strip():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Azure API key is not configured. Set AZURE_API_KEY environment variable.",
            )
        if not self._endpoint or not self._endpoint.strip():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Azure Endpoint is not configured. Set AZURE_ENDPOINT environment variable.",
            )
        return self._api_key.strip(), self._endpoint.strip()

    def _get_translator_credentials(self) -> tuple[str, str, str | None]:
        """Resolve and validate Translator credentials."""
        key = self._translator_key or self._api_key
        if not key or not key.strip():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Azure Translator API key is not configured. Set AZURE_TRANSLATOR_KEY or AZURE_API_KEY.",
            )
        return key.strip(), self._translator_endpoint, self._translator_region

    def analyze_layout(
        self,
        content_bytes: bytes,
        media_type: str = "application/pdf",
        api_version: str = _DEFAULT_API_VERSION,
        cancellation_token: Any | None = None,
    ) -> dict[str, Any]:
        """Analyze document layout using Azure Document Intelligence REST API."""
        if not content_bytes:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Empty content passed to Azure Document Intelligence OCR.",
            )

        api_key, endpoint = self._get_ocr_credentials()
        url = f"{endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze?api-version={api_version}"
        headers = {
            "Ocp-Apim-Subscription-Key": api_key,
            "Content-Type": media_type,
        }

        resp = self._http.post(
            url,
            headers=headers,
            content=content_bytes,
            cancellation_token=cancellation_token,
            redact_keys=(api_key,),
        )

        resp_headers = getattr(resp, "headers", {}) or {}
        status_code = getattr(resp, "status_code", 200)

        # Azure returns 202 Accepted with Operation-Location for async analysis
        if status_code == 202:
            op_url = resp_headers.get("Operation-Location") if hasattr(resp_headers, "get") else None
            if not op_url:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Azure returned 202 Accepted without Operation-Location header.",
                )
            poll_headers = {"Ocp-Apim-Subscription-Key": api_key}
            start_time = time.monotonic()
            while time.monotonic() - start_time < self._poll_timeout_seconds:
                if cancellation_token is not None and cancellation_token.is_cancelled:
                    cancellation_token.check_cancelled()

                poll_resp = self._http.get(
                    op_url,
                    headers=poll_headers,
                    cancellation_token=cancellation_token,
                    redact_keys=(api_key,),
                )
                p_headers = getattr(poll_resp, "headers", {}) or {}
                if getattr(poll_resp, "status_code", 200) == 200:
                    poll_data = poll_resp.json()
                    status = poll_data.get("status")
                    if status == "succeeded":
                        return poll_data.get("analyzeResult", poll_data)
                    if status in ("failed", "canceled"):
                        raise DoshError(
                            code=FailureCode.EXECUTION_FAILED,
                            message=f"Azure Document Intelligence operation {status}.",
                        )
                    wait_s = 0.5
                    p_retry_after = p_headers.get("Retry-After") if hasattr(p_headers, "get") else None
                    if p_retry_after:
                        try:
                            wait_s = max(0.1, float(p_retry_after))
                        except (ValueError, TypeError):
                            pass
                    interruptible_sleep(wait_s, cancellation_token)
                else:
                    interruptible_sleep(0.5, cancellation_token)

            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message="Azure Document Intelligence layout analysis timed out.",
            )

        try:
            return resp.json().get("analyzeResult", resp.json())
        except Exception:
            return {}

    def translate_text(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """Translate text using Azure AI Translator REST API v3.0."""
        if not text.strip():
            return ""

        key, endpoint, region = self._get_translator_credentials()
        s_code = "hi" if "hindi" in source_lang.lower() else ("en" if "english" in source_lang.lower() else source_lang)
        t_code = "en" if "english" in target_lang.lower() else ("hi" if "hindi" in target_lang.lower() else target_lang)

        url = f"{endpoint}/translate?api-version=3.0&to={t_code}&from={s_code}"
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/json",
        }
        if region:
            headers["Ocp-Apim-Subscription-Region"] = region

        body_bytes = json.dumps([{"Text": text}]).encode("utf-8")
        resp = self._http.post(
            url,
            headers=headers,
            content=body_bytes,
            redact_keys=(key,),
        )
        try:
            data = resp.json()
        except Exception as exc:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to parse JSON response from Azure Translator.",
            ) from exc

        if isinstance(data, list) and len(data) > 0:
            translations = data[0].get("translations", [])
            if translations:
                trans_text = translations[0].get("text", "").strip()
                if trans_text:
                    return trans_text
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Azure Translator response contained no translations.",
        )

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        batch_size: int = 32,
    ) -> list[str]:
        """Translate multiple texts in batches using Azure AI Translator REST API v3.0."""
        if not texts:
            return []
        if len(texts) == 1:
            return [self.translate_text(texts[0], source_lang, target_lang)]

        key, endpoint, region = self._get_translator_credentials()
        s_code = "hi" if "hindi" in source_lang.lower() else ("en" if "english" in source_lang.lower() else source_lang)
        t_code = "en" if "english" in target_lang.lower() else ("hi" if "hindi" in target_lang.lower() else target_lang)

        url = f"{endpoint}/translate?api-version=3.0&to={t_code}&from={s_code}"
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/json",
        }
        if region:
            headers["Ocp-Apim-Subscription-Region"] = region

        results: list[str] = [""] * len(texts)
        for batch_start in range(0, len(texts), batch_size):
            batch_indices = list(range(batch_start, min(batch_start + batch_size, len(texts))))
            batch_items = [(idx, texts[idx]) for idx in batch_indices]

            non_empty = [(idx, text) for idx, text in batch_items if text and text.strip()]
            if not non_empty:
                for idx, text in batch_items:
                    results[idx] = text
                continue

            body_payload = [{"Text": text} for _, text in non_empty]
            body_bytes = json.dumps(body_payload).encode("utf-8")

            try:
                resp = self._http.post(
                    url,
                    headers=headers,
                    content=body_bytes,
                    redact_keys=(key,),
                )
                data = resp.json()
                if isinstance(data, list) and len(data) == len(non_empty):
                    for i, (orig_idx, _) in enumerate(non_empty):
                        translations = data[i].get("translations", [])
                        if translations:
                            results[orig_idx] = translations[0].get("text", "").strip()
                else:
                    for orig_idx, text in non_empty:
                        results[orig_idx] = self.translate_text(text, source_lang, target_lang)

                for idx, text in batch_items:
                    if not text or not text.strip():
                        results[idx] = text

            except DoshError:
                raise
            except Exception:
                for orig_idx, text in non_empty:
                    results[orig_idx] = self.translate_text(text, source_lang, target_lang)
                for idx, text in batch_items:
                    if not text or not text.strip():
                        results[idx] = text

        return results
