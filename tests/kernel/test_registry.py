"""Unit tests for Nabhi — Core Kernel Phase 1: Kosh Registry."""

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import Kosh
import sarathi.nabhi as nabhi_module
from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionProfile,
    PluginInfo,
    SecurityDeclaration,
)


@pytest.fixture
def kosh() -> Kosh:
    return Kosh()


@pytest.fixture
def sample_plugin() -> PluginInfo:
    return PluginInfo(
        plugin_id="shakti.ocr",
        name="OCR Plugin",
        version="2.0.0",
        security=SecurityDeclaration(),
        capabilities=("ocr",),
    )


@pytest.fixture
def sample_capability() -> CapabilityDeclaration:
    return CapabilityDeclaration(
        capability_id="ocr",
        plugin_id="shakti.ocr",
        version="2.0.0",
        supported_profiles=(ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE),
        supported_input_types=("application/pdf", "image/png"),
    )


class TestKoshRegistry:
    def test_empty_registry(self, kosh: Kosh) -> None:
        assert len(kosh) == 0
        assert kosh.plugins() == ()
        assert kosh.capabilities() == ()
        assert kosh.get_plugin("shakti.ocr") is None
        assert kosh.get_capability("ocr") is None
        assert kosh.has_plugin("shakti.ocr") is False
        assert kosh.has_capability("ocr") is False

    def test_plugin_registration_and_lookup(self, kosh: Kosh, sample_plugin: PluginInfo) -> None:
        kosh.register_plugin(sample_plugin)

        assert kosh.has_plugin("shakti.ocr") is True
        assert kosh.get_plugin("shakti.ocr") == sample_plugin
        assert kosh.plugins() == (sample_plugin,)
        assert isinstance(kosh.plugins(), tuple)

    def test_capability_registration_and_lookup(
        self,
        kosh: Kosh,
        sample_plugin: PluginInfo,
        sample_capability: CapabilityDeclaration,
    ) -> None:
        kosh.register_plugin(sample_plugin)
        kosh.register_capability(sample_capability)

        assert len(kosh) == 1
        assert kosh.has_capability("ocr") is True
        assert kosh.get_capability("ocr") == sample_capability
        assert kosh.capabilities() == (sample_capability,)
        assert kosh.get_capabilities_for_plugin("shakti.ocr") == (sample_capability,)

    def test_capability_without_registered_plugin_rejected(
        self,
        kosh: Kosh,
        sample_capability: CapabilityDeclaration,
    ) -> None:
        # Owning plugin "shakti.ocr" has not been registered yet
        with pytest.raises(DoshError) as exc_info:
            kosh.register_capability(sample_capability)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "is not registered" in err.message
        assert len(kosh) == 0

    def test_duplicate_plugin_registration_rejected(
        self,
        kosh: Kosh,
        sample_plugin: PluginInfo,
    ) -> None:
        kosh.register_plugin(sample_plugin)

        duplicate_plugin = PluginInfo(
            plugin_id="shakti.ocr",
            name="Conflicting OCR Plugin",
            version="3.0.0",
        )

        with pytest.raises(DoshError) as exc_info:
            kosh.register_plugin(duplicate_plugin)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "already registered" in err.message

        # Verify no overwrite occurred
        assert kosh.get_plugin("shakti.ocr") == sample_plugin

    def test_duplicate_capability_registration_rejected(
        self,
        kosh: Kosh,
        sample_plugin: PluginInfo,
        sample_capability: CapabilityDeclaration,
    ) -> None:
        kosh.register_plugin(sample_plugin)
        kosh.register_capability(sample_capability)

        duplicate_cap = CapabilityDeclaration(
            capability_id="ocr",
            plugin_id="shakti.ocr",
            version="2.1.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )

        with pytest.raises(DoshError) as exc_info:
            kosh.register_capability(duplicate_cap)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "already registered" in err.message

        # Verify original capability remains
        assert kosh.get_capability("ocr") == sample_capability
        assert len(kosh) == 1

    def test_undeclared_capability_rejected(
        self,
        kosh: Kosh,
        sample_plugin: PluginInfo,
    ) -> None:
        kosh.register_plugin(sample_plugin)

        undeclared_cap = CapabilityDeclaration(
            capability_id="undeclared.ocr",
            plugin_id="shakti.ocr",
            version="2.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )

        with pytest.raises(DoshError) as exc_info:
            kosh.register_capability(undeclared_cap)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "not declared by owning plugin" in err.message

    def test_undeclared_capability_rejection_leaves_state_unmutated(
        self,
        kosh: Kosh,
        sample_plugin: PluginInfo,
        sample_capability: CapabilityDeclaration,
    ) -> None:
        kosh.register_plugin(sample_plugin)
        kosh.register_capability(sample_capability)

        # Baseline snapshots before rejection
        plugins_before = kosh.plugins()
        caps_before = kosh.capabilities()
        plugin_caps_before = kosh.get_capabilities_for_plugin("shakti.ocr")
        count_before = len(kosh)

        undeclared_cap = CapabilityDeclaration(
            capability_id="undeclared.cap",
            plugin_id="shakti.ocr",
            version="2.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )

        with pytest.raises(DoshError) as exc_info:
            kosh.register_capability(undeclared_cap)

        assert exc_info.value.code is FailureCode.VALIDATION_FAILED

        # Verify state is completely unmutated
        assert len(kosh) == count_before
        assert kosh.plugins() == plugins_before
        assert kosh.capabilities() == caps_before
        assert kosh.get_capabilities_for_plugin("shakti.ocr") == plugin_caps_before
        assert kosh.get_capability("undeclared.cap") is None
        assert kosh.has_capability("undeclared.cap") is False

    def test_registration_order_preserved_in_snapshots(self, kosh: Kosh) -> None:
        p1 = PluginInfo(plugin_id="plugin.a", name="A", version="1.0", capabilities=("cap.1", "cap.3"))
        p2 = PluginInfo(plugin_id="plugin.b", name="B", version="1.0", capabilities=("cap.2",))
        p3 = PluginInfo(plugin_id="plugin.c", name="C", version="1.0")

        kosh.register_plugin(p1)
        kosh.register_plugin(p2)
        kosh.register_plugin(p3)

        c1 = CapabilityDeclaration(
            capability_id="cap.1",
            plugin_id="plugin.a",
            version="1.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        c2 = CapabilityDeclaration(
            capability_id="cap.2",
            plugin_id="plugin.b",
            version="1.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        c3 = CapabilityDeclaration(
            capability_id="cap.3",
            plugin_id="plugin.a",
            version="1.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )

        kosh.register_capability(c1)
        kosh.register_capability(c2)
        kosh.register_capability(c3)

        assert kosh.plugins() == (p1, p2, p3)
        assert kosh.capabilities() == (c1, c2, c3)
        assert kosh.get_capabilities_for_plugin("plugin.a") == (c1, c3)

    def test_invalid_argument_types(self, kosh: Kosh) -> None:
        with pytest.raises(TypeError, match="plugin must be a PluginInfo"):
            kosh.register_plugin("not_a_plugin")  # type: ignore

        with pytest.raises(TypeError, match="capability must be a CapabilityDeclaration"):
            kosh.register_capability("not_a_capability")  # type: ignore

        with pytest.raises(TypeError, match="plugin_id must be a string"):
            kosh.get_plugin(123)  # type: ignore

        with pytest.raises(TypeError, match="capability_id must be a string"):
            kosh.get_capability(123)  # type: ignore

        with pytest.raises(TypeError, match="plugin_id must be a string"):
            kosh.get_capabilities_for_plugin(None)  # type: ignore

    def test_nabhi_exports(self) -> None:
        expected = {"ArtifactBoundary", "CapabilityPlan", "Kosh", "Manthan", "Prana", "Pravaha"}
        assert set(nabhi_module.__all__) == expected
        for name in expected:
            assert hasattr(nabhi_module, name)
