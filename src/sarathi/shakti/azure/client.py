"""Direct REST client for Microsoft Azure AI Services with sanitized error handling."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from sarathi.dosh import DoshError, FailureCode

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
    ) -> None:
        self._api_key = api_key or os.environ.get("AZURE_API_KEY") or os.environ.get("AZURE_VISION_KEY")
        self._endpoint = (endpoint or os.environ.get("AZURE_ENDPOINT") or os.environ.get("AZURE_VISION_ENDPOINT") or "").rstrip("/")
        self._translator_key = translator_key or os.environ.get("AZURE_TRANSLATOR_KEY") or self._api_key
        self._translator_region = translator_region or os.environ.get("AZURE_TRANSLATOR_REGION")
        self._translator_endpoint = (translator_endpoint or _DEFAULT_TRANSLATOR_URL).rstrip("/")
        self._timeout_seconds = timeout_seconds

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
            "User-Agent": "Sarathi/2.0",
        }

        try:
            import httpx

            with httpx.Client(timeout=self._timeout_seconds) as client:
                resp = client.post(url, headers=headers, content=content_bytes)

                if resp.status_code in (401, 403):
                    raise DoshError(
                        code=FailureCode.SECURITY_DENIED,
                        message="Azure authentication failed. Verify AZURE_API_KEY and AZURE_ENDPOINT.",
                    )
                if resp.status_code == 429:
                    raise DoshError(
                        code=FailureCode.RESOURCE_UNAVAILABLE,
                        message="Azure API rate limit exceeded.",
                    )
                if resp.status_code >= 400:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message=f"Azure Document Intelligence returned error status {resp.status_code}.",
                    )

                # Azure returns 202 Accepted with Operation-Location for async analysis
                if resp.status_code == 202:
                    op_url = resp.headers.get("Operation-Location")
                    if not op_url:
                        raise DoshError(
                            code=FailureCode.EXECUTION_FAILED,
                            message="Azure returned 202 Accepted without Operation-Location header.",
                        )
                    poll_headers = {"Ocp-Apim-Subscription-Key": api_key, "User-Agent": "Sarathi/2.0"}
                    start_time = time.monotonic()
                    while time.monotonic() - start_time < self._timeout_seconds:
                        time.sleep(0.5)
                        poll_resp = client.get(op_url, headers=poll_headers)
                        if poll_resp.status_code == 200:
                            poll_data = poll_resp.json()
                            status = poll_data.get("status")
                            if status == "succeeded":
                                return poll_data.get("analyzeResult", poll_data)
                            if status in ("failed", "canceled"):
                                raise DoshError(
                                    code=FailureCode.EXECUTION_FAILED,
                                    message=f"Azure Document Intelligence operation {status}.",
                                )
                    raise DoshError(
                        code=FailureCode.RESOURCE_UNAVAILABLE,
                        message="Azure Document Intelligence layout analysis timed out.",
                    )

                return resp.json().get("analyzeResult", resp.json())

        except DoshError:
            raise
        except Exception as exc:
            sanitized = str(exc).replace(api_key, "[REDACTED]") if api_key else "Azure request failed"
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message=f"Azure Document Intelligence request failed: {sanitized}",
            ) from exc

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
        # Map common language names to 2-letter codes if necessary
        s_code = "hi" if "hindi" in source_lang.lower() else ("en" if "english" in source_lang.lower() else source_lang)
        t_code = "en" if "english" in target_lang.lower() else ("hi" if "hindi" in target_lang.lower() else target_lang)

        url = f"{endpoint}/translate?api-version=3.0&to={t_code}&from={s_code}"
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/json",
            "User-Agent": "Sarathi/2.0",
        }
        if region:
            headers["Ocp-Apim-Subscription-Region"] = region

        body_bytes = json.dumps([{"Text": text}]).encode("utf-8")

        try:
            import httpx

            with httpx.Client(timeout=self._timeout_seconds) as client:
                resp = client.post(url, headers=headers, content=body_bytes)

                if resp.status_code in (401, 403):
                    raise DoshError(
                        code=FailureCode.SECURITY_DENIED,
                        message="Azure Translator authentication failed. Verify AZURE_TRANSLATOR_KEY.",
                    )
                if resp.status_code == 429:
                    raise DoshError(
                        code=FailureCode.RESOURCE_UNAVAILABLE,
                        message="Azure Translator rate limit exceeded.",
                    )
                if resp.status_code >= 400:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message=f"Azure Translator returned error status {resp.status_code}.",
                    )

                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    translations = data[0].get("translations", [])
                    if translations:
                        return translations[0].get("text", "").strip()
                return text
        except DoshError:
            raise
        except Exception as exc:
            sanitized = str(exc).replace(key, "[REDACTED]") if key else "Azure translation request failed"
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message=f"Azure Translator request failed: {sanitized}",
            ) from exc
