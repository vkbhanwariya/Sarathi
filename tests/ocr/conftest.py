"""Platform-specific OCR test collection rules."""

from __future__ import annotations

import os

import pytest


_WINDOWS_TESSERACT_TESTS = {
    "test_tesseract_adapter_real_subprocess_execution_with_tsv_parsing",
    "test_tesseract_adapter_tsv_invalid_confidence_adversarial",
    "test_tesseract_discovery_finds_installed_executable",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip tests whose assertions or executable shims are explicitly Windows-only."""
    if os.name == "nt":
        return

    marker = pytest.mark.skip(reason="Windows-specific Tesseract .bat/.exe integration test")
    for item in items:
        if item.name in _WINDOWS_TESSERACT_TESTS:
            item.add_marker(marker)
