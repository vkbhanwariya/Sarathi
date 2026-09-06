"""Unit tests for Shakti TranslationProvider (R05, R06)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sarathi.sankalpa import PluginServices, ReadinessStatus
from sarathi.shakti.translation.capability import TranslationCapability
from sarathi.shakti.translation.provider import TranslationProvider


def test_provider_data_root_subpath_resolution(tmp_path: Path) -> None:
    """R05 Fix: TranslationProvider resolves translation subpath when passed root data dir."""
    prov = TranslationProvider()

    # Case 1: services.data_root is root data dir
    services = PluginServices(data_root=tmp_path)
    caps = prov.create_capabilities(services)
    trans_cap = caps["translation"]
    assert isinstance(trans_cap, TranslationCapability)
    assert trans_cap._engine._data_root == (tmp_path / "translation").resolve()

    # Case 2: services.data_root is already translation dir
    direct_trans_dir = tmp_path / "custom" / "translation"
    services_direct = PluginServices(data_root=direct_trans_dir)
    caps_direct = prov.create_capabilities(services_direct)
    trans_cap_direct = caps_direct["translation"]
    assert isinstance(trans_cap_direct, TranslationCapability)
    assert trans_cap_direct._engine._data_root == direct_trans_dir.resolve()


def test_provider_readiness_missing_sentencepiece(tmp_path: Path) -> None:
    """R06 Fix: readiness reports unavailable if sentencepiece is missing."""
    prov = TranslationProvider()
    services = PluginServices(data_root=tmp_path)

    # Mock ctranslate2 available but sentencepiece unavailable
    def mock_find_spec(name: str):
        if name == "ctranslate2":
            return object()
        if name == "sentencepiece":
            return None
        return None

    with patch("importlib.util.find_spec", side_effect=mock_find_spec):
        readiness_map = prov.readiness(services)
        res = readiness_map["translation"]
        assert not res.ready
        assert res.status == ReadinessStatus.DEPENDENCY_UNAVAILABLE
        assert "sentencepiece" in res.reason


def test_provider_readiness_missing_manifest(tmp_path: Path) -> None:
    """R06 Fix: readiness reports unavailable if manifest.json is missing."""
    prov = TranslationProvider()
    trans_dir = tmp_path / "translation"
    trans_dir.mkdir(parents=True, exist_ok=True)

    # Set up models directory with complete models, but NO manifest.json
    for model_name in ("hi-en", "en-hi"):
        m_dir = trans_dir / "models" / model_name
        m_dir.mkdir(parents=True, exist_ok=True)
        (m_dir / "model.bin").write_bytes(b"dummy")
        (m_dir / "spm.model").write_bytes(b"dummy")
        (m_dir / "shared_vocabulary.json").write_bytes(b"{}")

    services = PluginServices(data_root=tmp_path)

    def mock_find_spec(name: str):
        return object()

    with patch("importlib.util.find_spec", side_effect=mock_find_spec):
        readiness_map = prov.readiness(services)
        res = readiness_map["translation"]
        assert not res.ready
        assert res.status == ReadinessStatus.DEPENDENCY_UNAVAILABLE
        assert "manifest.json" in res.reason


def test_provider_readiness_ready_when_all_assets_and_packages_present(tmp_path: Path) -> None:
    """R06 Fix: readiness reports READY when ctranslate2, sentencepiece, manifest, and models are present."""
    prov = TranslationProvider()
    trans_dir = tmp_path / "translation"
    trans_dir.mkdir(parents=True, exist_ok=True)
    (trans_dir / "manifest.json").write_text('{"version": "1.0"}', encoding="utf-8")

    for model_name in ("hi-en", "en-hi"):
        m_dir = trans_dir / "models" / model_name
        m_dir.mkdir(parents=True, exist_ok=True)
        (m_dir / "model.bin").write_bytes(b"dummy")
        (m_dir / "spm.model").write_bytes(b"dummy")
        (m_dir / "shared_vocabulary.json").write_bytes(b"{}")

    services = PluginServices(data_root=tmp_path)

    def mock_find_spec(name: str):
        return object()

    with patch("importlib.util.find_spec", side_effect=mock_find_spec):
        readiness_map = prov.readiness(services)
        res = readiness_map["translation"]
        assert res.ready
        assert res.status == ReadinessStatus.READY
        assert "IndicTrans2 CTranslate2" in res.reason
