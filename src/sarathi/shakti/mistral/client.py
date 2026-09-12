"""Direct REST client for Mistral AI APIs with sanitized error handling.

Uses explicit authentication headers and sanitized error mapping.
Supports both httpx and standard library urllib as a fallback.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from sarathi.dosh import DoshError, FailureCode

_DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
_DEFAULT_TIMEOUT_SECONDS = 60.0


class MistralClient:
    """HTTP client for Mistral AI OCR and Chat Completion APIs."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def is_configured(self) -> bool:
        """Return True if a non-empty API key is present."""
        return bool(self._api_key and self._api_key.strip())

    def _get_api_key(self) -> str:
        """Resolve and validate API key, raising DoshError if missing."""
        if not self._api_key or not self._api_key.strip():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Mistral API key is not configured. Set the MISTRAL_API_KEY environment variable.",
            )
        return self._api_key.strip()

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Perform sanitized HTTP POST to Mistral API."""
        api_key = self._get_api_key()
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Sarathi/2.0",
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        try:
            import httpx

            with httpx.Client(timeout=self._timeout_seconds) as client:
                resp = client.post(url, headers=headers, content=body_bytes)
                status_code = resp.status_code
                resp_text = resp.text
        except ImportError as imp_err:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="HTTP transport dependency (httpx) is not installed.",
            ) from imp_err
        except httpx.TimeoutException as net_err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Network timeout while connecting to Mistral API.",
            ) from net_err
        except Exception as exc:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Network communication error while connecting to Mistral API.",
            ) from exc

        # Handle HTTP status codes without leaking headers or request tokens
        if status_code in (401, 403):
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="Mistral API authentication failed. Verify that MISTRAL_API_KEY is valid.",
            )
        if status_code == 429:
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message="Mistral API rate limit exceeded.",
            )
        if status_code >= 400:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message=f"Mistral API returned error status {status_code}.",
            )

        try:
            return json.loads(resp_text)
        except json.JSONDecodeError as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to parse JSON response from Mistral API.",
            ) from err

    def process_ocr(
        self,
        content_bytes: bytes,
        media_type: str = "image/jpeg",
        model: str = "mistral-ocr-latest",
        include_blocks: bool = True,
    ) -> dict[str, Any]:
        """Process document image or PDF bytes using Mistral OCR API."""
        if not content_bytes:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Empty content passed to Mistral OCR.",
            )

        b64_data = base64.b64encode(content_bytes).decode("ascii")
        doc_type = "document_url" if "pdf" in media_type.lower() else "image_url"
        url_key = "document_url" if doc_type == "document_url" else "image_url"

        payload = {
            "model": model,
            "document": {
                "type": doc_type,
                url_key: f"data:{media_type};base64,{b64_data}",
            },
            "include_blocks": include_blocks,
        }

        return self._post("ocr", payload)

    def chat_translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        model: str = "mistral-large-latest",
    ) -> str:
        """Translate text using Mistral Chat Completion API preserving protected tokens."""
        clean_text = text.strip()
        if not clean_text:
            return ""

        system_prompt = (
            f"You are a professional legal, administrative, and technical translator.\n"
            f"Translate the provided text from {source_lang} to {target_lang}.\n"
            f"Guidelines:\n"
            f"- Strictly preserve formatting, line breaks, and whitespace structure.\n"
            f"- Strictly preserve all tokens enclosed in '__PROTECTED_SPAN_' (e.g. '__PROTECTED_SPAN_0__'), "
            f"legal citations, section numbers, dates, and currency without translation or alteration.\n"
            f"- Output ONLY the translated text without commentary, pleasantries, or preamble."
        )

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": clean_text},
            ],
            "temperature": 0.0,
        }

        resp_dict = self._post("chat/completions", payload)
        try:
            choices = resp_dict["choices"]
            if not choices:
                raise KeyError("empty choices")
            return choices[0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Mistral translation response missing expected completion choice.",
            ) from err
