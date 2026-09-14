"""Test confirmed artifact streaming headers and containment validation.

Validates:
1. Confirmed artifacts are streamed through the public server lookup contract.
2. Download responses return correct Content-Type, Content-Length, and Content-Disposition.
3. Access to files outside output_root or runtime_root is strictly denied with 403 Forbidden.
4. Non-existent or unregistered artifacts return 404 Not Found.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sarathi.mukha.web.server import MukhaWebServer
from sarathi.sankalpa import ArtifactRef


def _http_get(url: str) -> tuple[int, dict[str, str], bytes]:
    """Helper to perform HTTP GET returning status, headers dict, and raw body."""
    req = urllib.request.Request(url, headers={"Host": "127.0.0.1"})
    try:
        with urllib.request.urlopen(req) as resp:
            headers = {key.lower(): value for key, value in resp.headers.items()}
            return resp.status, headers, resp.read()
    except urllib.error.HTTPError as err:
        headers = {key.lower(): value for key, value in err.headers.items()}
        return err.code, headers, err.read()


@pytest.fixture
def artifact_server(tmp_path: Path):
    """Provide a started MukhaWebServer with isolated output and runtime roots."""
    output_root = tmp_path / "output"
    runtime_root = tmp_path / "runtime"
    output_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)

    mock_agni = MagicMock()
    mock_agni.output_root = output_root
    mock_agni.runtime_root = runtime_root
    mock_agni.kavacha = None
    mock_agni.kosh.capabilities.return_value = ()
    mock_agni.darpana = None
    mock_agni.smriti = None

    server = MukhaWebServer(mock_agni, host="127.0.0.1", port=0)
    server.start()
    try:
        yield server, output_root, runtime_root
    finally:
        server.stop()


def test_confirmed_artifact_streamed(artifact_server: tuple[MukhaWebServer, Path, Path]) -> None:
    """A confirmed artifact returned by the server lookup must be streamable with strict headers."""
    server, out_root, _ = artifact_server

    run_id = "run_art_001"
    art_file = out_root / "document_extracted.pdf"
    art_content = b"%PDF-1.4\n1 0 obj\n<< /Title (Test) >>\nendobj\n%%EOF\n"
    art_file.write_bytes(art_content)

    art_ref = ArtifactRef(
        artifact_id="art_pdf_01",
        role="final_document",
        media_type="application/pdf",
        path=art_file,
        size_bytes=len(art_content),
    )

    with patch.object(server, "get_confirmed_artifact", return_value=art_ref):
        status, headers, body = _http_get(
            f"http://127.0.0.1:{server.resolved_port}/api/runs/{run_id}/artifacts/{art_ref.artifact_id}"
        )

    assert status == 200
    assert headers["content-type"] == "application/pdf"
    assert headers["content-length"] == str(len(art_content))
    assert 'attachment; filename="document_extracted.pdf"' in headers["content-disposition"]
    assert body == art_content


def test_artifact_containment_forbidden(artifact_server: tuple[MukhaWebServer, Path, Path], tmp_path: Path) -> None:
    """Artifact pointing outside authorized roots must return 403 Forbidden."""
    server, _, _ = artifact_server

    outside_dir = tmp_path / "outside_forbidden"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "secret_passwords.txt"
    outside_content = b"super_secret_data"
    outside_file.write_bytes(outside_content)

    run_id = "run_forbidden_01"
    art_ref = ArtifactRef(
        artifact_id="art_evil_01",
        role="leak",
        media_type="text/plain",
        path=outside_file,
        size_bytes=len(outside_content),
    )

    with patch.object(server, "get_confirmed_artifact", return_value=art_ref):
        status, _, _ = _http_get(
            f"http://127.0.0.1:{server.resolved_port}/api/runs/{run_id}/artifacts/{art_ref.artifact_id}"
        )

    assert status == 403


def test_missing_or_unregistered_artifact_returns_404(artifact_server: tuple[MukhaWebServer, Path, Path]) -> None:
    """Non-existent artifact ID must return 404 Not Found."""
    server, _, _ = artifact_server

    status, _, _ = _http_get(
        f"http://127.0.0.1:{server.resolved_port}/api/runs/run_valid_01/artifacts/art_non_existent"
    )

    assert status == 404
