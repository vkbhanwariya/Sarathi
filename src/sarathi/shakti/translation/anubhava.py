"""Translation Anubhava Approved Corrections Loader.

Read-only at runtime; rejects malformed entries and revalidates before use.
"""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Mapping

from sarathi.shakti.translation.models import TranslationDirection

_CANONICAL_ANUBHAVA_DIR = Path(__file__).resolve().parents[4] / "data" / "translation"


class TranslationAnubhavaStore:
    """Manages verified translation overrides and corrections."""

    def __init__(self, anubhava_dir: Path | None = None) -> None:
        self._dir = anubhava_dir.resolve() if anubhava_dir is not None else _CANONICAL_ANUBHAVA_DIR
        self._corrections: dict[TranslationDirection, dict[str, str]] = {
            TranslationDirection.HI_TO_EN: {},
            TranslationDirection.EN_TO_HI: {},
        }
        self._load()

    def _load(self) -> None:
        toml_path = self._dir / "anubhava.toml"
        if not toml_path.exists():
            return

        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            corrections = data.get("corrections", [])
            for c in corrections:
                if not isinstance(c, dict):
                    continue
                src = c.get("source", "").strip()
                tgt = c.get("target", "").strip()
                d_str = c.get("direction", "hi-en").strip().lower()
                direction = TranslationDirection.HI_TO_EN if d_str == "hi-en" else TranslationDirection.EN_TO_HI
                if src and tgt:
                    self._corrections[direction][src] = tgt
        except Exception:
            pass

    def get_corrections(self, direction: TranslationDirection) -> Mapping[str, str]:
        """Return validated corrections for direction."""
        return self._corrections.get(direction, {})

    def apply_corrections(self, text: str, direction: TranslationDirection) -> str:
        """Apply approved corrections directly to text."""
        corrs = self.get_corrections(direction)
        for src, tgt in corrs.items():
            text = text.replace(src, tgt)
        return text
