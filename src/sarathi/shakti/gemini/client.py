"""Zero-leak direct REST client for Google Gemini API."""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from sarathi.dosh import DoshError, FailureCode

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiClient:
    """Direct REST transport for Google Gemini API without vendor SDK overhead."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
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
                message="Google Gemini API key is not configured. Set the GEMINI_API_KEY environment variable.",
            )
        return self._api_key.strip()

    def _post(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Perform sanitized HTTP POST to Gemini generateContent endpoint."""
        api_key = self._get_api_key()
        url = f"{self._base_url}/models/{model}:generateContent"
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Sarathi/2.0",
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        status_code = 0
        resp_text = ""
        try:
            import httpx

            with httpx.Client(timeout=self._timeout_seconds) as client:
                resp = client.post(url, headers=headers, content=body_bytes)
                status_code = resp.status_code
                resp_text = resp.text
        except ImportError:
            import urllib.error
            import urllib.request

            req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self._timeout_seconds) as response:
                    status_code = response.getcode()
                    resp_text = response.read().decode("utf-8")
            except urllib.error.HTTPError as http_err:
                status_code = http_err.code
                resp_text = http_err.read().decode("utf-8", errors="replace")
            except urllib.error.URLError as url_err:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Network connection to Google Gemini API failed.",
                ) from url_err
        except Exception as exc:
            sanitized_err = str(exc).replace(api_key, "[REDACTED_API_KEY]") if api_key else "Network error"
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message=f"Gemini API request failed: {sanitized_err}",
            ) from exc

        # Map HTTP error codes to canonical FailureCodes with sanitized messages
        if status_code in (401, 403):
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="Google Gemini API authentication failed. Verify that GEMINI_API_KEY is valid.",
            )
        if status_code == 429:
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message="Google Gemini API rate limit exceeded.",
            )
        if status_code >= 400:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message=f"Google Gemini API returned error status {status_code}.",
            )

        try:
            return json.loads(resp_text)
        except json.JSONDecodeError as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to parse JSON response from Google Gemini API.",
            ) from err

    def process_ocr(
        self,
        content_bytes: bytes,
        media_type: str = "image/jpeg",
        model: str = _DEFAULT_MODEL,
    ) -> dict[str, Any]:
        """Extract text and layout from image/PDF bytes using Gemini multimodal API."""
        if not content_bytes:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Empty content passed to Gemini OCR.",
            )

        b64_data = base64.b64encode(content_bytes).decode("ascii")
        prompt_text = (
            "Extract all text from this document accurately. Preserve headings, paragraphs, "
            "and all tabular data as standard Markdown tables. Maintain document flow and script fidelity."
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": media_type,
                                "data": b64_data,
                            }
                        },
                        {"text": prompt_text},
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
            },
        }

        return self._post(model=model, payload=payload)

    def chat_translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        model: str = _DEFAULT_MODEL,
    ) -> str:
        """Translate text from source_lang to target_lang using Gemini."""
        if not text.strip():
            return ""

        prompt = (
            f"You are a professional legal and technical document translator.\n"
            f"Translate the following text faithfully from {source_lang} into {target_lang}.\n"
            f"Preserve all Markdown formatting, structure, numbers, and proper nouns accurately.\n"
            f"Output ONLY the translated text without commentary or preamble.\n\n"
            f"{text}"
        )

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
            },
        }

        data = self._post(model=model, payload=payload)
        candidates = data.get("candidates", [])
        if not candidates:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Google Gemini returned empty response for translation.",
            )

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        return "".join(part.get("text", "") for part in parts).strip()
