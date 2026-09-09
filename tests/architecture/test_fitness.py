"""Architecture fitness checks focused on maintainability, not arbitrary shape."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.architecture
class TestArchitecturalFitness:
    def test_key_packages_are_importable(self) -> None:
        packages = [
            "sarathi.agni",
            "sarathi.darpana",
            "sarathi.dosh",
            "sarathi.kavacha",
            "sarathi.mukha",
            "sarathi.nabhi",
            "sarathi.sankalpa",
            "sarathi.shakti",
            "sarathi.smriti",
            "sarathi.sutra",
            "sarathi.yantra",
        ]
        for package in packages:
            importlib.import_module(package)

    def test_shared_shakti_helpers_are_importable(self) -> None:
        for package in (
            "sarathi.shakti.docx_exporter",
            "sarathi.shakti.text.span_protection",
        ):
            importlib.import_module(package)
