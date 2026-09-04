"""Pytest fixtures for Mukha test suite."""

from __future__ import annotations

from pathlib import Path
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


@pytest.fixture
def web_server(test_agni: Agni) -> MukhaWebServer:
    """Provide running MukhaWebServer on a free loopback port."""
    server = MukhaWebServer(agni=test_agni, host="127.0.0.1", port=0)
    server.start()
    yield server
    server.stop()
