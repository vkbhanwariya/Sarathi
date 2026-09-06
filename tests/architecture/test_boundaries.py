"""Architectural boundary tests asserting AST isolation and import-linter contract adherence.

All boundary rules and group memberships are derived directly from Vedas/architecture.manifest.json,
ensuring the manifest remains the single dependency authority.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from importlinter.cli import lint_imports


def _load_manifest() -> dict:
    manifest_path = Path(__file__).resolve().parents[2] / "Vedas" / "architecture.manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@pytest.mark.architecture
class TestArchitecturalBoundaries:
    """Verify architectural layering invariants across subsystem boundaries using AST and import-linter."""

    def test_import_linter_contracts_kept(self) -> None:
        """All declarative contracts defined in import-linter configuration must pass with zero violations."""
        exit_code = lint_imports()
        assert exit_code == 0, "import-linter found broken architectural contracts"

    def test_sankalpa_does_not_import_higher_layers(self) -> None:
        """sankalpa (contracts) must not import runtime or capabilities."""
        manifest = _load_manifest()
        sankalpa_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "sankalpa"
        all_packages = {m["package"] for m in manifest["modules"].values()}
        allowed = set(manifest["modules"]["sankalpa"].get("may_import", [])) | {"sarathi.sankalpa"}
        forbidden = tuple(sorted(p for p in all_packages if p not in allowed))

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
        manifest = _load_manifest()
        mukha_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "mukha"
        forbidden = tuple(sorted(manifest["groups"]["shakti_plugins"]["members"] + ["sarathi.shakti.providers"]))

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
        manifest = _load_manifest()
        nabhi_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "nabhi"
        forbidden = tuple(sorted(manifest["groups"]["shakti_plugins"]["members"]))

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
        assert not violations, "Unauthorized nabhi -> shakti bridges detected:\n" + "\n".join(violations)

    def test_cross_shakti_plugin_isolation(self) -> None:
        """Plugins under shakti must not import internals of sibling plugins directly."""
        manifest = _load_manifest()
        shakti_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "shakti"
        plugin_members = manifest["groups"]["shakti_plugins"]["members"]
        plugins = [p.split(".")[-1] for p in plugin_members]

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

    def test_docx_exporter_does_not_import_concrete_shakti_plugins(self) -> None:
        """Shared docx_exporter must not import from any concrete shakti capability plugin."""
        manifest = _load_manifest()
        docx_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "shakti" / "docx_exporter"
        forbidden = tuple(sorted(manifest["groups"]["shakti_plugins"]["members"]))

        violations: list[str] = []
        for py_file in docx_dir.rglob("*.py"):
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
        assert not violations, "docx_exporter plugin leak violations:\n" + "\n".join(violations)
