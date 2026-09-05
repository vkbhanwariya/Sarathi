"""Evidence-based Legacy Font Detection for Shakti.

Provides neutral, high-precision detection of legacy non-Unicode Indian language
font encodings (such as KrutiDev, DevLys, Chanakya, and Shusha) from text signatures
and character distributions.
"""

from __future__ import annotations

from pathlib import Path

_KRUTI_SIGNATURES: tuple[str, ...] = (
    "[k", "vk", "vks", "vkS", "Fk", "/k", "Hk", "'k", ";Z", "jZ",
    ";k", "D;", "x~", "LVs", "cSa", ".k", "ñ", "ò", "ó", "ô",
    "õ", "ö", "÷", "ø", "ù", "ú", "û", "ü", "fdr", "fd",
    "fr", "fn", "fc", "f[", "fH", "fF", "fD", "fnY", "mRr",
)

_CHANAKYA_SIGNATURES: tuple[str, ...] = (
    "¥æ", "§Z", "§ü", "°ð", "ƒæ", "Ûæ", "ÿæ", "˜æ", "™æ", "æò",
    "æñ", "¥æò", "¥æð", "¥æñ", "¥ô", "¥õ",
)

_SHUSHA_SIGNATURES: tuple[str, ...] = (
    "aA", "bA", "cA", "dA", "uA", "vA", "wA", "pA", "sA", "tA",
    "rA", "yA",
)

_KNOWN_MODERN_FONTS: frozenset[str] = frozenset({
    "arial", "calibri", "timesnewroman", "times", "cambria", "georgia",
    "verdana", "tahoma", "couriernew", "courier", "segoeui", "segoe",
    "helvetica", "trebuchetms", "trebuchet", "bookmanoldstyle", "bookman",
    "garamond", "centurygothic", "mangal", "nirmalaui", "nirmala",
    "aparajita", "kokila", "utsaah", "gautami", "latha", "shruti",
})


def is_legacy_text(text: str) -> bool:
    """Public evidence-backed check whether text contains legacy Devanagari font signatures."""
    if not text or not text.strip():
        return False
    k_count = sum(1 for s in _KRUTI_SIGNATURES if s in text)
    c_count = sum(1 for s in _CHANAKYA_SIGNATURES if s in text)
    s_count = sum(1 for s in _SHUSHA_SIGNATURES if s in text)
    return (k_count >= 2) or (c_count >= 2) or (s_count >= 2)


class LegacyFontDetector:
    """Base detector for identifying legacy font encodings from text signatures."""

    def __init__(self, fonts_dir: Path | None = None) -> None:
        self._fonts_dir = fonts_dir

    @classmethod
    def is_legacy_text(cls, text: str) -> bool:
        """Evidence-backed check whether text contains legacy Devanagari font signatures."""
        return is_legacy_text(text)

    def is_legacy_font(self, text: str) -> bool:
        """Instance check whether text contains sufficient legacy font evidence."""
        return is_legacy_text(text)
