"""Akshara-aware Legacy Font to Unicode Converter for Roopa."""

from __future__ import annotations

from pathlib import Path
import re
import unicodedata

from sarathi.shakti.font_conversion.anubhava import AnubhavaStore
from sarathi.shakti.font_conversion.detector import load_font_profiles
from sarathi.shakti.font_conversion.models import LegacyFontProfile

_CANONICAL_FONTS_DIR = Path(__file__).resolve().parents[4] / "data" / "fonts"
_KRUTI_CONSONANTS = ('(?:[DPRFYOCLHEUI]|x~)?(?:\\[k|\\?k|Fk|/k|Hk|\'k|\\"k|\\.k|[dxptTVBMrnuc;jyo\\?ghKs])')


class FontConverter:
    """Converts legacy font text into canonical Unicode Devanagari."""

    def __init__(self, fonts_dir: Path | None = None, anubhava: AnubhavaStore | None = None) -> None:
        self._profiles = load_font_profiles(fonts_dir)
        self._anubhava = anubhava or AnubhavaStore()

    def convert(self, text: str, profile_id: str) -> str:
        """Apply legacy-to-Unicode mapping, pre-base matra reordering, and NFC normalization."""
        profile = self._profiles.get(profile_id)
        if profile is None:
            return text

        # 1. Apply verified Anubhava corrections first
        corrections = self._anubhava.get_corrections(profile_id)
        for src, tgt in corrections.items():
            text = text.replace(src, tgt)

        # 2. Pre-reordering for 'f' (choti-i matra pre-base reordering in Kruti Dev)
        text = re.sub(rf"f({_KRUTI_CONSONANTS})", r"\1f", text)

        # 3. Apply Multi-char and Single-char mappings (sorted by key length descending)
        sorted_keys = sorted(profile.mappings.keys(), key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(k) for k in sorted_keys))

        def _map_match(m: re.Match) -> str:
            return profile.mappings.get(m.group(0), m.group(0))

        text = pattern.sub(_map_match, text)

        # 4. Handle Postfix Reph ('Z' -> 'र्' moving before immediately preceding Devanagari character)
        reph_char = profile.postfix_reph
        reph_unicode = profile.reph_unicode
        if reph_char in text:
            text = re.sub(rf"([\u0900-\u097F]){re.escape(reph_char)}", lambda m: f"{reph_unicode}{m.group(1)}", text)

        # 5. Post-corrections
        for src, tgt in profile.post_corrections:
            text = text.replace(src, tgt)

        # 6. NFC Unicode normalization
        return unicodedata.normalize("NFC", text)
