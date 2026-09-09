"""Unit tests for Agni bootstrap dependency injection and lifecycle ownership."""

from __future__ import annotations

from pathlib import Path

from sarathi.agni import Agni
from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionContext,
    ExecutionProfile,
    PluginInfo,
    Request,
    Result,
)
from sarathi.sutra import Settings


class CustomImmutableCapability:
    def __init__(self) -> None:
        self.declaration = CapabilityDeclaration(
            capability_id="custom_cap",
            plugin_id="custom.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        self.executed = False

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        self.executed = True
        return Result(data="custom_ok")


class UserCapabilityWithNoneYantra:
    def __init__(self) -> None:
        self.declaration = CapabilityDeclaration(
            capability_id="none_cap",
            plugin_id="custom.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        self._yantra = None

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        return Result(data="none_ok")


class TestBootstrapDependencyInjection:
    def test_default_capabilities_receive_injected_dependencies(self, tmp_path: Path) -> None:
        settings = Settings({
            "storage": {
                "input_root": str(tmp_path / "inputs"),
                "output_root": str(tmp_path / "outputs"),
                "runtime_root": str(tmp_path / "runtime"),
            },
            "telemetry": {"live_buffer_capacity": 512},
        })

        agni = Agni(settings=settings)
        try:
            assert agni.darpana.capacity == 512
            caps = agni.capabilities
            assert "ocr" in caps
            assert caps["ocr"]._yantra is agni.yantra
            assert caps["ocr"]._darpana is agni.darpana
            assert caps["identify"]._darpana is agni.darpana
            assert caps["read_native"]._darpana is agni.darpana
            assert caps["bank_statements"]._darpana is agni.darpana
            assert caps["font_conversion"]._darpana is agni.darpana
            assert caps["translation"]._darpana is agni.darpana
        finally:
            agni.close()

    def test_user_supplied_capabilities_are_not_mutated(self, tmp_path: Path) -> None:
        settings = Settings({
            "storage": {
                "input_root": str(tmp_path / "inputs"),
                "output_root": str(tmp_path / "outputs"),
                "runtime_root": str(tmp_path / "runtime"),
            },
        })
        cap1 = CustomImmutableCapability()
        cap2 = UserCapabilityWithNoneYantra()
        plugin = PluginInfo(
            plugin_id="custom.plugin",
            name="Custom Plugin",
            version="1.0.0",
            capabilities=("custom_cap", "none_cap"),
        )

        agni = Agni(
            settings=settings,
            capabilities={"custom_cap": cap1, "none_cap": cap2},
            plugins=[plugin],
        )
        try:
            assert not hasattr(cap1, "_yantra")
            assert cap2._yantra is None
        finally:
            agni.close()

    def test_smriti_cache_auto_managed_by_agni(self, tmp_path: Path) -> None:
        from sarathi.smriti import SmritiCache

        settings = Settings({
            "storage": {
                "input_root": str(tmp_path / "in"),
                "output_root": str(tmp_path / "out"),
                "runtime_root": str(tmp_path / "rt"),
            },
            "cache": {"enabled": True},
        })
        agni = Agni(settings=settings)
        try:
            assert agni.smriti is not None
            assert isinstance(agni.smriti, SmritiCache)
            assert "smriti" in agni.registered_component_ids()
        finally:
            agni.close()
