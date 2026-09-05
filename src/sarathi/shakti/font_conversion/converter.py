"""Akshara-aware Legacy Font to Unicode Converter for Roopa."""

from __future__ import annotations

import re
import tomllib
import unicodedata
from pathlib import Path

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.font_conversion.akshara import (
    reorder_pre_base_matra_legacy,
    reorder_reph_unicode,
    synthesize_akshara_unicode,
)
from sarathi.shakti.font_conversion.detector import load_font_profiles
from sarathi.sutra import get_canonical_data_root

_CANONICAL_FONTS_DIR = get_canonical_data_root() / "fonts"
_CANONICAL_ANUBHAVA_PATH = get_canonical_data_root() / "font_conversion" / "anubhava.toml"

# Kruti/Remington legacy cluster regex pattern:
# Captures optional half-consonants (D, P, R, F, Y, O, L, C, H, E, U, I, x~, etc.) + base consonant + optional sub-ra ('z')
# In Remington: uppercase letters D, P, R, F, Y, O, L, C, H, E, U, I are half-consonants (क्, च्, त्, थ्, ल्, व्, स्, ब्, भ्, म्, न्, प्)
# Lowercase letters d, x, p, t, T, V, B, M, r, n, u, c, ;, j, y, o, ?, g, h, K, s, e are base consonants (क, ग, च, ज, झ, ट, ठ, ड, त, द, न, ब, य, र, ल, व, ?, घ, ह, ज्ञ, स, म)
_KRUTI_HALF_CONSONANTS = r"(?:[DPRFYOCLHUI\xb6\xd9]|E(?!$)|x~|\{|\&|J~)"
_KRUTI_BASE_CONSONANTS = r"(?:\[k|\?k|Fk|/k|Hk|'k|\"k|\.k|\{k|\u2019k|\xd9k|[ldixptTVBMrnuc;jyo\?ghKsQeJK\xe7\xe4\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xfb\xfc\xfd\xfe=\}\xd8\)])"
_KRUTI_CONSONANT_CLUSTER = rf"(?:{_KRUTI_HALF_CONSONANTS})*{_KRUTI_BASE_CONSONANTS}z?"


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
        """Apply legacy-to-Unicode mapping, profile-specific pre-base matra reordering, and Akshara synthesis."""
        profile = self._profiles.get(profile_id)
        if profile is None:
            return text

        # 1. Apply verified Anubhava corrections: generic first, profile-specific second
        generic_corrections = self._anubhava_corrections.get("generic", {})
        for src, tgt in generic_corrections.items():
            text = text.replace(src, tgt)

        profile_corrections = self._anubhava_corrections.get(profile_id, {})
        for src, tgt in profile_corrections.items():
            text = text.replace(src, tgt)

        # 2. Profile-specific pre-base matra reordering (e.g. 'f' in KrutiDev/DevLys)
        # ONLY execute if the active profile defines this prefix!
        if profile.family in ("krutidev", "devlys"):
            for pfx, matra_uni in profile.prefixes.items():
                if pfx in text:
                    text = reorder_pre_base_matra_legacy(
                        text,
                        prefix_char=pfx,
                        matra_unicode=matra_uni,
                        consonant_chars_pattern=_KRUTI_CONSONANT_CLUSTER,
                    )
        elif profile.family == "chanakya":
            for pfx in profile.prefixes.keys():
                if pfx in text:
                    text = re.sub(rf"{re.escape(pfx)}([^\s])", r"\1" + pfx, text)
        elif profile.family == "shusha":
            if "D" in profile.prefixes and "D" in text:
                text = re.sub(r"D([a-z])", r"\1D", text)
        elif profile.family == "shivaji":
            if "C" in profile.prefixes and "C" in text:
                text = re.sub(r"C([a-z0-9])", r"\1C", text)

        # 3. Apply Multi-char and Single-char mappings using precompiled forward transducer
        if profile.compiled_forward_regex is not None:
            text = profile.compiled_forward_regex.sub(
                lambda m: profile.mappings.get(m.group(0), m.group(0)), text
            )

        # 4. Handle Postfix Reph at logical Akshara level
        reph_char = profile.postfix_reph
        reph_uni = profile.reph_unicode
        if reph_char and reph_char in text:
            text = reorder_reph_unicode(text, reph_marker=reph_char, reph_unicode=reph_uni)

        # 5. Post-corrections declared in profile
        for src, tgt in profile.post_corrections:
            text = text.replace(src, tgt)

        # 5b. Family corrections (e.g. typewriter artifact corrections declared in profile)
        for src, tgt in profile.family_corrections:
            text = text.replace(src, tgt)

        # 6. Akshara Unicode synthesis and canonical NFC normalization
        return synthesize_akshara_unicode(text)

    def convert_to_legacy(self, text: str, target_profile_id: str = "krutidev010") -> str:
        """Convert standard Unicode Devanagari text into legacy font encoding using precompiled reverse transducers."""
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

        # 3. Apply precompiled reverse mapping (Unicode -> Legacy)
        if profile.compiled_reverse_regex is not None:
            rev_map = profile.compiled_reverse_map
            norm_text = profile.compiled_reverse_regex.sub(
                lambda m: rev_map.get(m.group(0), m.group(0)), norm_text
            )

        return norm_text
