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
