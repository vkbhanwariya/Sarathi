"""Domain Glossary and Terminology Manager for Translation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.translation.models import TranslationDirection
from sarathi.sutra import get_canonical_data_root

_CANONICAL_GLOSSARY_DIR = get_canonical_data_root() / "translation"


class GlossaryStore:
    """Loads and applies static domain glossaries."""

    def __init__(self, glossary_dir: Path | None = None, strict: bool = False) -> None:
        self._dir = glossary_dir.resolve() if glossary_dir is not None else _CANONICAL_GLOSSARY_DIR
        self._strict = strict
        self._collisions: list[dict[str, str]] = []
        self._entries: dict[TranslationDirection, dict[str, str]] = {
            TranslationDirection.HI_TO_EN: {},
            TranslationDirection.EN_TO_HI: {},
        }
        self._load()

    @property
    def collisions(self) -> tuple[dict[str, str], ...]:
        """Return all recorded source-term collisions across loaded glossaries."""
        return tuple(self._collisions)

    def _load(self) -> None:
        # 1. Base canonical glossary.yaml if present
        yaml_file = self._dir / "glossary.yaml"
        if yaml_file.exists():
            try:
                raw_data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                self._parse_raw_data(raw_data, yaml_file.name)
            except (OSError, yaml.YAMLError) as exc:
                raise DoshError(
                    code=FailureCode.INVALID_CONFIGURATION,
                    message=f"Failed to parse translation glossary YAML: {yaml_file.name}",
                ) from exc

        # 2. Domain-specific dictionary files in glossaries/
        glossaries_dir = self._dir / "glossaries"
        if glossaries_dir.exists() and glossaries_dir.is_dir():
            for gfile in sorted(glossaries_dir.iterdir()):
                if gfile.is_file() and gfile.suffix.lower() in (".json", ".yaml", ".yml"):
                    try:
                        content = gfile.read_text(encoding="utf-8")
                        if gfile.suffix.lower() == ".json":
                            parsed = json.loads(content)
                        else:
                            parsed = yaml.safe_load(content)
                        self._parse_raw_data(parsed, gfile.name)
                    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
                        raise DoshError(
                            code=FailureCode.INVALID_CONFIGURATION,
                            message=f"Failed to parse domain glossary file: {gfile.name}",
                        ) from exc

    def _parse_raw_data(self, raw_data: Any, filename: str) -> None:
        if raw_data is None:
            return

        if isinstance(raw_data, dict):
            if "entries" in raw_data:
                if not isinstance(raw_data["entries"], list):
                    raise DoshError(
                        code=FailureCode.INVALID_CONFIGURATION,
                        message=f"Glossary 'entries' field must be a list: {filename}",
                    )
                for item in raw_data["entries"]:
                    if isinstance(item, dict):
                        self._add_entry(item)
            else:
                # Key-value domain dictionary: English -> Hindi
                for k, v in raw_data.items():
                    if isinstance(k, str) and isinstance(v, str):
                        clean_k = k.strip()
                        clean_v = v.strip()
                        if clean_k and clean_v:
                            self._add_term(TranslationDirection.EN_TO_HI, clean_k, clean_v)
                            # Split composite synonyms (e.g. "शब्द 1 / शब्द 2") so each maps back to English
                            synonyms = [s.strip() for s in re.split(r"[/,]", clean_v) if s.strip()]
                            for syn in synonyms:
                                self._add_term(TranslationDirection.HI_TO_EN, syn, clean_k)
        elif isinstance(raw_data, list):
            for item in raw_data:
                if isinstance(item, dict):
                    self._add_entry(item)
        else:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Translation glossary root must be a mapping or list: {filename}",
            )

    def _add_term(self, direction: TranslationDirection, source: str, target: str) -> None:
        table = self._entries[direction]
        if source in table and table[source] != target:
            coll = {
                "direction": direction.value,
                "source": source,
                "existing_target": table[source],
                "conflicting_target": target,
            }
            self._collisions.append(coll)
            if self._strict:
                raise DoshError(
                    code=FailureCode.INVALID_CONFIGURATION,
                    message=(
                        f"Translation glossary conflict for '{source}' in direction '{direction.value}': "
                        f"existing '{table[source]}' vs conflicting '{target}'"
                    ),
                )
            return
        table[source] = target

    def _add_entry(self, raw: dict[str, str]) -> None:
        src = raw.get("source", "").strip()
        tgt = raw.get("target", "").strip()
        d_str = raw.get("direction", "hi-en").strip().lower()
        if d_str in ("hi-en", "hi_to_en", "hi_en"):
            direction = TranslationDirection.HI_TO_EN
        elif d_str in ("en-hi", "en_to_hi", "en_hi"):
            direction = TranslationDirection.EN_TO_HI
        else:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"Invalid translation glossary direction '{d_str}'. Must be 'hi-en' or 'en-hi'.",
            )
        if src and tgt:
            self._add_term(direction, src, tgt)

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
