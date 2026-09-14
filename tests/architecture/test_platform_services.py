"""Architectural invariant tests for platform services and capability isolation."""

from __future__ import annotations

import dataclasses
import sys

import pytest

from sarathi.sankalpa import PluginProvider, PluginServices
from sarathi.shakti.providers import BUILTIN_PLUGIN_PROVIDERS


@pytest.mark.architecture
class TestPlatformServicesArchitecture:
    """Ensure PluginServices remains a constrained platform container rather than an unconstrained service locator."""

    def test_plugin_services_fields_strictly_constrained(self) -> None:
        """PluginServices dataclass must only expose approved platform services."""
        approved_fields = {
            "darpana",
            "yantra",
            "kavacha",
            "settings",
            "data_root",
        }
        actual_fields = {field.name for field in dataclasses.fields(PluginServices)}

        assert actual_fields == approved_fields, (
            f"PluginServices fields deviated from architectural contract: {actual_fields ^ approved_fields}"
        )

    def test_builtin_providers_implement_plugin_provider_protocol(self) -> None:
        """Every built-in provider registered in the catalog must implement the PluginProvider protocol."""
        assert len(BUILTIN_PLUGIN_PROVIDERS) > 0, "No built-in providers registered"

        for provider in BUILTIN_PLUGIN_PROVIDERS:
            assert isinstance(provider, PluginProvider), (
                f"Provider {type(provider).__name__} does not satisfy PluginProvider protocol"
            )
            assert provider.plugin_info is not None
            assert len(provider.declarations) > 0

    def test_shakti_package_roots_remain_lazy(self) -> None:
        """Importing shakti package roots must not eagerly import heavy neural or execution libraries."""
        import subprocess

        cmd = [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import sarathi.shakti.bank_statements; "
                "import sarathi.shakti.darshana; "
                "import sarathi.shakti.font_conversion; "
                "import sarathi.shakti.native_extraction; "
                "import sarathi.shakti.ocr; "
                "import sarathi.shakti.translation; "
                "heavy = {'openvino', 'rapidocr', 'ctranslate2', 'sentencepiece'}; "
                "loaded = heavy.intersection(sys.modules); "
                "assert not loaded, f'Heavy modules eagerly loaded: {loaded}'"
            ),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"Lazy import violation in isolated process:\n{res.stderr}"
