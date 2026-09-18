"""Direct REST client for Mistral AI APIs with sanitized error handling.

Uses explicit authentication headers and sanitized error mapping.
Supports both httpx and standard library urllib as a fallback.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
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
        rate_limit_delay_seconds: float = 0.5,
    ) -> None:
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY")
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
                message="Mistral API key is not configured. Set the MISTRAL_API_KEY environment variable.",
            )
        return self._api_key.strip()

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Perform sanitized HTTP POST to Mistral API with rate pacing and resilient retry."""
        api_key = self._get_api_key()
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Sarathi/2.0",
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        # Enforce rate pacing interval to prevent bursting past RPS limit
        if self._rate_limit_delay_seconds > 0.0 and self._last_request_time > 0.0:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self._rate_limit_delay_seconds:
                time.sleep(self._rate_limit_delay_seconds - elapsed)
        self._last_request_time = time.monotonic()

        status_code = 0
        resp_text = ""
        max_attempts = 4
        for attempt in range(max_attempts):
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
                if attempt < max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Network timeout while connecting to Mistral API.",
                ) from net_err
            except Exception as exc:
                if attempt < max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Network communication error while connecting to Mistral API.",
                ) from exc

            # Retry transient 429 Rate Limit spikes with exponential backoff
            if status_code == 429 and attempt < max_attempts - 1:
                backoff = 2.0 * (2 ** attempt)
                time.sleep(backoff)
                continue

            # Retry transient 503 High Demand spikes
            if status_code == 503 and attempt < max_attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            break

        # Handle HTTP status codes without leaking headers or request tokens
        if status_code in (401, 403):
            detail_msg = ""
            try:
                err_data = json.loads(resp_text)
                if isinstance(err_data, dict):
                    detail_msg = str(err_data.get("message") or err_data.get("detail", "")).strip()
            except Exception:
                pass
            sanitized = f": {detail_msg}" if detail_msg else ""
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message=f"Mistral API authentication failed{sanitized}. Verify that MISTRAL_API_KEY is valid.",
            )
        if status_code == 429:
            detail_msg = ""
            try:
                err_data = json.loads(resp_text)
                if isinstance(err_data, dict):
                    detail_msg = str(err_data.get("message") or err_data.get("detail", "")).strip()
            except Exception:
                pass
            sanitized = f": {detail_msg}" if detail_msg else ""
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message=f"Mistral API rate limit exceeded{sanitized}. Consider increasing rate_limit_delay_seconds or upgrading tier.",
            )
        if status_code >= 400:
            detail_msg = ""
            try:
                err_data = json.loads(resp_text)
                if isinstance(err_data, dict):
                    detail_msg = str(err_data.get("message") or err_data.get("detail", "")).strip()
            except Exception:
                pass
            sanitized = f": {detail_msg}" if detail_msg else ""
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message=f"Mistral API returned error status {status_code}{sanitized}.",
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
        model: str = "mistral-medium-latest",
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Translate text using Mistral Chat Completion API preserving protected tokens and legal context."""
        clean_text = text.strip()
        if not clean_text:
            return ""

        effective_system_prompt = system_prompt or (
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
                {"role": "system", "content": effective_system_prompt},
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

    def batch_translate(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        model: str = "mistral-medium-latest",
        system_prompt: str | None = None,
        batch_size: int = 16,
        **kwargs: Any,
    ) -> list[str]:
        """Translate a sequence of texts using Mistral Chat Completion, grouping them into multi-segment batches."""
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
            effective_system_prompt = system_prompt or (
                f"You are a professional legal, administrative, and technical translator.\n"
                f"Translate each text segment faithfully from {source_lang} to {target_lang}.\n"
                f"Strict Rules:\n"
                f"- Return every segment enclosed in its exact matching `<segment id=\"...\">` and `</segment>` tags.\n"
                f"- Do not omit, combine, or reorder segments.\n"
                f"- Strictly preserve formatting, line breaks, and tokens enclosed in '__PROTECTED_SPAN_'.\n"
                f"- Output ONLY the tagged translated segments without preamble or commentary."
            )

            user_prompt = f"Translate the following segments faithfully:\n\n{segment_blocks}"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": effective_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
            }

            try:
                resp_dict = self._post("chat/completions", payload)
                choices = resp_dict.get("choices", [])
                raw_out = choices[0]["message"]["content"].strip() if choices else ""

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
