"""Unit tests for Agni bootstrap composition-root dependency injection and immutability."""

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
    """A user-supplied capability without private _yantra attribute."""

    def __init__(self) -> None:
        self.declaration = CapabilityDeclaration(
            capability_id="custom_cap",
            plugin_id="custom.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        self.executed: bool = False

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        self.executed = True
        return Result(data="custom_ok")


class UserCapabilityWithNoneYantra:
    """A user capability that explicitly sets _yantra = None and should NOT be mutated."""

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
        in_dir = tmp_path / "inputs"
        out_dir = tmp_path / "outputs"
        rt_dir = tmp_path / "runtime"
        in_dir.mkdir()
        out_dir.mkdir()
        rt_dir.mkdir()

        settings = Settings({
            "storage": {
                "input_root": str(in_dir),
                "output_root": str(out_dir),
                "runtime_root": str(rt_dir),
            },
            "telemetry": {
                "live_buffer_capacity": 512,
            },
        })

        agni = Agni(settings=settings)
        try:
            # Check Darpana was constructed with Sutra live_buffer_capacity
            assert agni.darpana.capacity == 512

            # Check default OCRCapability received Yantra and Darpana at construction
            caps = agni.capabilities
            assert "ocr" in caps
            ocr_cap = caps["ocr"]
            assert hasattr(ocr_cap, "_yantra")
            assert ocr_cap._yantra is agni.yantra
            assert ocr_cap._darpana is agni.darpana

            # Check other default capabilities received Darpana
            assert caps["identify"]._darpana is agni.darpana
            assert caps["read_native"]._darpana is agni.darpana
            assert caps["bank_statements"]._darpana is agni.darpana
            assert caps["font_conversion"]._darpana is agni.darpana
            assert caps["translation"]._darpana is agni.darpana
        finally:
            agni.close()

    def test_user_supplied_capabilities_are_not_mutated(self, tmp_path: Path) -> None:
        in_dir = tmp_path / "inputs"
        out_dir = tmp_path / "outputs"
        rt_dir = tmp_path / "runtime"
        in_dir.mkdir()
        out_dir.mkdir()
        rt_dir.mkdir()

        settings = Settings({
            "storage": {
                "input_root": str(in_dir),
                "output_root": str(out_dir),
                "runtime_root": str(rt_dir),
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
            # cap1 must not have _yantra dynamically attached
            assert not hasattr(cap1, "_yantra")

            # cap2 must still have _yantra is None (not overwritten by bootstrap)
            assert cap2._yantra is None
        finally:
            agni.close()
