"""Evidence-based Legacy Font Detector for Roopa."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sarathi.shakti.font_conversion.models import LegacyFontProfile

_CANONICAL_FONTS_DIR = Path(__file__).resolve().parents[4] / "data" / "fonts"

_KRUTI_SIGNATURES = (
    "[k", "vk", "vks", "vkS", "Fk", "/k", "Hk", "'k", ";Z", "jZ", ";k", "D;",
    "x~", "LVs", "cSa", ".k", "ñ", "ò", "ó", "ô", "õ", "ö", "÷", "ø", "ù", "ú",
    "û", "ü", "fdr", "fd", "fr", "fn", "fc", "f["
)


def load_font_profiles(fonts_dir: Path | None = None) -> dict[str, LegacyFontProfile]:
    """Load all validated font mapping profiles from data/fonts/."""
    target_dir = fonts_dir.resolve() if fonts_dir is not None else _CANONICAL_FONTS_DIR
    profiles = {}
    if not target_dir.exists():
        return profiles

    for json_file in target_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "profile_id" in data:
                profile = LegacyFontProfile(
                    profile_id=data["profile_id"],
                    family=data.get("family", data["profile_id"]),
                    name=data.get("name", data["profile_id"]),
                    aliases=tuple(data.get("aliases", ())),
                    prefixes=data.get("prefixes", {}),
                    postfix_reph=data.get("postfix_reph", "Z"),
                    reph_unicode=data.get("reph_unicode", "र्"),
                    mappings=data.get("mappings", {}),
                    post_corrections=tuple(tuple(c) for c in data.get("post_corrections", ())),
                )
                profiles[profile.profile_id] = profile
        except Exception:
            continue
    return profiles


class LegacyFontDetector:
    """Detects legacy font encoding from text statistical properties and profile clues."""

    def __init__(self, fonts_dir: Path | None = None) -> None:
        self._profiles = load_font_profiles(fonts_dir)

    def detect(self, text: str, font_hint: str | None = None) -> tuple[str | None, float]:
        """Detect legacy font profile from font_hint or text distribution."""
        if font_hint:
            hint_lower = font_hint.lower().strip()
            for prof in self._profiles.values():
                if hint_lower == prof.profile_id.lower() or hint_lower in prof.aliases:
                    return prof.profile_id, 1.0

        if not text.strip():
            return None, 0.0

        # Evidence-based signature digraph detection
        matches = [s for s in _KRUTI_SIGNATURES if s in text]
        if len(matches) >= 2 and "krutidev010" in self._profiles:
            conf = min(1.0, 0.5 + len(matches) * 0.1)
            return "krutidev010", conf

        return None, 0.0
