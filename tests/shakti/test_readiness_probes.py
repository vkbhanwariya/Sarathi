"""Tests for Shakti plugin readiness probes and Agni readiness auditing."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from sarathi.agni import Agni
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.sankalpa import CapabilityReadiness, PluginServices, ReadinessStatus
from sarathi.shakti.bank_statements.provider import BankStatementsProvider
from sarathi.shakti.darshana.provider import DarshanaProvider
from sarathi.shakti.font_conversion.provider import FontConversionProvider
from sarathi.shakti.native_extraction.provider import NativeExtractionProvider
from sarathi.shakti.ocr.provider import OCRProvider
from sarathi.shakti.providers import BUILTIN_PLUGIN_PROVIDERS
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


def test_mukha_presenter_audit_capability_status_delegation(tmp_path: Path) -> None:
    """Verify MukhaPresenter.audit_capability_status delegates to Agni and providers."""
    agni = Agni(runtime_root=tmp_path / "rt", output_root=tmp_path / "out")
    try:
        # 1. Via Agni
        status_via_agni = MukhaPresenter.audit_capability_status(agni=agni)
        assert "read_native" in status_via_agni
        assert status_via_agni["read_native"][0] is True
        assert "ocr" in status_via_agni
        assert isinstance(status_via_agni["ocr"][0], bool)
        assert isinstance(status_via_agni["ocr"][1], str)

        # 2. Via Providers directly (standalone fallback)
        status_via_providers = MukhaPresenter.audit_capability_status(
            providers=BUILTIN_PLUGIN_PROVIDERS,
            data_root=get_canonical_data_root(),
        )
        assert "read_native" in status_via_providers
        assert status_via_providers["read_native"][0] is True
        assert "bank_statements" in status_via_providers
        assert status_via_providers["bank_statements"][0] is True
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
