"""Tests for Agni runtime bootstrap consistency and 1-to-1 capability-declaration invariants."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pytest

from sarathi.agni import Agni
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    Capability,
    CapabilityDeclaration,
    CapabilityReadiness,
    ExecutionContext,
    ExecutionProfile,
    PluginInfo,
    PluginProvider,
    PluginServices,
    ReadinessStatus,
    Request,
    Result,
)


class SimpleTestCapability:
    """A minimal capability for testing bootstrap consistency."""

    def __init__(self, declaration: CapabilityDeclaration) -> None:
        self.declaration = declaration
        self.executed = False

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        self.executed = True
        return Result(data="test_ok")


@dataclass(frozen=True)
class SimpleTestProvider(PluginProvider):
    """Test provider with configurable plugin_info, declarations, and capabilities."""

    _plugin_info: PluginInfo
    _declarations: tuple[CapabilityDeclaration, ...]
    _capabilities: dict[str, Capability]

    @property
    def plugin_info(self) -> PluginInfo:
        return self._plugin_info

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return self._declarations

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        return dict(self._capabilities)

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        return {
            decl.capability_id: CapabilityReadiness(ready=True, status=ReadinessStatus.READY, reason="Ready")
            for decl in self._declarations
        }


def _make_decl(cap_id: str, plugin_id: str, version: str = "1.0.0") -> CapabilityDeclaration:
    return CapabilityDeclaration(
        capability_id=cap_id,
        plugin_id=plugin_id,
        version=version,
        supported_profiles=(ExecutionProfile.INSTANT,),
        display_name=f"Test {cap_id.title()}",
    )


def test_default_bootstrap_builtins_consistency(tmp_path: Path) -> None:
    """Verify that default Agni bootstrap wires 1-to-1 matching declarations and executables."""
    agni = Agni(runtime_root=tmp_path / "rt", output_root=tmp_path / "out")
    try:
        kosh_caps = set(c.capability_id for c in agni.kosh.capabilities())
        exec_caps = set(agni.capabilities.keys())

        # Exact 1-to-1 match
        assert kosh_caps == exec_caps
        assert "ocr" in exec_caps
        assert "bank_statements" in exec_caps
        assert "font_conversion" in exec_caps
        assert "translation" in exec_caps
        assert "read_native" in exec_caps
        assert "identify" in exec_caps

        # Exact declaration equivalence
        for cap_id, cap_obj in agni.capabilities.items():
            assert cap_obj.declaration == agni.kosh.get_capability(cap_id)
    finally:
        agni.close()


def test_registered_declaration_missing_executable_raises_validation_failed(tmp_path: Path) -> None:
    """Verify that a declaration registered in Kosh without an executable binding fails bootstrap."""
    decl1 = _make_decl("cap_one", "test.missing")
    decl2 = _make_decl("cap_two", "test.missing")
    p_info = PluginInfo(plugin_id="test.missing", name="Missing", version="1.0.0", capabilities=("cap_one", "cap_two"))

    # Provider declares two capabilities, but create_capabilities only returns one
    bad_provider = SimpleTestProvider(
        _plugin_info=p_info,
        _declarations=(decl1, decl2),
        _capabilities={"cap_one": SimpleTestCapability(decl1)},
    )

    with pytest.raises(DoshError) as exc_info:
        Agni(
            plugin_providers=[bad_provider],
            runtime_root=tmp_path / "rt",
            output_root=tmp_path / "out",
        )

    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "cap_two" in str(exc_info.value.message)
    assert "no matching executable binding" in str(exc_info.value.message)


def test_executable_binding_missing_declaration_raises_validation_failed(tmp_path: Path) -> None:
    """Verify that an executable capability without a declared plugin in Kosh fails bootstrap."""
    decl = _make_decl("orphan_cap", "unregistered.plugin")
    orphan_cap = SimpleTestCapability(decl)

    with pytest.raises(DoshError) as exc_info:
        Agni(
            capabilities={"orphan_cap": orphan_cap},
            runtime_root=tmp_path / "rt",
            output_root=tmp_path / "out",
        )

    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "unregistered.plugin" in str(exc_info.value.message)
    assert "owning plugin 'unregistered.plugin' is not registered in Kosh" in str(exc_info.value.message)


def test_executable_declaration_mismatch_raises_validation_failed(tmp_path: Path) -> None:
    """Verify that an executable whose declaration differs from Kosh fails bootstrap."""
    kosh_decl = _make_decl("mismatched_cap", "test.mismatch", version="1.0.0")
    exec_decl = _make_decl("mismatched_cap", "test.mismatch", version="2.0.0")

    p_info = PluginInfo(plugin_id="test.mismatch", name="Mismatch", version="1.0.0", capabilities=("mismatched_cap",))

    mismatched_provider = SimpleTestProvider(
        _plugin_info=p_info,
        _declarations=(kosh_decl,),
        _capabilities={"mismatched_cap": SimpleTestCapability(exec_decl)},
    )

    with pytest.raises(DoshError) as exc_info:
        Agni(
            plugin_providers=[mismatched_provider],
            runtime_root=tmp_path / "rt",
            output_root=tmp_path / "out",
        )

    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "mismatched_cap" in str(exc_info.value.message)
    assert "executable declaration does not match Kosh declaration" in str(exc_info.value.message)


def test_duplicate_plugin_id_across_providers_raises_validation_failed(tmp_path: Path) -> None:
    """Verify that duplicate plugin IDs across providers are rejected at bootstrap."""
    decl1 = _make_decl("cap_a", "duplicate.plugin")
    p_info = PluginInfo(plugin_id="duplicate.plugin", name="Dup", version="1.0.0", capabilities=("cap_a",))

    prov1 = SimpleTestProvider(_plugin_info=p_info, _declarations=(decl1,), _capabilities={"cap_a": SimpleTestCapability(decl1)})
    prov2 = SimpleTestProvider(_plugin_info=p_info, _declarations=(decl1,), _capabilities={"cap_a": SimpleTestCapability(decl1)})

    with pytest.raises(DoshError) as exc_info:
        Agni(
            plugin_providers=[prov1, prov2],
            runtime_root=tmp_path / "rt",
            output_root=tmp_path / "out",
        )

    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "duplicate.plugin" in str(exc_info.value.message)
    assert "Duplicate plugin ID" in str(exc_info.value.message)


def test_duplicate_capability_id_across_providers_raises_validation_failed(tmp_path: Path) -> None:
    """Verify that duplicate capability IDs declared across distinct providers are rejected."""
    decl1 = _make_decl("clashing_cap", "plugin.alpha")
    decl2 = _make_decl("clashing_cap", "plugin.beta")

    p1 = PluginInfo(plugin_id="plugin.alpha", name="Alpha", version="1.0.0", capabilities=("clashing_cap",))
    p2 = PluginInfo(plugin_id="plugin.beta", name="Beta", version="1.0.0", capabilities=("clashing_cap",))

    prov1 = SimpleTestProvider(_plugin_info=p1, _declarations=(decl1,), _capabilities={"clashing_cap": SimpleTestCapability(decl1)})
    prov2 = SimpleTestProvider(_plugin_info=p2, _declarations=(decl2,), _capabilities={"clashing_cap": SimpleTestCapability(decl2)})

    with pytest.raises(DoshError) as exc_info:
        Agni(
            plugin_providers=[prov1, prov2],
            runtime_root=tmp_path / "rt",
            output_root=tmp_path / "out",
        )

    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "clashing_cap" in str(exc_info.value.message)
    assert "Duplicate capability ID" in str(exc_info.value.message)


def test_extra_plugin_providers_additive_registration(tmp_path: Path) -> None:
    """Verify that extra_plugin_providers additively registers new plugins and capabilities alongside defaults."""
    custom_decl = _make_decl("custom_analyzer", "custom.analyzer")
    custom_pinfo = PluginInfo(
        plugin_id="custom.analyzer",
        name="Custom Analyzer",
        version="1.0.0",
        capabilities=("custom_analyzer",),
    )
    custom_provider = SimpleTestProvider(
        _plugin_info=custom_pinfo,
        _declarations=(custom_decl,),
        _capabilities={"custom_analyzer": SimpleTestCapability(custom_decl)},
    )

    agni = Agni(
        extra_plugin_providers=[custom_provider],
        runtime_root=tmp_path / "rt",
        output_root=tmp_path / "out",
    )
    try:
        assert agni.kosh.has_plugin("custom.analyzer")
        assert agni.kosh.has_capability("custom_analyzer")
        assert "custom_analyzer" in agni.capabilities
        # Built-ins are also present
        assert agni.kosh.has_capability("ocr")
        assert "ocr" in agni.capabilities
    finally:
        agni.close()


def test_replacement_composition_passes_validation_cleanly(tmp_path: Path) -> None:
    """Verify that replacement Agni(capabilities=...) registers only matching providers and passes consistency."""
    from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION as OCR_DECL

    mock_ocr = SimpleTestCapability(OCR_DECL)

    agni = Agni(
        capabilities={"ocr": mock_ocr},
        runtime_root=tmp_path / "rt",
        output_root=tmp_path / "out",
    )
    try:
        # Only matching provider (OCR) is registered in Kosh
        assert agni.kosh.has_capability("ocr")
        assert "ocr" in agni.capabilities
        # Non-matching builtins are NOT lingering in Kosh
        assert not agni.kosh.has_capability("bank_statements")
        assert not agni.kosh.has_capability("translation")
        assert not agni.kosh.has_capability("font_conversion")
        assert len(agni.capabilities) == 1
    finally:
        agni.close()


def test_operator_disabled_plugin_is_excluded_from_runtime(tmp_path: Path) -> None:
    """Verify that an operator-disabled plugin is cleanly excluded from Kosh and executables."""
    from sarathi.sankalpa import InputRef
    from sarathi.sutra import Settings

    settings = Settings({"plugins": {"disabled": ["shakti.translation"]}})

    agni = Agni(
        settings=settings,
        runtime_root=tmp_path / "rt",
        output_root=tmp_path / "out",
        input_root=tmp_path / "inp",
    )
    try:
        assert "shakti.translation" in agni.disabled_plugins
        # Excluded from Kosh and executables
        assert not agni.kosh.has_plugin("shakti.translation")
        assert not agni.kosh.has_capability("translation")
        assert "translation" not in agni.capabilities

        # Other builtins remain active and consistent
        assert agni.kosh.has_capability("ocr")
        assert "ocr" in agni.capabilities
        assert agni.kosh.has_capability("bank_statements")
        assert "bank_statements" in agni.capabilities

        # Executing a request for the disabled capability fails at Manthan resolution
        input_file = tmp_path / "inp" / "doc.txt"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.write_text("Hello World", encoding="utf-8")
        req = Request(
            request_id="req-trans",
            requirement="translation",
            inputs=(InputRef("inp-1", input_file, "doc.txt", input_file.stat().st_size),),
        )

        with pytest.raises(DoshError) as exc_info:
            agni.execute(req)
        assert exc_info.value.code in (FailureCode.UNSUPPORTED, FailureCode.VALIDATION_FAILED)
    finally:
        agni.close()
