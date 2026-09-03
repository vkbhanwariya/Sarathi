"""Evidence-based Legacy Font Detector for Roopa."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from sarathi.shakti.font_conversion.models import LegacyFontProfile
from sarathi.sutra import get_canonical_data_root

_CANONICAL_FONTS_DIR = get_canonical_data_root() / "fonts"

_KRUTI_SIGNATURES = (
    "[k",
    "vk",
    "vks",
    "vkS",
    "Fk",
    "/k",
    "Hk",
    "'k",
    ";Z",
    "jZ",
    ";k",
    "D;",
    "x~",
    "LVs",
    "cSa",
    ".k",
    "ñ",
    "ò",
    "ó",
    "ô",
    "õ",
    "ö",
    "÷",
    "ø",
    "ù",
    "ú",
    "û",
    "ü",
    "fdr",
    "fd",
    "fr",
    "fn",
    "fc",
    "f[",
    "fH",
    "fF",
    "fD",
    "fnY",
    "mRr",
)

_CHANAKYA_SIGNATURES = (
    "¥æ",
    "§Z",
    "§ü",
    "°ð",
    "ƒæ",
    "Ûæ",
    "ÿæ",
    "˜æ",
    "™æ",
    "æò",
    "æñ",
    "¥æò",
    "¥æð",
    "¥æñ",
    "¥ô",
    "¥õ",
)

_SHUSHA_SIGNATURES = (
    "aA",
    "bA",
    "cA",
    "dA",
    "uA",
    "vA",
    "wA",
    "pA",
    "sA",
    "tA",
    "rA",
    "yA",
)


def extract_ttf_font_family(ttf_bytes: bytes) -> str | None:
    """Parse TrueType SFNT binary header 'name' table to extract font family or full name."""
    if not isinstance(ttf_bytes, (bytes, bytearray)) or len(ttf_bytes) < 12:
        return None

    try:
        sfnt_version, num_tables = struct.unpack(">IH", ttf_bytes[:6])
        name_table_offset = None
        name_table_length = None

        for i in range(num_tables):
            offset = 12 + i * 16
            if offset + 16 > len(ttf_bytes):
                break
            tag, check_sum, offset_val, length = struct.unpack(">4sIII", ttf_bytes[offset : offset + 16])
            if tag == b"name":
                name_table_offset = offset_val
                name_table_length = length
                break

        if name_table_offset is None or name_table_offset + 6 > len(ttf_bytes):
            return None

        format_val, count, string_offset = struct.unpack(
            ">HHH", ttf_bytes[name_table_offset : name_table_offset + 6]
        )
        for i in range(count):
            rec_off = name_table_offset + 6 + i * 12
            if rec_off + 12 > len(ttf_bytes):
                break
            platform_id, encoding_id, language_id, name_id, length, offset = struct.unpack(
                ">HHHHHH", ttf_bytes[rec_off : rec_off + 12]
            )
            # Name ID 1 = Font Family, Name ID 4 = Full Name
            if name_id in (1, 4):
                start = name_table_offset + string_offset + offset
                end = start + length
                if end <= len(ttf_bytes):
                    raw_name = ttf_bytes[start:end]
                    try:
                        name_str = raw_name.decode(
                            "utf-16be" if platform_id in (0, 3) else "latin1", errors="ignore"
                        ).strip()
                        if name_str:
                            return name_str
                    except Exception:
                        pass
    except (struct.error, ValueError, IndexError):
        return None

    return None


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
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            continue
    return profiles


class LegacyFontDetector:
    """Detects legacy font encoding from text statistical properties and profile clues."""

    def __init__(self, fonts_dir: Path | None = None) -> None:
        self._profiles = load_font_profiles(fonts_dir)

    @classmethod
    def is_legacy_text(cls, text: str) -> bool:
        """Public evidence-based check whether text contains legacy Devanagari font signatures."""
        if not text or not text.strip():
            return False
        k_count = sum(1 for s in _KRUTI_SIGNATURES if s in text)
        c_count = sum(1 for s in _CHANAKYA_SIGNATURES if s in text)
        s_count = sum(1 for s in _SHUSHA_SIGNATURES if s in text)
        return (k_count >= 2) or (c_count >= 2) or (s_count >= 2)

    def is_legacy_font(self, text: str) -> bool:
        """Instance check whether text contains sufficient legacy font evidence."""
        return self.is_legacy_text(text)

    def detect(self, text: str, font_hint: str | None = None) -> tuple[str | None, float]:
        """Detect legacy font profile from actual text evidence.

        A font_hint narrows candidate profiles only; confirmed text evidence is strictly required.
        """
        if not text.strip():
            return None, 0.0

        # Evidence-based signature digraph detection in content
        k_matches = [s for s in _KRUTI_SIGNATURES if s in text]
        c_matches = [s for s in _CHANAKYA_SIGNATURES if s in text]
        s_matches = [s for s in _SHUSHA_SIGNATURES if s in text]

        has_evidence = (len(k_matches) >= 2) or (len(c_matches) >= 2) or (len(s_matches) >= 2)
        if not has_evidence:
            # Insufficient text evidence: do not authorize destructive conversion
            return None, 0.0

        max_matches = max(len(k_matches), len(c_matches), len(s_matches))
        conf = min(1.0, 0.5 + max_matches * 0.1)

        # If font_hint provided, validate against candidate profiles
        if font_hint:
            hint_lower = font_hint.lower().strip()
            for prof in self._profiles.values():
                if hint_lower == prof.profile_id.lower() or hint_lower in [a.lower() for a in prof.aliases]:
                    return prof.profile_id, conf
            # Incompatible hint provided despite legacy text: reject hint mismatch
            return None, 0.0

        # Without hint, select based on strongest signature match
        if len(c_matches) >= 2 and len(c_matches) >= len(k_matches) and len(c_matches) >= len(s_matches):
            return "chanakya010", conf
        elif len(s_matches) >= 2 and len(s_matches) >= len(k_matches):
            return "shusha010", conf
        elif len(k_matches) >= 2:
            return "krutidev010", conf

        return None, 0.0
