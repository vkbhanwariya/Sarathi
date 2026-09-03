"""Akshara-aware Legacy Font to Unicode Converter for Roopa."""

from __future__ import annotations

import re
import tomllib
import unicodedata
from pathlib import Path

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.font_conversion.detector import load_font_profiles

_CANONICAL_FONTS_DIR = Path(__file__).resolve().parents[4] / "data" / "fonts"
_CANONICAL_ANUBHAVA_PATH = Path(__file__).resolve().parents[4] / "data" / "font_conversion" / "anubhava.toml"
_KRUTI_CONSONANTS = "(?:[DPRFYOCLHEUI]|x~)?(?:\\[k|\\?k|Fk|/k|Hk|'k|\\\"k|\\.k|[dxptTVBMrnuc;jyo\\?ghKs])"
_REPH_DEVANAGARI_RE = re.compile(r"([ऀ-ॿ])Z")


def _load_anubhava_corrections(anubhava_path: Path | None = None) -> dict[str, dict[str, str]]:
    """Load and return approved corrections directly from capability-owned anubhava.toml."""
    path = (anubhava_path or _CANONICAL_ANUBHAVA_PATH).resolve()
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message=f"Failed to parse font conversion Anubhava TOML: {path.name}",
        ) from exc
    corrections: dict[str, dict[str, str]] = {}
    for item in data.get("corrections", []):
        if isinstance(item, dict) and item.get("verified", False):
            pid = item.get("profile_id", "generic")
            src = item.get("source", "")
            tgt = item.get("target", "")
            if src and tgt:
                corrections.setdefault(pid, {})[src] = tgt
    return corrections


class FontConverter:
    """Converts legacy font text into canonical Unicode Devanagari."""

    def __init__(self, fonts_dir: Path | None = None, anubhava_path: Path | None = None) -> None:
        self._profiles = load_font_profiles(fonts_dir)
        self._anubhava_corrections = _load_anubhava_corrections(anubhava_path)

    def convert(self, text: str, profile_id: str) -> str:
        """Apply legacy-to-Unicode mapping, pre-base matra reordering, and NFC normalization."""
        profile = self._profiles.get(profile_id)
        if profile is None:
            return text

        # 1. Apply verified Anubhava corrections first
        corrections = self._anubhava_corrections.get(profile_id, {})
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
            text = _REPH_DEVANAGARI_RE.sub(lambda m: f"{reph_unicode}{m.group(1)}", text)

        # 5. Post-corrections
        for src, tgt in profile.post_corrections:
            text = text.replace(src, tgt)

        # 5b. Typewriter artifact post-normalization
        # Number comma fix: Remington digits typed with ']' or 'ए' between digits: e.g. 30]000 -> 30,000
        text = re.sub(r"(?<=\d)[\]ए](?=\d)", ",", text)
        # Rupee shorthand prefix: ःपये / :पये -> रुपये
        text = re.sub(r"(?:[:ः]पये)", "रुपये", text)
        # Typist reph/matra inversion: कायार्लय -> कार्यालय
        text = text.replace("कायार्लय", "कार्यालय")

        # 6. NFC Unicode normalization
        return unicodedata.normalize("NFC", text)

    def convert_to_legacy(self, text: str, target_profile_id: str = "krutidev010") -> str:
        """Convert standard Unicode Devanagari text into legacy font encoding (KrutiDev or DevLys)."""
        pid = target_profile_id.lower().strip()
        profile = self._profiles.get(pid)
        if profile is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Requested target font profile is not supported or loaded: {target_profile_id!r}",
            )

        norm_text = unicodedata.normalize("NFC", text)

        # 1. Handle pre-base choti-i matra 'ि': in Unicode it follows consonant, in Kruti it precedes
        norm_text = re.sub(r"((?:[क-ह]्)*[क-ह])ि", r"f\1", norm_text)

        # 2. Handle reph 'र्': in Unicode it precedes consonant, in Kruti/DevLys 'Z' follows
        norm_text = re.sub(r"र्((?:[क-ह]्)*[क-ह](?:[ाीुूेैोौ]|ं|ँ)?)", r"\1Z", norm_text)

        # 3. Build reverse mapping (Unicode -> Legacy), longest Unicode matches first
        reverse_map: dict[str, str] = {}
        for leg_k, uni_v in profile.mappings.items():
            if uni_v and uni_v not in reverse_map:
                reverse_map[uni_v] = leg_k

        # Also add prefix if not present
        for leg_k, uni_v in profile.prefixes.items():
            if uni_v and uni_v not in reverse_map:
                reverse_map[uni_v] = leg_k

        sorted_uni = sorted(reverse_map.keys(), key=len, reverse=True)
        if sorted_uni:
            pattern = re.compile("|".join(re.escape(u) for u in sorted_uni))
            norm_text = pattern.sub(lambda m: reverse_map.get(m.group(0), m.group(0)), norm_text)

        return norm_text
