"""Deterministic AST-based generator for Vedas/CODE_INDEX.md.

Inspects all source files in src/sarathi, extracts module docstrings and public symbols,
determines hardware/compute characteristics, and formats a dense, tabular index.
Supports --check to enforce synchronization in CI and architecture test gates.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "sarathi"
INDEX_PATH = REPO_ROOT / "Vedas" / "CODE_INDEX.md"

SUBSYSTEM_ORDER = [
    ("agni", "Agni (Composition & Process Lifecycle)"),
    ("sankalpa", "Sankalpa (Contracts, Artifacts & Data Models)"),
    ("nabhi", "Nabhi (Planning, Execution & Artifact Quarantine)"),
    ("shakti", "Shakti (Capabilities & Provider Adapters)"),
    ("yantra", "Yantra (Device Scheduling & Hardware Concurrency)"),
    ("kavacha", "Kavacha (Security Boundaries & Privacy Enforcement)"),
    ("smriti", "Smriti (Deterministic Result Caching)"),
    ("darpana", "Darpana (Operational & Quality Telemetry)"),
    ("sutra", "Sutra (Configuration & Runtime Settings)"),
    ("mukha", "Mukha (UI, Presentation & Local Loopback Web)"),
    ("dosh", "Dosh (Error Taxonomy & Failure Classification)"),
]


def _classify_compute_profile(rel_path: str, source: str) -> str:
    lp = rel_path.lower()
    if "openvino" in lp or "ocr/engine" in lp:
        return "Primary iGPU (OpenVINO FP16)"
    if "translation/engine" in lp or "ctranslate2" in source:
        return "Multi-core CPU (Neural AVX2)"
    if "bank_statements" in lp or "delimited.py" in lp or "polars" in source:
        return "In-Memory / Polars Columnar"
    if "pdf" in lp or "pymupdf" in source or "rasterize" in lp:
        return "Native PDF Vector / PyMuPDF"
    if "font_conversion" in lp or "fonttools" in source:
        return "CPU (Font Engine / TTF)"
    if "artifacts" in lp or "atomic_io" in lp:
        return "Disk I/O (Atomic Staging)"
    if "web" in lp or "starlette" in source:
        return "Async Loopback ASGI (HTTP/SSE)"
    if "devices" in lp or "yantra" in lp:
        return "Hardware Scheduling"
    if "kavacha" in lp:
        return "Security / Path Containment"
    if "smriti" in lp:
        return "In-Memory / Disk Cache"
    if "darpana" in lp:
        return "Telemetry Telemetry Event Sink"
    if "sankalpa" in lp or "dosh" in lp:
        return "Pure Data Contracts (Zero I/O)"
    if "agni" in lp:
        return "Process Lifecycle Orchestrator"
    return "Standard Logic"


def _extract_file_info(file_path: Path) -> tuple[str, str, str]:
    """Parse one Python file using AST and return (docstring, symbols_str, compute_profile)."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except Exception:
        return "Unable to parse source", "", "Standard Logic"

    docstring = ast.get_docstring(tree) or ""
    first_line = ""
    for line in docstring.strip().splitlines():
        cleaned = line.strip()
        if cleaned:
            first_line = cleaned
            break
    if not first_line:
        first_line = "Module implementation"
    first_line = first_line.rstrip(".")

    classes: list[str] = []
    functions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                classes.append(f"`{node.name}`")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                functions.append(f"`{node.name}()`")

    symbols = classes + functions
    if not symbols:
        exported: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and not target.id.startswith("_") and target.id.isupper():
                        exported.append(f"`{target.id}`")
        symbols = exported[:3]

    symbols_str = ", ".join(symbols[:5]) if symbols else "—"
    rel_path = file_path.relative_to(SRC_ROOT).as_posix()
    compute = _classify_compute_profile(rel_path, source)

    return first_line, symbols_str, compute


def generate_index_markdown() -> str:
    """Generate the full content for Vedas/CODE_INDEX.md."""
    lines: list[str] = [
        "# Sarathi Code & Optimization Index",
        "",
        "> **Notice:** Generated automatically by `tools/generate_code_index.py`. Do not edit manually.",
        "> Run `uv run python tools/generate_code_index.py` to regenerate, or `--check` to verify.",
        "",
        "This dense index maps every source module in `src/sarathi/` to its primary responsibility, compute/hardware profile, and key exported symbols to enable targeted navigation and optimization without browsing entire trees.",
        "",
        "---",
        "",
    ]

    all_files = sorted(
        [p for p in SRC_ROOT.rglob("*.py") if p.name != "__init__.py" and "__pycache__" not in p.parts]
    )

    by_subsystem: dict[str, list[Path]] = {sub: [] for sub, _ in SUBSYSTEM_ORDER}
    root_files: list[Path] = []

    for file_path in all_files:
        rel = file_path.relative_to(SRC_ROOT)
        parts = rel.parts
        if len(parts) == 1:
            root_files.append(file_path)
        else:
            top = parts[0]
            if top in by_subsystem:
                by_subsystem[top].append(file_path)
            else:
                root_files.append(file_path)

    for sub_key, sub_title in SUBSYSTEM_ORDER:
        files = by_subsystem.get(sub_key, [])
        if not files:
            continue

        lines.append(f"## {sub_title}")
        lines.append("")
        lines.append("| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |")
        lines.append("| :--- | :--- | :--- | :--- |")

        for f in sorted(files, key=lambda p: p.as_posix()):
            rel = f.relative_to(SRC_ROOT / sub_key).as_posix()
            doc, symbols, compute = _extract_file_info(f)
            lines.append(f"| `{sub_key}/{rel}` | {doc} | **{compute}** | {symbols} |")

        lines.append("")

    if root_files:
        lines.append("## Root Application Entry Points")
        lines.append("")
        lines.append("| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for f in sorted(root_files, key=lambda p: p.as_posix()):
            rel = f.relative_to(SRC_ROOT).as_posix()
            doc, symbols, compute = _extract_file_info(f)
            lines.append(f"| `{rel}` | {doc} | **{compute}** | {symbols} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or check Vedas/CODE_INDEX.md.")
    parser.add_argument("--check", action="store_true", help="Verify if Vedas/CODE_INDEX.md matches generated index.")
    args = parser.parse_args()

    content = generate_index_markdown()

    if args.check:
        if not INDEX_PATH.is_file():
            sys.stderr.write(f"ERROR: {INDEX_PATH} does not exist. Run without --check to generate.\n")
            return 1
        existing = INDEX_PATH.read_text(encoding="utf-8")
        if existing != content:
            sys.stderr.write(
                f"ERROR: {INDEX_PATH} is out of date. Run 'uv run python tools/generate_code_index.py' to update.\n"
            )
            return 1
        print("PASS: Vedas/CODE_INDEX.md is in sync with codebase.")
        return 0

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(content, encoding="utf-8")
    print(f"Generated {INDEX_PATH.relative_to(REPO_ROOT)} successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
