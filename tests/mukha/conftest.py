"""Pytest fixtures for Mukha test suite."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from sarathi.agni import Agni
from sarathi.mukha.web import MukhaWebServer


@pytest.fixture
def test_agni(tmp_path: Path) -> Agni:
    """Provide initialized Agni instance with isolated roots."""
    input_dir = tmp_path / "Input"
    input_dir.mkdir()
    output_dir = tmp_path / "Output"
    output_dir.mkdir()
    runtime_dir = tmp_path / "Runtime"
    runtime_dir.mkdir()

    agni = Agni(
        runtime_root=runtime_dir,
        output_root=output_dir,
    )
    with agni:
        yield agni


@pytest.fixture(scope="module")
def module_agni(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Provide initialized Agni instance with isolated roots for module-scoped server."""
    tmp_path = tmp_path_factory.mktemp("mukha_module")
    input_dir = tmp_path / "Input"
    input_dir.mkdir(exist_ok=True)
    output_dir = tmp_path / "Output"
    output_dir.mkdir(exist_ok=True)
    runtime_dir = tmp_path / "Runtime"
    runtime_dir.mkdir(exist_ok=True)

    agni = Agni(
        runtime_root=runtime_dir,
        output_root=output_dir,
    )
    with agni:
        yield agni


@pytest.fixture(scope="module")
def module_web_server(module_agni: Agni) -> Any:
    """Provide running MukhaWebServer on a free loopback port shared within module."""
    server = MukhaWebServer(agni=module_agni, host="127.0.0.1", port=0)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def web_server(module_web_server: MukhaWebServer) -> MukhaWebServer:
    """Provide running MukhaWebServer, resetting runner state between tests."""
    module_web_server.reset()
    yield module_web_server
    module_web_server.reset()


class CaseInsensitiveHeaders(dict):
    """Case-insensitive dictionary for HTTP headers."""

    def __init__(self, data: dict[str, str] | None = None) -> None:
        super().__init__()
        if data:
            for k, v in data.items():
                self[k] = v

    def __getitem__(self, key: str) -> str:
        return super().__getitem__(key.lower())

    def __setitem__(self, key: str, value: str) -> None:
        super().__setitem__(key.lower(), value)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            return super().__contains__(key.lower())
        return super().__contains__(key)

    def get(self, key: str, default: Any = None) -> Any:
        if isinstance(key, str):
            return super().get(key.lower(), default)
        return super().get(key, default)


def http_get(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> tuple[int, bytes, CaseInsensitiveHeaders]:
    """Perform HTTP GET request returning (status, body_bytes, headers_dict)."""
    req_headers = {"Connection": "close"}
    if headers:
        req_headers.update(headers)
    for attempt in range(5):
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                headers_dict = CaseInsensitiveHeaders(dict(resp.headers.items()))
                return resp.status, resp.read(), headers_dict
        except urllib.error.HTTPError as err:
            return err.code, err.read(), CaseInsensitiveHeaders(dict(err.headers.items()))
        except (ConnectionResetError, ConnectionAbortedError, urllib.error.URLError, OSError) as exc:
            if attempt < 4:
                time.sleep(0.02 * (attempt + 1))
                continue
            raise AssertionError(f"HTTP GET {url} failed due to transport failure: {exc}") from exc
    raise AssertionError(f"HTTP GET {url} failed after 5 retries")


def http_get_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    """Perform HTTP GET returning parsed JSON (status, body_dict)."""
    status, data, _ = http_get(url, headers=headers, timeout=timeout)
    try:
        return status, json.loads(data.decode("utf-8"))
    except Exception:
        return status, {"error": "Failed to decode JSON", "raw": data.decode("utf-8", errors="replace")}


def http_post_json(
    url: str,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    raw_payload: bytes | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    """Perform HTTP POST request with JSON payload returning (status, json_dict)."""
    payload = raw_payload if raw_payload is not None else json.dumps(data or {}).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "Connection": "close"}
    if headers:
        req_headers.update(headers)

    for attempt in range(5):
        req = urllib.request.Request(url, data=payload, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, json.loads(body)
        except urllib.error.HTTPError as err:
            try:
                body = err.read().decode("utf-8")
                return err.code, json.loads(body)
            except Exception:
                return err.code, {"error": str(err.reason)}
        except (ConnectionResetError, ConnectionAbortedError, urllib.error.URLError, OSError) as exc:
            if attempt < 4:
                time.sleep(0.02 * (attempt + 1))
                continue
            raise AssertionError(f"HTTP POST {url} failed due to transport failure: {exc}") from exc
        except Exception as exc:
            raise AssertionError(f"HTTP POST {url} failed with unexpected exception: {exc}") from exc
    raise AssertionError(f"HTTP POST {url} failed after 5 retries")


def wait_for_idle(web_server: MukhaWebServer, max_seconds: float = 5.0) -> None:
    """Wait for web_server to finish background run processing or raise TimeoutError."""
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        if not web_server.is_busy():
            return
        time.sleep(0.01)
    raise TimeoutError(f"Server did not become idle within {max_seconds} seconds")


# Common backward-compatible aliases for Mukha test files
_http_get = http_get
_http_get_json = http_get_json
_http_post = http_post_json
_wait_for_idle = wait_for_idle
