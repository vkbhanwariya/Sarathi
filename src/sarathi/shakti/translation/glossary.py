"""Domain Glossary and Terminology Manager for Translation."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Mapping

from sarathi.shakti.translation.models import GlossaryEntry, TranslationDirection

_CANONICAL_GLOSSARY_DIR = Path(__file__).resolve().parents[4] / "data" / "translation"


class GlossaryStore:
    """Loads and applies static domain glossaries."""

    def __init__(self, glossary_dir: Path | None = None) -> None:
        self._dir = glossary_dir.resolve() if glossary_dir is not None else _CANONICAL_GLOSSARY_DIR
        self._entries: dict[TranslationDirection, dict[str, str]] = {
            TranslationDirection.HI_TO_EN: {},
            TranslationDirection.EN_TO_HI: {},
        }
        self._load()

    def _load(self) -> None:
        yaml_file = self._dir / "glossary.yaml"
        if not yaml_file.exists():
            return

        try:
            content = yaml_file.read_text(encoding="utf-8")
            # Parse YAML lines simply
            current_entry: dict[str, str] = {}
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("- source:"):
                    if "source" in current_entry and "target" in current_entry:
                        self._add_entry(current_entry)
                    current_entry = {"source": line.split(":", 1)[1].strip().strip('"').strip("'")}
                elif line.startswith("target:"):
                    current_entry["target"] = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("direction:"):
                    current_entry["direction"] = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("domain:"):
                    current_entry["domain"] = line.split(":", 1)[1].strip().strip('"').strip("'")
            if "source" in current_entry and "target" in current_entry:
                self._add_entry(current_entry)
        except Exception:
            pass

    def _add_entry(self, raw: dict[str, str]) -> None:
        src = raw.get("source", "").strip()
        tgt = raw.get("target", "").strip()
        d_str = raw.get("direction", "hi-en").strip().lower()
        direction = TranslationDirection.HI_TO_EN if d_str == "hi-en" else TranslationDirection.EN_TO_HI
        if src and tgt:
            self._entries[direction][src] = tgt

    def get_terms(self, direction: TranslationDirection) -> Mapping[str, str]:
        """Return the dictionary of source -> target glossary terms for direction."""
        return self._entries.get(direction, {})

    def apply_glossary(self, text: str, direction: TranslationDirection) -> str:
        """Apply glossary substitutions sorted by length descending."""
        terms = self.get_terms(direction)
        if not terms:
            return text

        sorted_keys = sorted(terms.keys(), key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(k) for k in sorted_keys))

        def _repl(m: re.Match) -> str:
            return terms.get(m.group(0), m.group(0))

        return pattern.sub(_repl, text)
