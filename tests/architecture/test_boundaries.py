"""Architectural boundary tests asserting AST isolation and import-linter contract adherence."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from importlinter.cli import lint_imports


@pytest.mark.architecture
class TestArchitecturalBoundaries:
    """Verify architectural layering invariants across subsystem boundaries using AST and import-linter."""

    def test_import_linter_contracts_kept(self) -> None:
        """All declarative contracts defined in import-linter configuration must pass with zero violations."""
        exit_code = lint_imports()
        assert exit_code == 0, "import-linter found broken architectural contracts"

    def test_sankalpa_does_not_import_higher_layers(self) -> None:
        """sankalpa (contracts) must not import runtime or capabilities."""
        sankalpa_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "sankalpa"
        forbidden = (
            "sarathi.nabhi",
            "sarathi.shakti",
            "sarathi.agni",
            "sarathi.mukha",
            "sarathi.smriti",
            "sarathi.yantra",
            "sarathi.sutra",
            "sarathi.darpana",
            "sarathi.kavacha",
        )
        violations: list[str] = []
        for py_file in sankalpa_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(alias.name.startswith(f) for f in forbidden):
                            violations.append(f"{py_file.name}:{node.lineno} imports '{alias.name}'")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if any(mod.startswith(f) for f in forbidden):
                        violations.append(f"{py_file.name}:{node.lineno} imports from '{mod}'")
        assert not violations, "sankalpa layer violations:\n" + "\n".join(violations)

    def test_mukha_does_not_import_concrete_shakti_internals(self) -> None:
        """mukha presentation must not import concrete shakti capabilities or provider catalog."""
        mukha_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "mukha"
        forbidden = (
            "sarathi.shakti.providers",
            "sarathi.shakti.ocr",
            "sarathi.shakti.font_conversion",
            "sarathi.shakti.bank_statements",
            "sarathi.shakti.translation",
            "sarathi.shakti.native_extraction",
            "sarathi.shakti.darshana",
        )
        violations: list[str] = []
        for py_file in mukha_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(alias.name.startswith(f) for f in forbidden):
                            violations.append(f"{py_file.name}:{node.lineno} imports '{alias.name}'")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if any(mod.startswith(f) for f in forbidden):
                        violations.append(f"{py_file.name}:{node.lineno} imports from '{mod}'")
        assert not violations, "mukha layer violations:\n" + "\n".join(violations)

    def test_nabhi_generic_does_not_import_concrete_capabilities(self) -> None:
        """Generic nabhi modules must not import concrete capabilities (except dvara -> shakti.providers)."""
        nabhi_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "nabhi"
        forbidden = (
            "sarathi.shakti.ocr",
            "sarathi.shakti.font_conversion",
            "sarathi.shakti.bank_statements",
            "sarathi.shakti.translation",
            "sarathi.shakti.native_extraction",
            "sarathi.shakti.darshana",
        )
        violations: list[str] = []
        for py_file in nabhi_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(alias.name.startswith(f) for f in forbidden):
                            violations.append(f"{py_file.name}:{node.lineno} imports '{alias.name}'")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if any(mod.startswith(f) for f in forbidden):
                        violations.append(f"{py_file.name}:{node.lineno} imports from '{mod}'")
        assert not violations, "nabhi generic violations:\n" + "\n".join(violations)

    def test_dvara_is_sole_nabhi_to_shakti_provider_bridge(self) -> None:
        """dvara.py must be the only module in nabhi permitted to import sarathi.shakti.providers."""
        nabhi_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "nabhi"
        violations: list[str] = []
        for py_file in nabhi_dir.rglob("*.py"):
            if py_file.name == "dvara.py":
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "sarathi.shakti" in alias.name:
                            violations.append(f"{py_file.name}:{node.lineno} imports '{alias.name}'")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if "sarathi.shakti" in mod:
                        violations.append(f"{py_file.name}:{node.lineno} imports from '{mod}'")
        assert not violations, f"Unauthorized nabhi -> shakti bridges detected:\n" + "\n".join(violations)

    def test_cross_shakti_plugin_isolation(self) -> None:
        """Plugins under shakti must not import internals of sibling plugins directly."""
        shakti_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "shakti"
        plugins = [
            "bank_statements",
            "darshana",
            "font_conversion",
            "native_extraction",
            "ocr",
            "translation",
        ]
        violations: list[str] = []
        for plugin in plugins:
            plugin_path = shakti_dir / plugin
            other_plugins = [p for p in plugins if p != plugin]
            for py_file in plugin_path.rglob("*.py"):
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            for other in other_plugins:
                                if f"sarathi.shakti.{other}" in alias.name:
                                    violations.append(f"{plugin}/{py_file.name}:{node.lineno} imports '{alias.name}'")
                    elif isinstance(node, ast.ImportFrom):
                        mod = node.module or ""
                        for other in other_plugins:
                            if f"sarathi.shakti.{other}" in mod:
                                violations.append(f"{plugin}/{py_file.name}:{node.lineno} imports from '{mod}'")
        assert not violations, "Cross-plugin violations:\n" + "\n".join(violations)
