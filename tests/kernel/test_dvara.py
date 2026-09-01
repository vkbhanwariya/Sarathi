"""Unit and integration tests for Dvara — Built-in Plugin Discovery & Registration."""

from __future__ import annotations

from pathlib import Path
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import Dvara, Kosh, Manthan
from sarathi.sankalpa import (
    CapabilityDeclaration,
    DeviceRequirement,
    DeviceType,
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


class TestDvaraConstructorAndRegistration:
    def test_dvara_requires_kosh_instance(self) -> None:
        with pytest.raises(TypeError, match="registry must be a Kosh instance"):
            Dvara("not_a_kosh")  # type: ignore

    def test_register_builtins_registers_all_shakti_plugins(self, kosh: Kosh) -> None:
        dvara = Dvara(kosh)
        registered_ids = dvara.register_builtins()

        assert "shakti.darshana" in registered_ids
        assert "shakti.native_extraction" in registered_ids
        assert "shakti.ocr" in registered_ids

        # Verify Kosh contains the plugins
        assert kosh.has_plugin("shakti.darshana")
        assert kosh.has_plugin("shakti.native_extraction")
        assert kosh.has_plugin("shakti.ocr")

        # Verify Kosh contains capabilities
        assert kosh.get_capability("identify") is not None
        assert kosh.get_capability("read_native") is not None
        assert kosh.get_capability("ocr") is not None

    def test_register_builtins_is_idempotent(self, kosh: Kosh) -> None:
        dvara = Dvara(kosh)
        first_pass = dvara.register_builtins()
        second_pass = dvara.register_builtins()

        assert first_pass == second_pass
        assert len(kosh.get_capabilities_for_plugin("shakti.ocr")) == 1

    def test_preflight_conflict_in_plugin_fails_before_mutation(self, kosh: Kosh) -> None:
        # Pre-register a conflicting plugin with same ID but different version/name
        tampered_plugin = PluginInfo(
            plugin_id="shakti.darshana",
            name="Conflicting Tampered Darshana",
            version="9.9.9",
            security=SecurityDeclaration(),
            capabilities=("identify",),
        )
        kosh.register_plugin(tampered_plugin)

        dvara = Dvara(kosh)
        with pytest.raises(DoshError) as exc_info:
            dvara.register_builtins()

        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "Conflicting plugin declaration already registered" in exc_info.value.message

        # Assert no other built-in plugins were registered (atomic preflight)
        assert not kosh.has_plugin("shakti.ocr")
        assert not kosh.has_plugin("shakti.native_extraction")

    def test_preflight_conflict_in_capability_fails_before_mutation(self, kosh: Kosh) -> None:
        # Pre-register genuine plugin, but with a conflicting capability definition
        p = PluginInfo(
            plugin_id="shakti.ocr",
            name="OCR",
            version="1.0.0",
            security=SecurityDeclaration(),
            capabilities=("ocr",),
        )
        kosh.register_plugin(p)
        tampered_cap = CapabilityDeclaration(
            capability_id="ocr",
            plugin_id="shakti.ocr",
            version="9.9.9",
            supported_profiles=(ExecutionProfile.CUSTOM,),
        )
        kosh.register_capability(tampered_cap)

        dvara = Dvara(kosh)
        with pytest.raises(DoshError) as exc_info:
            dvara.register_builtins()

        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "Conflicting capability declaration already registered" in exc_info.value.message

        # Assert no other plugins registered
        assert not kosh.has_plugin("shakti.darshana")
        assert not kosh.has_plugin("shakti.native_extraction")


class TestDarshanaManthanIntegrationWiring:
    def test_actual_darshana_enriched_request_reaches_manthan(self, tmp_path: Path, kosh: Kosh) -> None:
        # 1. Setup Dvara and Manthan sharing the SAME Kosh instance
        dvara = Dvara(kosh)
        dvara.register_builtins()
        manthan = Manthan(kosh)

        # 2. Create an input without media_type (as standard during intake)
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

        # 3. Canonical intake enrichment via Darshana
        enriched_request = identify_request(initial_request)

        assert enriched_request.inputs[0].media_type == "application/pdf"
        assert "darshana_facts" in enriched_request.inputs[0].metadata

        # 4. Resolve via Manthan directly using the enriched Request
        plan = manthan.resolve(enriched_request)
        assert plan.request_id == "req-process-1"
        assert plan.capability_ids == ("ocr",)
