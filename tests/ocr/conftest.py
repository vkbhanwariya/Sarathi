"""OCR test configuration and fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_ocr_checkpoints(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure OCR tests run in isolated checkpoint directories and never pollute production cache."""
    cache_dir = tmp_path_factory.mktemp("ocr_test_checkpoints")
    monkeypatch.setattr("sarathi.shakti.ocr.engine.checkpoint.DEFAULT_CHECKPOINT_DIR", cache_dir)
