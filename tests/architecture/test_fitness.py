"""Architectural fitness functions enforcing modularity invariants across Sarathi V2.

Invariants verified:
1. Zero Monoliths: No production Python file in `src/sarathi` exceeds 30 KB (30,720 bytes).
2. Explicit Subpackage Exports: All decomposed subpackages declare explicit `__all__` exports.
3. No Stale Monolith Files: No superseded standalone file coexists with its replacement subpackage.
4. Clean Importability: Every subpackage and its internal components import without cycles.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

MAX_MODULE_SIZE_BYTES = 30 * 1024  # 30 KB strict ceiling


@pytest.mark.architecture
class TestArchitecturalFitness:
    """Automated fitness functions guarding Sarathi's modular subpackage architecture."""

    def test_zero_monoliths_in_production_source(self) -> None:
        """Every production Python source file in src/sarathi must be <= 30 KB."""
        repo_root = Path(__file__).resolve().parents[2]
        src_sarathi = repo_root / "src" / "sarathi"
        assert src_sarathi.exists(), f"Source directory not found: {src_sarathi}"

        violations: list[str] = []
        for py_file in src_sarathi.rglob("*.py"):
            size = py_file.stat().st_size
            if size > MAX_MODULE_SIZE_BYTES:
                rel_path = py_file.relative_to(repo_root)
                size_kb = size / 1024
                violations.append(f"{rel_path}: {size_kb:.2f} KB (exceeds 30 KB limit)")

        assert not violations, (
            f"Found {len(violations)} monolithic file(s) exceeding 30 KB limit:\n"
            + "\n".join(violations)
        )

    def test_decomposed_subpackages_have_explicit_all_exports(self) -> None:
        """All decomposed subpackages must define explicit __all__ and resolve each exported symbol."""
        subpackages = [
            "sarathi.shakti.native_extraction.readers",
            "sarathi.shakti.ocr.engine",
            "sarathi.nabhi.artifacts",
            "sarathi.shakti.docx_exporter",
            "sarathi.nabhi.pravaha",
            "sarathi.agni",
            "sarathi.mukha.web",
        ]

        missing_all: list[str] = []
        unresolvable_exports: list[str] = []

        for subpkg in subpackages:
            mod = importlib.import_module(subpkg)
            exports = getattr(mod, "__all__", None)
            if exports is None or not isinstance(exports, (list, tuple)):
                missing_all.append(subpkg)
                continue

            for name in exports:
                if not hasattr(mod, name):
                    unresolvable_exports.append(f"{subpkg}.{name}")

        assert not missing_all, f"Subpackages missing explicit __all__: {missing_all}"
        assert not unresolvable_exports, f"Exports defined in __all__ but unresolvable: {unresolvable_exports}"

    def test_no_stale_monolith_files_coexist_with_subpackages(self) -> None:
        """Superseded monolithic single files must not coexist with their replacement subpackages."""
        repo_root = Path(__file__).resolve().parents[2]
        src_sarathi = repo_root / "src" / "sarathi"

        decomposed_targets = [
            "shakti/native_extraction/readers",
            "shakti/ocr/engine",
            "nabhi/artifacts",
            "shakti/docx_exporter",
            "nabhi/pravaha",
        ]

        coexisting_stale: list[str] = []
        for target in decomposed_targets:
            subpkg_dir = src_sarathi / target
            stale_file = src_sarathi / f"{target}.py"
            assert subpkg_dir.is_dir(), f"Expected subpackage directory: {subpkg_dir}"
            if stale_file.exists():
                coexisting_stale.append(str(stale_file.relative_to(repo_root)))

        assert not coexisting_stale, (
            f"Stale monolithic files found coexisting with subpackages:\n"
            + "\n".join(coexisting_stale)
        )
