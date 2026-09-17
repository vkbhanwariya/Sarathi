"""Lightweight dependency sanity checks.

These tests prevent obvious layering mistakes without enforcing artificial isolation
between cooperating document-processing capabilities.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _imports_under(package_dir: Path) -> set[str]:
    imports: set[str] = set()
    for py_file in package_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


@pytest.mark.architecture
class TestArchitecturalBoundaries:
    def test_contracts_do_not_depend_on_ui_or_capability_implementations(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        imports = _imports_under(repo_root / "src" / "sarathi" / "sankalpa")
        forbidden_prefixes = ("sarathi.mukha", "sarathi.shakti")
        violations = sorted(name for name in imports if name.startswith(forbidden_prefixes))
        assert not violations, f"Shared contracts depend on higher-level implementation packages: {violations}"

    def test_capability_code_does_not_depend_on_ui(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        imports = _imports_under(repo_root / "src" / "sarathi" / "shakti")
        violations = sorted(name for name in imports if name.startswith("sarathi.mukha"))
        assert not violations, f"Document-processing capabilities depend on UI code: {violations}"

    def test_pravaha_does_not_construct_plans_or_select_supported_profiles(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        violations: list[str] = []
        for py_file in (repo_root / "src" / "sarathi" / "nabhi" / "pravaha").rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "CapabilityPlan":
                    violations.append(f"{py_file.name}: constructs CapabilityPlan")
                if isinstance(node, ast.Attribute) and node.attr == "supported_profiles":
                    violations.append(f"{py_file.name}: inspects supported_profiles")
        assert not violations, f"Pravaha contains planning decisions owned by Manthan: {violations}"

    def test_all_subsystem_imports_conform_to_manifest_may_import(self) -> None:
        """Every cross-subsystem import under src/sarathi must be explicitly declared in architecture.manifest.json."""
        import json

        repo_root = Path(__file__).resolve().parents[2]
        manifest_path = repo_root / "Vedas" / "architecture.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        src_root = repo_root / "src" / "sarathi"

        modules = manifest.get("modules", {})
        violations: list[str] = []

        for mod_name, mod_info in modules.items():
            mod_dir = src_root / mod_name
            if not mod_dir.is_dir():
                continue

            allowed = set(mod_info.get("may_import", []))
            if "*" in allowed:
                continue

            for py_file in mod_dir.rglob("*.py"):
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
                for node in ast.walk(tree):
                    imported_module = None
                    lineno = getattr(node, "lineno", 0)
                    if isinstance(node, ast.Import):
                        for a in node.names:
                            if a.name.startswith("sarathi."):
                                imported_module = a.name
                    elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("sarathi."):
                        imported_module = node.module

                    if imported_module:
                        parts = imported_module.split(".")
                        if len(parts) >= 2:
                            target_sub = parts[1]
                            target_pkg = f"sarathi.{target_sub}"
                            # Intra-subsystem imports are allowed; cross-subsystem imports must be declared
                            if target_sub != mod_name and target_pkg not in allowed:
                                rel_file = py_file.relative_to(repo_root)
                                violations.append(
                                    f"{rel_file}:{lineno} illegal import of '{imported_module}'; "
                                    f"subsystem '{mod_name}' may only import: {sorted(allowed)}"
                                )

        assert not violations, (
            f"Cross-subsystem architectural boundary violations found ({len(violations)}):\n"
            + "\n".join(violations)
        )
