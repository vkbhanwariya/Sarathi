"""Architecture test verifying all third-party imports in src/sarathi are declared in pyproject.toml."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

# Known package name to top-level import name mapping
KNOWN_IMPORT_MAPPING: dict[str, set[str]] = {
    "beautifulsoup4": {"bs4"},
    "charset-normalizer": {"charset_normalizer"},
    "defusedxml": {"defusedxml"},
    "openpyxl": {"openpyxl"},
    "polars": {"polars"},
    "pymupdf": {"pymupdf", "fitz"},
    "pymupdf-layout": {"fitz_layout"},
    "python-calamine": {"calamine", "python_calamine"},
    "pyyaml": {"yaml"},
    "starlette": {"starlette"},
    "uvicorn": {"uvicorn"},
    "xlrd": {"xlrd"},
    "numpy": {"numpy"},
    "opencv-python-headless": {"cv2"},
    "opencv-python": {"cv2"},
    "openvino": {"openvino", "openvino_telemetry"},
    "pillow": {"PIL"},
    "rapidocr": {"rapidocr", "rapidocr_onnxruntime"},
    "ctranslate2": {"ctranslate2"},
    "sentencepiece": {"sentencepiece"},
    "fonttools": {"fontTools"},
    "rapidfuzz": {"rapidfuzz"},
    "regex": {"regex"},
    "httpx": {"httpx"},
}


def _extract_package_canonical_name(spec: str) -> str:
    """Strip version specifiers and extras from requirement string."""
    name = re.split(r"[<>=~;!\s]", spec)[0].strip()
    name = re.sub(r"\[.*\]", "", name).strip().lower()
    return name


def _get_declared_import_names(pyproject_path: Path) -> set[str]:
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    deps = list(project.get("dependencies", []))
    for group_deps in project.get("optional-dependencies", {}).values():
        deps.extend(group_deps)

    allowed_imports: set[str] = set()
    for dep in deps:
        pkg_name = _extract_package_canonical_name(dep)
        if pkg_name in KNOWN_IMPORT_MAPPING:
            allowed_imports.update(KNOWN_IMPORT_MAPPING[pkg_name])
        else:
            # Default: replace '-' with '_'
            allowed_imports.add(pkg_name.replace("-", "_"))

    return allowed_imports


def _find_top_level_imports(file_path: Path) -> set[str]:
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        source = f.read()

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return set()

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                imports.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                top = node.module.split(".")[0]
                imports.add(top)
    return imports


@pytest.mark.architecture
def test_all_imports_declared_in_pyproject() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent
    pyproject_path = repo_root / "pyproject.toml"
    src_dir = repo_root / "src" / "sarathi"

    assert pyproject_path.is_file(), f"Missing pyproject.toml at {pyproject_path}"
    assert src_dir.is_dir(), f"Missing src/sarathi at {src_dir}"

    declared_imports = _get_declared_import_names(pyproject_path)
    stdlib_modules = set(sys.stdlib_module_names) | {"_winreg", "winreg", "nt"}

    undeclared_by_file: dict[str, set[str]] = {}
    for py_file in src_dir.rglob("*.py"):
        rel_path = py_file.relative_to(repo_root).as_posix()
        file_imports = _find_top_level_imports(py_file)
        undeclared = set()
        for imp in file_imports:
            if imp in stdlib_modules or imp == "sarathi" or imp.startswith("_"):
                continue
            if imp not in declared_imports:
                undeclared.add(imp)
        if undeclared:
            undeclared_by_file[rel_path] = undeclared

    assert not undeclared_by_file, "Found undeclared third-party imports in src/sarathi:\n" + "\n".join(
        f"  {f}: {sorted(imps)}" for f, imps in sorted(undeclared_by_file.items())
    )
