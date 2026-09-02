"""Anubhava Approved Corrections Loader and Revalidator for Roopa."""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any

_CANONICAL_ANUBHAVA = Path(__file__).resolve().parents[4] / "data" / "font_conversion" / "anubhava.toml"


class AnubhavaStore:
    """Loads approved domain corrections and re-validates them before use."""

    def __init__(self, anubhava_path: Path | None = None) -> None:
        self._path = anubhava_path.resolve() if anubhava_path is not None else _CANONICAL_ANUBHAVA
        self._corrections: dict[str, dict[str, str]] = self._load()

    def _load(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        try:
            data = tomllib.loads(self._path.read_text(encoding="utf-8"))
            corrections = {}
            for item in data.get("corrections", []):
                if isinstance(item, dict) and item.get("verified", False):
                    pid = item.get("profile_id", "generic")
                    src = item.get("source", "")
                    tgt = item.get("target", "")
                    if src and tgt:
                        corrections.setdefault(pid, {})[src] = tgt
            return corrections
        except Exception:
            return {}

    def get_corrections(self, profile_id: str) -> dict[str, str]:
        """Return verified corrections for a given profile."""
        return self._corrections.get(profile_id, {})
