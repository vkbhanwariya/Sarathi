"""Standard Indian Court Orders, Statutory Boilerplate, and Section Formulas Matcher.

Provides zero-latency, high-precision translation for recurring judicial boilerplate
and statutory formulas without invoking neural sequence-to-sequence models.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from sarathi.shakti.translation.models import TranslationDirection
from sarathi.sutra import get_canonical_data_root

logger = logging.getLogger(__name__)

_CANONICAL_TRANSLATION_DIR = get_canonical_data_root() / "translation"


class CourtTemplateMatcher:
    """Zero-latency matcher for standard Indian court orders and statutory sections."""

    def __init__(self, data_root: Path | None = None) -> None:
        self._data_root = (data_root or _CANONICAL_TRANSLATION_DIR).resolve()
        self._boilerplate_en_to_hi: dict[str, str] = {}
        self._boilerplate_hi_to_en: dict[str, str] = {}
        self._patterns_en_to_hi: list[tuple[re.Pattern[str], str]] = []
        self._patterns_hi_to_en: list[tuple[re.Pattern[str], str]] = []
        self._load()

    def _load(self) -> None:
        template_file = self._data_root / "glossaries" / "court_templates.json"
        if not template_file.is_file():
            return

        try:
            data = json.loads(template_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load court templates from %s: %s", template_file, exc)
            return

        if not isinstance(data, dict):
            return

        for k, v in data.get("boilerplate_en_to_hi", {}).items():
            if isinstance(k, str) and isinstance(v, str):
                self._boilerplate_en_to_hi[self._normalize_key(k, is_english=True)] = v.strip()

        for k, v in data.get("boilerplate_hi_to_en", {}).items():
            if isinstance(k, str) and isinstance(v, str):
                self._boilerplate_hi_to_en[self._normalize_key(k, is_english=False)] = v.strip()

        for item in data.get("statutory_patterns_en_to_hi", []):
            if isinstance(item, dict) and "pattern" in item and "template" in item:
                try:
                    pat = re.compile(item["pattern"], re.IGNORECASE)
                    self._patterns_en_to_hi.append((pat, str(item["template"])))
                except re.error as err:
                    logger.warning("Invalid regex in court_templates: %s (%s)", item["pattern"], err)

        for item in data.get("statutory_patterns_hi_to_en", []):
            if isinstance(item, dict) and "pattern" in item and "template" in item:
                try:
                    pat = re.compile(item["pattern"])
                    self._patterns_hi_to_en.append((pat, str(item["template"])))
                except re.error as err:
                    logger.warning("Invalid regex in court_templates: %s (%s)", item["pattern"], err)

    @staticmethod
    def _normalize_key(text: str, is_english: bool) -> str:
        norm = " ".join(text.strip().rstrip(".।!?").split())
        return norm.lower() if is_english else norm

    def match_sentence(self, sentence: str, direction: TranslationDirection) -> str | None:
        """Attempt to match a sentence against judicial boilerplate or statutory formulas.

        Returns the exact translated sentence if matched, or None if neural translation is required.
        """
        raw_stripped = sentence.strip()
        if not raw_stripped:
            return None

        # Check trailing punctuation
        has_period = raw_stripped.endswith((".", "।"))

        if direction == TranslationDirection.EN_TO_HI:
            norm_key = self._normalize_key(raw_stripped, is_english=True)
            target = self._boilerplate_en_to_hi.get(norm_key)
            if target is not None:
                return f"{target}।" if has_period else target

            # Check statutory regex patterns
            clean_s = raw_stripped.rstrip(".।!?").strip()
            for pat, tmpl in self._patterns_en_to_hi:
                if pat.search(clean_s):
                    replaced = pat.sub(tmpl, clean_s).strip()
                    return f"{replaced}।" if has_period else replaced

        elif direction == TranslationDirection.HI_TO_EN:
            norm_key = self._normalize_key(raw_stripped, is_english=False)
            target = self._boilerplate_hi_to_en.get(norm_key)
            if target is not None:
                return f"{target}." if has_period else target

            # Check statutory regex patterns
            clean_s = raw_stripped.rstrip(".।!?").strip()
            for pat, tmpl in self._patterns_hi_to_en:
                if pat.search(clean_s):
                    replaced = pat.sub(tmpl, clean_s).strip()
                    return f"{replaced}." if has_period else replaced

        return None


__all__ = ["CourtTemplateMatcher"]
