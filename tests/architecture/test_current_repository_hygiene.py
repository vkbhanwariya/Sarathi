"""Keep the active Sarathi repository free of superseded product-generation references."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
CURRENT_DOCS = {
    "README.md",
    "Architecture.md",
    "Capabilities.md",
    "Cleanup_Optimization_Plan.md",
    "Configuration.md",
    "Development.md",
    "Formats.md",
    "Mukha_Transport.md",
    "Troubleshooting.md",
}
STALE_DOC_NAME_PARTS = (
    "Sarathi_" + "V1",
    "Sarathi_" + "V2",
    "Sarathi_" + "V3",
    "Sarathi-" + "V1",
    "Sarathi-" + "V2",
    "Sarathi-" + "V3",
)
SEARCH_ROOTS = ("src", "tests", "scripts", "config", "data", "ui", "Vedas")
STALE_CONTENT = re.compile(r"(?:Sarathi[ _-]?V[12](?:\b|_)|(?<![A-Za-z0-9])V[12](?![A-Za-z0-9]))")


def _iter_text_files():
    for root_name in SEARCH_ROOTS:
        base = ROOT / root_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve() == SELF:
                continue
            if any(part in {"node_modules", "dist", ".venv", "__pycache__"} for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            yield path, text
    for name in ("README.md", "AGENTS.md"):
        path = ROOT / name
        yield path, path.read_text(encoding="utf-8")


@pytest.mark.architecture
def test_active_repository_has_no_stale_product_generation_references() -> None:
    matches = []
    for path, text in _iter_text_files():
        for line_number, line in enumerate(text.splitlines(), start=1):
            if STALE_CONTENT.search(line):
                matches.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")
    assert not matches, "Stale product-generation references remain:\n" + "\n".join(matches)


@pytest.mark.architecture
def test_vedas_has_only_current_document_names() -> None:
    vedas = ROOT / "Vedas"
    stale_names = [path.name for path in vedas.iterdir() if any(part in path.name for part in STALE_DOC_NAME_PARTS)]
    assert not stale_names, f"Version-prefixed Vedas files are obsolete: {stale_names}"
    existing = {path.name for path in vedas.glob("*.md")}
    assert CURRENT_DOCS.issubset(existing)
