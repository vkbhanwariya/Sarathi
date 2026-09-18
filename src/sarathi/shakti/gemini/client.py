"""Direct REST client for Google Gemini API with sanitized error handling."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any

from sarathi.dosh import DoshError, FailureCode

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MODEL = "gemini-3.6-flash"


class GeminiClient:
    """Direct REST transport for Google Gemini API without vendor SDK overhead."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        rate_limit_delay_seconds: float = 2.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._rate_limit_delay_seconds = max(0.0, float(rate_limit_delay_seconds))
        self._last_request_time: float = 0.0

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

        # Enforce rate pacing interval to prevent bursting past RPM limit
        if self._rate_limit_delay_seconds > 0.0 and self._last_request_time > 0.0:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self._rate_limit_delay_seconds:
                time.sleep(self._rate_limit_delay_seconds - elapsed)
        self._last_request_time = time.monotonic()

        status_code = 0
        resp_text = ""
        resp_headers: Any = {}
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                import httpx

                with httpx.Client(timeout=self._timeout_seconds) as client:
                    resp = client.post(url, headers=headers, content=body_bytes)
                    status_code = resp.status_code
                    resp_text = resp.text
                    resp_headers = getattr(resp, "headers", {})
            except ImportError as imp_err:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="HTTP transport dependency (httpx) is not installed.",
                ) from imp_err
            except httpx.TimeoutException as exc:
                if attempt < max_attempts - 1:
                    time.sleep(1.0)
                    self._last_request_time = time.monotonic()
                    continue
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Network timeout while connecting to Google Gemini API.",
                ) from exc
            except Exception as exc:
                if attempt < max_attempts - 1:
                    time.sleep(1.0)
                    self._last_request_time = time.monotonic()
                    continue
                sanitized_err = str(exc).replace(api_key, "[REDACTED_API_KEY]") if api_key else "Network error"
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message=f"Gemini API request failed: {sanitized_err}",
                ) from exc

            # Retry transient 429 Rate Limit spikes respecting Retry-After header with exponential backoff
            if status_code == 429 and attempt < max_attempts - 1:
                wait_sec = 0.0
                if hasattr(resp_headers, "get"):
                    raw_val = resp_headers.get("retry-after") or resp_headers.get("x-ratelimit-reset")
                    if isinstance(raw_val, (int, float)):
                        wait_sec = float(raw_val)
                    elif isinstance(raw_val, str) and raw_val.strip():
                        try:
                            wait_sec = float(raw_val.strip())
                        except ValueError:
                            pass
                if wait_sec <= 0.0:
                    wait_sec = 2.5 * (2 ** attempt)
                else:
                    wait_sec += 0.5
                time.sleep(wait_sec)
                self._last_request_time = time.monotonic()
                continue

            # Retry transient 503 High Demand spikes
            if status_code == 503 and attempt < max_attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                self._last_request_time = time.monotonic()
                continue
            break

        # Map HTTP error codes to canonical FailureCodes with sanitized messages
        if status_code in (401, 403):
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="Google Gemini API authentication failed. Verify that GEMINI_API_KEY is valid.",
            )
        if status_code == 429:
            detail_msg = ""
            try:
                err_data = json.loads(resp_text)
                if isinstance(err_data, dict) and "error" in err_data:
                    detail_msg = str(err_data["error"].get("message", "")).strip()
            except Exception:
                pass
            sanitized = f": {detail_msg}" if detail_msg else ""
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message=f"Google Gemini API rate limit exceeded{sanitized}. Consider increasing rate_limit_delay_seconds or upgrading tier.",
            )
        if status_code == 404:
            detail_msg = ""
            try:
                err_data = json.loads(resp_text)
                if isinstance(err_data, dict) and "error" in err_data:
                    detail_msg = str(err_data["error"].get("message", "")).strip()
            except Exception:
                pass
            sanitized = f": {detail_msg}" if detail_msg else ""
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message=(
                    f"Google Gemini API returned error status 404 (Model or Resource Not Found){sanitized}. "
                    f"Verify configured model '{model}' exists (e.g. 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash')."
                ),
            )
        if status_code >= 400:
            detail_msg = ""
            try:
                err_data = json.loads(resp_text)
                if isinstance(err_data, dict) and "error" in err_data:
                    detail_msg = str(err_data["error"].get("message", "")).strip()
            except Exception:
                pass
            sanitized = f": {detail_msg}" if detail_msg else ""
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message=f"Google Gemini API returned error status {status_code}{sanitized}.",
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
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Translate text from source_lang to target_lang using Gemini with legal context awareness."""
        if not text.strip():
            return ""

        sys_inst = system_prompt or kwargs.get("system_instruction")
        if sys_inst:
            prompt = f"### Document Content to Translate:\n{text}"
        else:
            prompt = (
                f"You are a professional legal and technical document translator.\n"
                f"Translate the following text faithfully from {source_lang} into {target_lang}.\n"
                f"Preserve all Markdown formatting, structure, numbers, and proper nouns accurately.\n"
                f"Output ONLY the translated text without commentary or preamble.\n\n"
                f"{text}"
            )

        payload: dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
            },
        }
        if sys_inst:
            payload["system_instruction"] = {"parts": [{"text": sys_inst}]}

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

    def batch_translate(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        model: str = _DEFAULT_MODEL,
        system_prompt: str | None = None,
        batch_size: int = 16,
        **kwargs: Any,
    ) -> list[str]:
        """Translate a sequence of texts using Gemini, grouping them into multi-segment batches."""
        if not texts:
            return []
        if len(texts) == 1:
            return [
                self.chat_translate(
                    texts[0],
                    source_lang,
                    target_lang,
                    model=model,
                    system_prompt=system_prompt,
                    **kwargs,
                )
            ]

        results: list[str] = [""] * len(texts)
        for batch_start in range(0, len(texts), batch_size):
            batch_indices = list(range(batch_start, min(batch_start + batch_size, len(texts))))
            batch_items = [(idx, texts[idx]) for idx in batch_indices]

            non_empty = [(idx, text) for idx, text in batch_items if text and text.strip()]
            if not non_empty:
                for idx, text in batch_items:
                    results[idx] = text
                continue

            if len(non_empty) == 1:
                idx, text = non_empty[0]
                results[idx] = self.chat_translate(
                    text,
                    source_lang,
                    target_lang,
                    model=model,
                    system_prompt=system_prompt,
                    **kwargs,
                )
                for i, t in batch_items:
                    if i != idx:
                        results[i] = t
                continue

            segment_blocks = "\n".join(f'<segment id="{idx}">\n{text}\n</segment>' for idx, text in non_empty)
            sys_inst = system_prompt or kwargs.get("system_instruction")
            instructions = (
                f"You are a professional legal, administrative, and technical translator.\n"
                f"Translate each text segment faithfully from {source_lang} to {target_lang}.\n"
                f"Strict Rules:\n"
                f"- Return every segment enclosed in its exact matching `<segment id=\"...\">` and `</segment>` tags.\n"
                f"- Do not omit, combine, or reorder segments.\n"
                f"- Strictly preserve formatting, line breaks, tokens enclosed in '__PROTECTED_SPAN_', citations, section numbers, dates, and amounts.\n"
                f"- Output ONLY the tagged translated segments without preamble or commentary."
            )
            if sys_inst:
                instructions = f"{sys_inst}\n\n{instructions}"

            prompt = f"{instructions}\n\n### Document Segments to Translate:\n{segment_blocks}"
            payload: dict[str, Any] = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1},
            }

            try:
                resp = self._post(model=model, payload=payload)
                candidates = resp.get("candidates", [])
                raw_out = ""
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    raw_out = "".join(p.get("text", "") for p in parts)

                parsed_segments: dict[int, str] = {}
                for m in re.finditer(r'<segment\s+id=["\']?(\d+)["\']?\s*>(.*?)</segment>', raw_out, re.DOTALL):
                    seg_id = int(m.group(1))
                    parsed_segments[seg_id] = m.group(2).strip()

                for idx, text in non_empty:
                    if idx in parsed_segments and parsed_segments[idx]:
                        results[idx] = parsed_segments[idx]
                    else:
                        results[idx] = self.chat_translate(
                            text,
                            source_lang,
                            target_lang,
                            model=model,
                            system_prompt=system_prompt,
                            **kwargs,
                        )

                for idx, text in batch_items:
                    if not text or not text.strip():
                        results[idx] = text

            except Exception:
                for idx, text in non_empty:
                    results[idx] = self.chat_translate(
                        text,
                        source_lang,
                        target_lang,
                        model=model,
                        system_prompt=system_prompt,
                        **kwargs,
                    )
                for idx, text in batch_items:
                    if not text or not text.strip():
                        results[idx] = text

        return results
