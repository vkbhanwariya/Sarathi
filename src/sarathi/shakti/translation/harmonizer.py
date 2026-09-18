"""On-Device Statutory Terminology Harmonizer for Sarathi Translation.

Provides post-translation normalization and alignment of colloquial, informal, or
inconsistent cloud-generated translations into canonical statutory terms (e.g.
PMLA, Banking & Financial, Criminal Law, and Judicial designations).
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from sarathi.shakti.translation.models import TranslationDirection

# Devanagari character class excluding sentence/abbreviation punctuation (danda U+0964, double danda U+0965, etc.)
_DEV_WORD_CHARS = r"\w\u0900-\u0963\u0966-\u096f\u0971-\u097f"
_L_DEV = f"(?<![{_DEV_WORD_CHARS}])"
_R_DEV = f"(?![{_DEV_WORD_CHARS}])"

# Canonical statutory synonyms for English -> Hindi translation
# Maps variant regex pattern to canonical statutory term
_CANONICAL_HI_VARIANTS: Sequence[tuple[re.Pattern[str], str]] = (
    # PMLA Sec 2(1)(u) - Proceeds of Crime
    (
        re.compile(rf"{_L_DEV}(?:अपराध\s+(?:की\s+कमाई|से\s+प्राप्त\s+(?:आय|लाभ)|से\s+अर्जित\s+आय)|जुर्म\s+का\s+पैसा){_R_DEV}"),
        "अपराध के आगम",
    ),
    # PMLA Sec 2(1)(wa) - Reporting Entity
    (
        re.compile(rf"{_L_DEV}(?:रिपोर्टिंग\s+(?:संस्था|निकाय|इकाई)|सूचना\s+(?:देने\s+वाली\s+संस्था|प्रदाता\s+इकाई)){_R_DEV}"),
        "रिपोर्टकर्ता इकाई",
    ),
    # PMLA Sec 12AA - Enhanced Due Diligence
    (
        re.compile(rf"{_L_DEV}(?:उन्नत|अतिरिक्त|विस्तृत|संवर्धित)\s+सम्यक\s+तत्परता{_R_DEV}"),
        "वर्धित सम्यक तत्परता",
    ),
    # PMLA Sec 2(1)(fa) - Beneficial Owner
    (
        re.compile(rf"{_L_DEV}(?:वास्तविक\s+लाभार्थी|हितकारी\s+स्वामी|लाभकारी\s+स्वामी){_R_DEV}"),
        "हिताधिकारी स्वामी",
    ),
    # PMLA Sec 6 - Adjudicating Authority
    (
        re.compile(rf"{_L_DEV}(?:न्यायनिर्णायक\s+प्राधिकरण|न्याय\s*निर्णयन\s+प्राधिकारी|अधिनिर्णय\s+प्राधिकारी){_R_DEV}"),
        "न्यायनिर्णायक प्राधिकारी",
    ),
    # PMLA Sec 25 - Appellate Tribunal
    (
        re.compile(rf"{_L_DEV}(?:अपीलीय\s+(?:अधिकरण|न्यायाधिकरण)|अपील\s+ट्रिब्यूनल){_R_DEV}"),
        "अपील अधिकरण",
    ),
    # PMLA Sec 43 - Special Court
    (
        re.compile(rf"{_L_DEV}(?:विशेष\s+अदालत|स्पेशल\s+कोर्ट){_R_DEV}"),
        "विशेष न्यायालय",
    ),
    # Enforcement Directorate
    (
        re.compile(rf"{_L_DEV}(?:प्रवर्तन\s+निदेशालय\s*\(ईडी\)|प्रवर्तन\s+विभाग){_R_DEV}"),
        "प्रवर्तन निदेशालय",
    ),
    # Benami Transaction
    (
        re.compile(rf"{_L_DEV}(?:बेनामी\s+(?:लेनदेन|सौदा)){_R_DEV}"),
        "बेनामी संव्यवहार",
    ),
    # Money Laundering
    (
        re.compile(rf"{_L_DEV}(?:मनी\s+लॉन्ड्रिंग|काले\s+धन\s+को\s+सफेद\s+करना){_R_DEV}"),
        "धन-शोधन",
    ),
)

# Canonical statutory synonyms for Hindi -> English translation
_CANONICAL_EN_VARIANTS: Sequence[tuple[re.Pattern[str], str]] = (
    (
        re.compile(r"\b(?:Crime\s+Income|Proceeds\s+of\s+(?:Offence|Crime\s+Money|illegal\s+activity))\b", re.IGNORECASE),
        "Proceeds of Crime",
    ),
    (
        re.compile(r"\b(?:Reporting\s+(?:Agency|Institution|Organization))\b", re.IGNORECASE),
        "Reporting Entity",
    ),
    (
        re.compile(r"\b(?:Adjudication\s+Authority|Adjudicating\s+Body)\b", re.IGNORECASE),
        "Adjudicating Authority",
    ),
    (
        re.compile(r"\b(?:Appellate\s+Court(?=\s+under\s+PMLA)|Appellate\s+Body)\b", re.IGNORECASE),
        "Appellate Tribunal",
    ),
    (
        re.compile(r"\b(?:Anti[- ]Money\s+Laundering\s+Act|PMLA\s+Act)\b", re.IGNORECASE),
        "Prevention of Money Laundering Act, 2002",
    ),
)


class GlossaryHarmonizer:
    """On-device statutory terminology normalizer for translated legal texts."""

    def __init__(self, custom_variants: Mapping[str, str] | None = None) -> None:
        self._custom_variants = dict(custom_variants) if custom_variants else {}
        self._compiled_custom: list[tuple[re.Pattern[str], str]] = []
        if self._custom_variants:
            for variant, canonical in self._custom_variants.items():
                stripped = variant.strip()
                if stripped:
                    is_devanagari = any("\u0900" <= c <= "\u097f" for c in stripped)
                    char_class = _DEV_WORD_CHARS if is_devanagari else r"\w"
                    flags = re.IGNORECASE if any(ord(c) < 128 and c.isalpha() for c in stripped) else 0
                    prefix = f"(?<![{char_class}])" if (stripped[0].isalnum() or ("\u0900" <= stripped[0] <= "\u097f")) else ""
                    suffix = f"(?![{char_class}])" if (stripped[-1].isalnum() or ("\u0900" <= stripped[-1] <= "\u097f")) else ""
                    pat = re.compile(f"{prefix}{re.escape(stripped)}{suffix}", flags)
                    self._compiled_custom.append((pat, canonical.strip()))

    def harmonize(self, text: str, direction: TranslationDirection | str) -> str:
        """Harmonize translated text by replacing colloquial variations with statutory terms."""
        if not text or not text.strip():
            return text

        dir_enum = (
            direction
            if isinstance(direction, TranslationDirection)
            else (
                TranslationDirection.EN_TO_HI
                if str(direction).lower() in ("en-hi", "en_to_hi", "en_hi", "english->hindi")
                else TranslationDirection.HI_TO_EN
            )
        )

        result = text

        # 1. Apply canonical statutory pattern replacements
        if dir_enum == TranslationDirection.EN_TO_HI:
            for pattern, canonical in _CANONICAL_HI_VARIANTS:
                result = pattern.sub(canonical, result)
        else:
            for pattern, canonical in _CANONICAL_EN_VARIANTS:
                result = pattern.sub(canonical, result)

        # 2. Apply any custom configured variant mappings
        for pattern, canonical in self._compiled_custom:
            result = pattern.sub(canonical, result)

        return result


__all__ = ["GlossaryHarmonizer"]
