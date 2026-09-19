"""Architecture test ensuring that lazy-exporting packages resolve all exports in __all__ and __dir__."""

from __future__ import annotations

import importlib

import pytest

LAZY_PACKAGES = [
    "sarathi.shakti.font_conversion",
    "sarathi.shakti.translation",
    "sarathi.shakti.bank_statements",
    "sarathi.shakti.ocr",
]


@pytest.mark.architecture
@pytest.mark.parametrize("pkg_name", LAZY_PACKAGES)
def test_lazy_exports_resolve_and_dir_in_sync(pkg_name: str) -> None:
    pkg = importlib.import_module(pkg_name)
    assert hasattr(pkg, "__all__"), f"{pkg_name} missing __all__"
    all_exports = set(pkg.__all__)
    dir_names = set(dir(pkg))

    # Every item in __all__ must resolve and be present in dir()
    for name in all_exports:
        resolved = getattr(pkg, name)
        assert resolved is not None, f"{name} in {pkg_name}.__all__ resolved to None"
        assert name in dir_names, f"{name} in {pkg_name}.__all__ is missing from dir({pkg_name})"

    # If the package has a lazy export map or __getattr__, check for unmapped or non-__all__ exports
    lazy_map = getattr(pkg, "_LAZY_EXPORTS", None)
    if lazy_map is not None:
        for mapped_name in lazy_map:
            assert mapped_name in all_exports, f"Lazy export {mapped_name!r} missing from {pkg_name}.__all__"


@pytest.mark.architecture
def test_lazy_packages_do_not_import_heavy_dependencies() -> None:
    import subprocess
    import sys

    script = """
import sys
import sarathi.shakti.ocr
import sarathi.shakti.translation
import sarathi.shakti.bank_statements
import sarathi.shakti.font_conversion

assert "rapidocr_onnxruntime" not in sys.modules, "rapidocr_onnxruntime imported eagerly"
assert "ctranslate2" not in sys.modules, "ctranslate2 imported eagerly"
assert "polars" not in sys.modules, "polars imported eagerly"
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, f"Subprocess failed:\n{result.stderr}"
