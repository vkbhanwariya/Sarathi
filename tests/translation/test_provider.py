"""Unit tests for Shakti TranslationProvider (R05, R06)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

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
        m_dir = trans_dir / "models" / "indictrans2" / model_name
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


def test_translation_engine_error_does_not_leak_paths(tmp_path: Path) -> None:
    """Verify missing model assets error message does not leak local filesystem paths."""
    import pytest

    from sarathi.dosh import DoshError, FailureCode
    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
    from sarathi.shakti.translation.models import TranslationDirection

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text('{"models": {"hi-en": {"path": "hi-en"}}}', encoding="utf-8")
    models_dir = tmp_path / "models" / "indictrans2"
    models_dir.mkdir(parents=True)
    model_dir = models_dir / "hi-en"
    model_dir.mkdir()
    (model_dir / "model.bin").write_bytes(b"dummy")
    # spm.model is intentionally missing

    engine = CTranslate2TranslationEngine(data_root=tmp_path)
    try:
        backend = engine._ensure_backend()
    except DoshError as exc:
        if exc.code is FailureCode.DEPENDENCY_UNAVAILABLE:
            pytest.skip("Translation dependencies (ctranslate2, sentencepiece) are not installed.")
        raise
    with pytest.raises(DoshError) as exc_info:
        backend.translate_sentences(["नमस्ते"], TranslationDirection.HI_TO_EN)
    err_msg = exc_info.value.message
    assert str(tmp_path) not in err_msg
    assert "Model assets for IndicTrans2 translation direction 'hi-en' are missing or incomplete." == err_msg


def test_translation_anubhava_malformed_raises_invalid_configuration(tmp_path: Path) -> None:
    """Malformed anubhava.toml raises INVALID_CONFIGURATION."""
    from sarathi.dosh import DoshError, FailureCode
    from sarathi.shakti.translation.engine import _load_translation_anubhava

    bad_toml = tmp_path / "anubhava.toml"
    bad_toml.write_text("invalid [ = toml syntax", encoding="utf-8")

    with pytest.raises(DoshError) as exc_info:
        _load_translation_anubhava(tmp_path)
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION


def test_provider_readiness_indictrans2_subfolder_with_dual_spm(tmp_path: Path) -> None:
    """Readiness reports READY when indictrans2 models are stored in models/indictrans2 with dual SPM."""
    prov = TranslationProvider()
    trans_dir = tmp_path / "translation"
    trans_dir.mkdir(parents=True, exist_ok=True)
    (trans_dir / "manifest.json").write_text('{"version": "1.0"}', encoding="utf-8")

    for model_name in ("hi-en", "en-hi"):
        m_dir = trans_dir / "models" / "indictrans2" / model_name
        m_dir.mkdir(parents=True, exist_ok=True)
        (m_dir / "model.bin").write_bytes(b"dummy")
        (m_dir / "model.SRC").write_bytes(b"dummy")
        (m_dir / "model.TGT").write_bytes(b"dummy")
        (m_dir / "source_vocabulary.json").write_bytes(b"{}")
        (m_dir / "target_vocabulary.json").write_bytes(b"{}")

    services = PluginServices(data_root=tmp_path)

    with patch("importlib.util.find_spec", side_effect=lambda name: object()):
        readiness_map = prov.readiness(services)
        res = readiness_map["translation"]
        assert res.ready
        assert res.status == ReadinessStatus.READY
        assert "IndicTrans2 CTranslate2" in res.reason


def test_native_backend_exports_and_translate_delegation() -> None:
    """Verify CTranslate2NativeBackend, BackendTranslationResult, and engine.translate delegation."""
    from unittest.mock import MagicMock

    from sarathi.shakti.translation.engine import (
        BackendTranslationResult,
        CTranslate2NativeBackend,
        CTranslate2TranslationEngine,
    )
    from sarathi.shakti.translation.models import TranslationDirection

    # Verify typed dataclass
    result = BackendTranslationResult(
        sentences=["Hello world"],
        device="cpu",
        truncation_flags=(False,),
    )
    assert result.sentences == ["Hello world"]
    assert result.device == "cpu"
    assert result.truncation_flags == (False,)

    # Verify CTranslate2NativeBackend class is available at module scope
    assert CTranslate2NativeBackend is not None

    # Verify translate() delegates directly to translate_batch()
    engine = CTranslate2TranslationEngine()
    mock_batch = MagicMock(return_value=[MagicMock(translated_text="Delegated")])
    engine.translate_batch = mock_batch  # type: ignore[method-assign]

    res = engine.translate("परीक्षण", direction=TranslationDirection.HI_TO_EN)
    assert res.translated_text == "Delegated"
    mock_batch.assert_called_once_with(
        texts=["परीक्षण"],
        direction=TranslationDirection.HI_TO_EN,
        execution_binding=None,
        engine="krutrim",
        glossary_terms=None,
        custom_terms=(),
    )


def test_ctranslate2_native_backend_caches_cuda_probe(tmp_path: Path) -> None:
    """Verify CTranslate2NativeBackend caches the CUDA device count probe."""
    from sarathi.shakti.translation.engine import CTranslate2NativeBackend

    backend = CTranslate2NativeBackend(root=tmp_path, manifest={})
    assert backend._cuda_device_count is None

    with patch("ctranslate2.get_cuda_device_count", return_value=0) as mock_probe:
        count1 = backend._get_cuda_device_count()
        count2 = backend._get_cuda_device_count()
        assert count1 == 0
        assert count2 == 0
        assert backend._cuda_device_count == 0
        # Probe must only have been invoked once and cached
        assert mock_probe.call_count <= 1


def test_strict_engine_directory_isolation(tmp_path: Path) -> None:
    """Verify indictrans2 never falls back to opus_mt directory or models root."""
    from sarathi.dosh import DoshError, FailureCode
    from sarathi.shakti.translation.engine import CTranslate2NativeBackend
    from sarathi.shakti.translation.models import TranslationDirection

    # Set up OPUS-MT model only
    opus_dir = tmp_path / "models" / "opus_mt" / "hi-en"
    opus_dir.mkdir(parents=True)
    (opus_dir / "model.bin").write_bytes(b"opus-model-binary")
    (opus_dir / "spm.model").write_bytes(b"opus-spm-model")
    (opus_dir / "shared_vocabulary.json").write_bytes(b"{}")

    # Set up root models dir (legacy)
    root_dir = tmp_path / "models" / "hi-en"
    root_dir.mkdir(parents=True)
    (root_dir / "model.bin").write_bytes(b"legacy-model-binary")
    (root_dir / "spm.model").write_bytes(b"legacy-spm-model")

    backend = CTranslate2NativeBackend(root=tmp_path, manifest={"models": {"hi-en": {}}})

    # Requesting indictrans2 MUST fail closed despite opus_mt and root models existing
    with pytest.raises(DoshError) as exc_info:
        backend.translate_sentences(["परीक्षण"], TranslationDirection.HI_TO_EN, engine="indictrans2")
    assert exc_info.value.code == FailureCode.DEPENDENCY_UNAVAILABLE
    assert "Model assets for IndicTrans2 translation direction 'hi-en' are missing or incomplete." in exc_info.value.message

    # Requesting unsupported engine MUST fail with INVALID_CONFIGURATION
    with pytest.raises(DoshError) as exc_info:
        backend.translate_sentences(["परीक्षण"], TranslationDirection.HI_TO_EN, engine="unknown_nmt")
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION


def test_translation_model_sha256_verification(tmp_path: Path) -> None:
    """Verify translation model SHA-256 verification detects corrupted weights."""
    import hashlib

    from sarathi.dosh import DoshError, FailureCode
    from sarathi.shakti.translation.engine import CTranslate2NativeBackend

    indic_dir = tmp_path / "models" / "indictrans2" / "hi-en"
    indic_dir.mkdir(parents=True)
    bin_data = b"genuine-ct2-model-weights"
    (indic_dir / "model.bin").write_bytes(bin_data)
    (indic_dir / "spm.model").write_bytes(b"genuine-spm-model")
    (indic_dir / "model.SRC").write_bytes(b"genuine-spm-model")

    correct_sha = hashlib.sha256(bin_data).hexdigest()

    # Case 1: Manifest with correct SHA256 passes verification
    manifest_valid = {
        "models": {
            "hi-en": {
                "files": {
                    "model.bin": {"sha256": correct_sha}
                }
            }
        }
    }
    backend_valid = CTranslate2NativeBackend(root=tmp_path, manifest=manifest_valid)
    # Integrity check directly
    backend_valid._verify_model_integrity(indic_dir, manifest_valid["models"]["hi-en"]["files"])

    # Case 2: Tampered model weights fail closed with DEPENDENCY_UNAVAILABLE
    manifest_corrupt = {
        "models": {
            "hi-en": {
                "files": {
                    "model.bin": {"sha256": "0000000000000000000000000000000000000000000000000000000000000000"}
                }
            }
        }
    }
    backend_corrupt = CTranslate2NativeBackend(root=tmp_path, manifest=manifest_corrupt)
    with pytest.raises(DoshError) as exc_info:
        backend_corrupt._verify_model_integrity(indic_dir, manifest_corrupt["models"]["hi-en"]["files"])
    assert exc_info.value.code == FailureCode.DEPENDENCY_UNAVAILABLE
    assert "checksum mismatch" in exc_info.value.message


def test_provider_readiness_krutrim_models(tmp_path: Path) -> None:
    """Verify TranslationProvider recognizes Krutrim-Translate models and reports 4096 readiness."""
    prov = TranslationProvider()
    trans_dir = tmp_path / "translation"
    trans_dir.mkdir(parents=True, exist_ok=True)
    (trans_dir / "manifest.json").write_text('{"version": "1.1.0"}', encoding="utf-8")

    models_dir = trans_dir / "models"
    for direction in ("hi-en", "en-hi"):
        d = models_dir / "krutrim" / direction
        d.mkdir(parents=True, exist_ok=True)
        (d / "model.bin").write_bytes(b"dummy-bin")
        (d / "spm.model").write_bytes(b"dummy-spm")
        (d / "shared_vocabulary.json").write_text("{}", encoding="utf-8")

    services = PluginServices(data_root=tmp_path)
    with patch("importlib.util.find_spec", return_value=object()):
        res = prov.readiness(services)["translation"]
        assert res.ready
        assert res.status == ReadinessStatus.READY
        assert "Krutrim-Translate 4096" in res.reason
