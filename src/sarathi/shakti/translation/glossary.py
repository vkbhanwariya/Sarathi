"""Domain Glossary and Terminology Manager for Translation."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Mapping
import yaml

from sarathi.dosh import DoshError, FailureCode
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
            raw_data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Failed to parse translation glossary YAML: {yaml_file.name}",
            ) from exc

        if raw_data is None:
            return

        if isinstance(raw_data, dict):
            entries = raw_data.get("entries", [])
            if not isinstance(entries, list):
                raise DoshError(
                    code=FailureCode.INVALID_CONFIGURATION,
                    message=f"Translation glossary 'entries' field must be a list: {yaml_file.name}",
                )
        elif isinstance(raw_data, list):
            entries = raw_data
        else:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Translation glossary YAML root must be a mapping or list: {yaml_file.name}",
            )

        for item in entries:
            if isinstance(item, dict):
                self._add_entry(item)

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
