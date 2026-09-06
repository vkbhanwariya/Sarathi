"""Tests for Shakti plugin readiness probes and Agni readiness auditing."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from sarathi.agni import Agni
from sarathi.sankalpa import CapabilityReadiness, PluginServices, ReadinessStatus
from sarathi.shakti.bank_statements.provider import BankStatementsProvider
from sarathi.shakti.darshana.provider import DarshanaProvider
from sarathi.shakti.font_conversion.provider import FontConversionProvider
from sarathi.shakti.native_extraction.provider import NativeExtractionProvider
from sarathi.shakti.ocr.provider import OCRProvider
from sarathi.shakti.translation.provider import TranslationProvider
from sarathi.sutra import get_canonical_data_root


def test_darshana_and_native_readiness_probes() -> None:
    """Verify built-in zero-dependency capabilities report ready unconditionally."""
    darshana_p = DarshanaProvider()
    darshana_res = darshana_p.readiness()
    assert "identify" in darshana_res
    assert darshana_res["identify"].ready is True
    assert darshana_res["identify"].status == ReadinessStatus.READY

    native_p = NativeExtractionProvider()
    native_res = native_p.readiness()
    assert "read_native" in native_res
    assert native_res["read_native"].ready is True
    assert native_res["read_native"].status == ReadinessStatus.READY


def test_ocr_provider_readiness_probe() -> None:
    """Verify OCRProvider delegates to check_ocr_readiness."""
    ocr_p = OCRProvider()
    services = PluginServices(data_root=get_canonical_data_root())
    res = ocr_p.readiness(services)
    assert "ocr" in res
    readiness = res["ocr"]
    assert isinstance(readiness, CapabilityReadiness)
    # Status reflects environment facts truthfully
    assert readiness.status in (ReadinessStatus.READY, ReadinessStatus.DEPENDENCY_UNAVAILABLE)


def test_bank_statements_provider_readiness_probe(tmp_path: Path) -> None:
    """Verify BankStatementsProvider audits bank profiles directory."""
    bank_p = BankStatementsProvider()

    # When no banks dir exists in tmp_path
    empty_services = PluginServices(data_root=tmp_path)
    res_empty = bank_p.readiness(empty_services)
    assert "bank_statements" in res_empty
    assert res_empty["bank_statements"].ready is False
    assert "No bank profiles loaded" in res_empty["bank_statements"].reason

    # When canonical banks dir with SBI is present
    canon_services = PluginServices(data_root=get_canonical_data_root())
    res_canon = bank_p.readiness(canon_services)
    assert "bank_statements" in res_canon
    assert res_canon["bank_statements"].ready is True
    assert "SBI" in res_canon["bank_statements"].reason


def test_font_conversion_provider_readiness_probe(tmp_path: Path) -> None:
    """Verify FontConversionProvider audits font JSON packs directory."""
    font_p = FontConversionProvider()

    # Empty data dir
    empty_services = PluginServices(data_root=tmp_path)
    res_empty = font_p.readiness(empty_services)
    assert "font_conversion" in res_empty
    assert res_empty["font_conversion"].ready is False
    assert "Missing font mapping packs" in res_empty["font_conversion"].reason

    # Canonical data dir
    canon_services = PluginServices(data_root=get_canonical_data_root())
    res_canon = font_p.readiness(canon_services)
    assert "font_conversion" in res_canon
    assert res_canon["font_conversion"].ready is True
    assert "mapping packs" in res_canon["font_conversion"].reason


def test_translation_provider_readiness_probe(tmp_path: Path) -> None:
    """Verify TranslationProvider checks ctranslate2 and models."""
    trans_p = TranslationProvider()

    # Empty data dir
    empty_services = PluginServices(data_root=tmp_path)
    res_empty = trans_p.readiness(empty_services)
    assert "translation" in res_empty
    assert res_empty["translation"].ready is False
    assert "Unavailable" in res_empty["translation"].reason

    # Directory exists but model weights/vocabularies are missing
    data_dir = tmp_path / "translation" / "models"
    (data_dir / "hi-en").mkdir(parents=True)
    (data_dir / "en-hi").mkdir(parents=True)
    services = PluginServices(data_root=tmp_path)
    res_incomplete = trans_p.readiness(services)
    assert res_incomplete["translation"].ready is False
    assert "model assets" in res_incomplete["translation"].reason

    # All required assets present for both directions
    (tmp_path / "translation" / "manifest.json").write_text('{"version": "1.0"}', encoding="utf-8")
    for lang in ("hi-en", "en-hi"):
        (data_dir / lang / "model.bin").write_bytes(b"dummy")
        (data_dir / lang / "spm.model").write_bytes(b"dummy")
        (data_dir / lang / "shared_vocabulary.json").write_text("{}", encoding="utf-8")

    res_ready = trans_p.readiness(services)
    # Ready if ctranslate2 and sentencepiece are installed
    import importlib.util

    if (
        importlib.util.find_spec("ctranslate2") is not None
        and importlib.util.find_spec("sentencepiece") is not None
    ):
        assert res_ready["translation"].ready is True
    else:
        assert res_ready["translation"].ready is False
        assert (
            "ctranslate2" in res_ready["translation"].reason
            or "sentencepiece" in res_ready["translation"].reason
        )


def test_agni_audit_readiness_memoization(tmp_path: Path) -> None:
    """Verify Agni.audit_readiness memoizes results and invalidates on force_refresh."""
    agni = Agni(runtime_root=tmp_path / "rt", output_root=tmp_path / "out")
    try:
        # First call audits and caches
        res1 = agni.audit_readiness()
        assert isinstance(res1, MappingProxyType)
        assert "ocr" in res1
        assert "read_native" in res1
        assert "bank_statements" in res1

        # Second call returns cached mapping
        res2 = agni.audit_readiness()
        assert res1 == res2

        # force_refresh creates a new audit
        res3 = agni.audit_readiness(force_refresh=True)
        assert res3 == res1
    finally:
        agni.close()


def test_agni_audit_readiness_reports_disabled_status(tmp_path: Path) -> None:
    """Verify Agni.audit_readiness reports ReadinessStatus.DISABLED for operator-disabled plugins."""
    from sarathi.sutra import Settings

    settings = Settings({"plugins": {"disabled": ["shakti.translation"]}})
    agni = Agni(settings=settings, runtime_root=tmp_path / "rt", output_root=tmp_path / "out")
    try:
        readiness = agni.audit_readiness()
        assert "translation" in readiness
        trans_r = readiness["translation"]
        assert trans_r.ready is False
        assert trans_r.status == ReadinessStatus.DISABLED
        assert "Disabled by operator configuration" in trans_r.reason

        # Active plugins still report their normal readiness
        assert "read_native" in readiness
        assert readiness["read_native"].ready is True
        assert readiness["read_native"].status == ReadinessStatus.READY
    finally:
        agni.close()
