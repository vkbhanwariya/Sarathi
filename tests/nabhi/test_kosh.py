"""Tests for the Nabhi Kosh plugin and capability registry."""

from pathlib import Path

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import Kosh, Manthan
from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionProfile,
    InputRef,
    PluginInfo,
    Request,
    SecurityDeclaration,
)
from sarathi.shakti.darshana import identify_request


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
        with pytest.raises(TypeError, match="providers must be a sequence"):
            kosh.register_providers(123)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="plugin must be a PluginInfo"):
            kosh.register_plugin("not_a_plugin")  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="capability must be a CapabilityDeclaration"):
            kosh.register_capability("not_a_capability")  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="plugin_id must be a string"):
            kosh.get_plugin(123)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="capability_id must be a string"):
            kosh.get_capability(123)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="plugin_id must be a string"):
            kosh.get_capabilities_for_plugin(None)  # type: ignore[arg-type]


class TestKoshProviderRegistration:
    def test_register_providers_registers_builtin_metadata(self, kosh: Kosh) -> None:
        from sarathi.shakti.providers import BUILTIN_PLUGIN_PROVIDERS

        registered_ids = kosh.register_providers(BUILTIN_PLUGIN_PROVIDERS)

        assert "shakti.darshana" in registered_ids
        assert "shakti.native_extraction" in registered_ids
        assert "shakti.ocr" in registered_ids
        assert "shakti.translation" in registered_ids
        assert kosh.get_capability("identify") is not None
        assert kosh.get_capability("read_native") is not None
        assert kosh.get_capability("ocr") is not None
        assert kosh.get_capability("translation") is not None

    def test_register_providers_is_idempotent(self, kosh: Kosh) -> None:
        from sarathi.shakti.providers import BUILTIN_PLUGIN_PROVIDERS

        first_pass = kosh.register_providers(BUILTIN_PLUGIN_PROVIDERS)
        second_pass = kosh.register_providers(BUILTIN_PLUGIN_PROVIDERS)

        assert first_pass == second_pass
        assert len(kosh.get_capabilities_for_plugin("shakti.ocr")) == 1

    def test_provider_conflict_fails_before_batch_mutation(self, kosh: Kosh) -> None:
        from sarathi.shakti.providers import BUILTIN_PLUGIN_PROVIDERS

        tampered_plugin = PluginInfo(
            plugin_id="shakti.darshana",
            name="Conflicting Tampered Darshana",
            version="9.9.9",
            security=SecurityDeclaration(),
            capabilities=("identify",),
        )
        kosh.register_plugin(tampered_plugin)

        with pytest.raises(DoshError) as exc_info:
            kosh.register_providers(BUILTIN_PLUGIN_PROVIDERS)

        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "Conflicting plugin declaration already registered" in exc_info.value.message
        assert not kosh.has_plugin("shakti.ocr")
        assert not kosh.has_plugin("shakti.native_extraction")

    def test_capability_conflict_fails_before_batch_mutation(self, kosh: Kosh) -> None:
        from sarathi.shakti.providers import BUILTIN_PLUGIN_PROVIDERS

        plugin = PluginInfo(
            plugin_id="shakti.ocr",
            name="OCR",
            version="1.0.0",
            security=SecurityDeclaration(),
            capabilities=("ocr",),
        )
        kosh.register_plugin(plugin)
        tampered_capability = CapabilityDeclaration(
            capability_id="ocr",
            plugin_id="shakti.ocr",
            version="9.9.9",
            supported_profiles=(ExecutionProfile.CUSTOM,),
        )
        kosh.register_capability(tampered_capability)

        with pytest.raises(DoshError) as exc_info:
            kosh.register_providers(BUILTIN_PLUGIN_PROVIDERS)

        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "Conflicting capability declaration already registered" in exc_info.value.message
        assert not kosh.has_plugin("shakti.darshana")
        assert not kosh.has_plugin("shakti.native_extraction")

    def test_provider_capabilities_must_match_plugin_info_before_mutation(self, kosh: Kosh) -> None:
        from sarathi.shakti.darshana.provider import DarshanaProvider

        tampered_plugin = PluginInfo(
            plugin_id="shakti.darshana",
            name="Darshana",
            version="1.0.0",
            security=SecurityDeclaration(),
            capabilities=("identify", "extra_cap"),
        )

        class TamperedDarshanaProvider(DarshanaProvider):
            @property
            def plugin_info(self) -> PluginInfo:
                return tampered_plugin

        with pytest.raises(DoshError) as exc_info:
            kosh.register_providers([TamperedDarshanaProvider()])

        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "do not exactly match" in exc_info.value.message
        assert not kosh.has_plugin("shakti.darshana")

    def test_duplicate_provider_id_in_single_batch_is_rejected(self, kosh: Kosh) -> None:
        from sarathi.shakti.darshana.provider import DarshanaProvider

        provider = DarshanaProvider()
        with pytest.raises(DoshError, match="Duplicate plugin ID"):
            kosh.register_providers([provider, provider])

        assert kosh.plugins() == ()
        assert kosh.capabilities() == ()

    def test_darshana_enriched_request_reaches_manthan(self, tmp_path: Path, kosh: Kosh) -> None:
        from sarathi.shakti.providers import BUILTIN_PLUGIN_PROVIDERS

        kosh.register_providers(BUILTIN_PLUGIN_PROVIDERS)
        manthan = Manthan(kosh)

        pdf_file = tmp_path / "invoice.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\nInvoice details")
        raw_input = InputRef(
            input_id="inp-invoice-1",
            source_path=pdf_file,
            display_name="invoice.pdf",
            size_bytes=pdf_file.stat().st_size,
            media_type=None,
        )
        initial_request = Request(
            request_id="req-process-1",
            requirement="ocr",
            inputs=(raw_input,),
            profile=ExecutionProfile.INSTANT,
        )

        enriched_request = identify_request(initial_request)
        assert enriched_request.inputs[0].media_type == "application/pdf"
        assert "darshana_facts" in enriched_request.inputs[0].metadata

        plan = manthan.resolve(enriched_request)
        assert plan.request_id == "req-process-1"
        assert plan.capability_ids == ("ocr",)
