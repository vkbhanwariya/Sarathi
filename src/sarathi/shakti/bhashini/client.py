"""Direct REST client for Bhashini (NLTM / ULCA) with sanitized error handling."""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from sarathi.dosh import DoshError, FailureCode

_DEFAULT_INFERENCE_URL = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
_DEFAULT_TIMEOUT_SECONDS = 60.0


class BhashiniClient:
    """Direct REST transport for Bhashini Dhruva Inference Pipeline."""

    def __init__(
        self,
        user_id: str | None = None,
        api_key: str | None = None,
        inference_key: str | None = None,
        pipeline_url: str = _DEFAULT_INFERENCE_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._user_id = user_id or os.environ.get("BHASHINI_USER_ID")
        self._api_key = api_key or os.environ.get("BHASHINI_API_KEY")
        self._inference_key = inference_key or os.environ.get("BHASHINI_INFERENCE_KEY")
        self._pipeline_url = pipeline_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def is_configured(self) -> bool:
        """Return True if required Bhashini credentials are present."""
        return bool(
            self._user_id
            and self._user_id.strip()
            and self._api_key
            and self._api_key.strip()
            and self._inference_key
            and self._inference_key.strip()
        )

    def _get_credentials(self) -> tuple[str, str, str]:
        """Resolve and validate Bhashini credentials, raising DoshError if missing."""
        if not self._user_id or not self._user_id.strip():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Bhashini User ID is not configured. Set BHASHINI_USER_ID environment variable.",
            )
        if not self._api_key or not self._api_key.strip():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Bhashini API key is not configured. Set BHASHINI_API_KEY environment variable.",
            )
        if not self._inference_key or not self._inference_key.strip():
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Bhashini Inference key is not configured. Set BHASHINI_INFERENCE_KEY environment variable.",
            )
        return self._user_id.strip(), self._api_key.strip(), self._inference_key.strip()

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Perform sanitized HTTP POST to Bhashini pipeline endpoint."""
        user_id, api_key, inf_key = self._get_credentials()
        headers = {
            "userID": user_id,
            "ulcaApiKey": api_key,
            "Authorization": inf_key,
            "Content-Type": "application/json",
            "User-Agent": "Sarathi/2.0",
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        status_code = 0
        resp_text = ""
        try:
            import httpx

            with httpx.Client(timeout=self._timeout_seconds) as client:
                resp = client.post(self._pipeline_url, headers=headers, content=body_bytes)
                status_code = resp.status_code
                resp_text = resp.text
        except ImportError as imp_err:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="HTTP transport dependency (httpx) is not installed.",
            ) from imp_err
        except httpx.TimeoutException as exc:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Network timeout while connecting to Bhashini API.",
            ) from exc
        except Exception as exc:
            sanitized = str(exc).replace(api_key, "[REDACTED]").replace(inf_key, "[REDACTED]")
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message=f"Bhashini API request failed: {sanitized}",
            ) from exc

        if status_code in (401, 403):
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="Bhashini authentication failed. Verify BHASHINI_USER_ID, BHASHINI_API_KEY, and BHASHINI_INFERENCE_KEY.",
            )
        if status_code == 429:
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message="Bhashini API rate limit exceeded.",
            )
        if status_code >= 400:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message=f"Bhashini API returned error status {status_code}.",
            )

        try:
            return json.loads(resp_text)
        except json.JSONDecodeError as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to parse JSON response from Bhashini API.",
            ) from err

    def process_ocr(
        self,
        content_bytes: bytes,
        source_lang: str = "hi",
    ) -> dict[str, Any]:
        """Perform OCR via Bhashini Chitrakshar pipeline."""
        if not content_bytes:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Empty content passed to Bhashini OCR.",
            )

        b64_img = base64.b64encode(content_bytes).decode("ascii")
        payload = {
            "pipelineTasks": [
                {
                    "taskType": "ocr",
                    "config": {
                        "language": {
                            "sourceLanguage": source_lang,
                        }
                    },
                }
            ],
            "inputData": {
                "image": [
                    {
                        "imageContent": b64_img,
                    }
                ]
            },
        }
        return self._post(payload)

    def translate_text(
        self,
        text: str,
        source_lang: str = "hi",
        target_lang: str = "en",
    ) -> str:
        """Perform translation via Bhashini IndicTrans2 NMT pipeline."""
        if not text.strip():
            return ""

        payload = {
            "pipelineTasks": [
                {
                    "taskType": "translation",
                    "config": {
                        "language": {
                            "sourceLanguage": source_lang,
                            "targetLanguage": target_lang,
                        }
                    },
                }
            ],
            "inputData": {
                "input": [
                    {
                        "source": text,
                    }
                ]
            },
        }

        data = self._post(payload)
        pipeline_response = data.get("pipelineResponse", [])
        if pipeline_response:
            output = pipeline_response[0].get("output", [])
            if output:
                return str(output[0].get("target", "")).strip()
        return text
