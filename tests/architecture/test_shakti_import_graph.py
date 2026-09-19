"""Architecture test asserting that sarathi.shakti subpackages have an acyclic import graph.

Specifically:
- The dependency graph between shakti subpackages must be a DAG (no cycles).
- docx_exporter and text must not import any capability packages.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CAPABILITY_PACKAGES = {
    "ocr",
    "translation",
    "font_conversion",
    "native_extraction",
    "bank_statements",
    "statutory",
    "darshana",
    "cloud_providers",
}


def _get_shakti_subpackages(shakti_root: Path) -> set[str]:
    subpkgs = set()
    for item in shakti_root.iterdir():
        if item.is_dir() and (item / "__init__.py").is_file():
            subpkgs.add(item.name)
    return subpkgs


def _extract_imports(file_path: Path, shakti_subpkgs: set[str]) -> set[str]:
    """Parse file and return all sarathi.shakti.<subpackage> names imported."""
    targets = set()
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except Exception:
        return targets

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name.startswith("sarathi.shakti."):
                    parts = name.split(".")
                    if len(parts) >= 3 and parts[2] in shakti_subpkgs:
                        targets.add(parts[2])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("sarathi.shakti."):
                parts = mod.split(".")
                if len(parts) >= 3 and parts[2] in shakti_subpkgs:
                    targets.add(parts[2])
            elif node.level > 0:
                pass
    return targets


def _build_import_graph(shakti_root: Path) -> dict[str, set[str]]:
    shakti_subpkgs = _get_shakti_subpackages(shakti_root)
    graph: dict[str, set[str]] = {pkg: set() for pkg in shakti_subpkgs}

    for pkg in shakti_subpkgs:
        pkg_dir = shakti_root / pkg
        for py_file in pkg_dir.rglob("*.py"):
            imported = _extract_imports(py_file, shakti_subpkgs)
            for imp in imported:
                if imp != pkg:
                    graph[pkg].add(imp)

    return graph


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visited: dict[str, int] = {}  # 0 = visiting, 1 = visited
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        visited[node] = 0
        path.append(node)
        for neighbor in sorted(graph.get(node, ())):
            if visited.get(neighbor) == 0:
                cycle_start = path.index(neighbor)
                return path[cycle_start:] + [neighbor]
            if neighbor not in visited:
                cycle = dfs(neighbor)
                if cycle:
                    return cycle
        path.pop()
        visited[node] = 1
        return None

    for n in sorted(graph.keys()):
        if n not in visited:
            cycle = dfs(n)
            if cycle:
                return cycle
    return None


@pytest.mark.architecture
def test_bug_m3_shakti_import_graph_is_acyclic():
    shakti_root = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "shakti"
    assert shakti_root.is_dir()

    graph = _build_import_graph(shakti_root)
    cycle = _find_cycle(graph)
    assert cycle is None, f"Circular import cycle detected in shakti subpackages: {' -> '.join(cycle)}"


@pytest.mark.architecture
def test_bug_m3_docx_exporter_and_text_import_no_capabilities():
    shakti_root = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "shakti"
    graph = _build_import_graph(shakti_root)

    for base_pkg in ("docx_exporter", "text"):
        imports = graph.get(base_pkg, set())
        forbidden = imports & CAPABILITY_PACKAGES
        assert not forbidden, f"Package {base_pkg} forbiddenly imports capabilities: {forbidden}"
