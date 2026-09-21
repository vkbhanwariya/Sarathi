"""Akshara-aware Devanagari Syllable Synthesis and Reordering for Roopa.

Handles Devanagari syllable structure:
- Consonant clusters: [Half consonants (C + virama)]* + Base consonant + [Nukta]?
- Pre-base matras (e.g. chhoti-i 'ि') moving after the full consonant cluster
- Postfix reph ('र्') moving to the logical start of the Akshara
- Subscript ra ('्र') and conjunct modifiers
- Canonical Unicode ordering: Reph -> Consonant Cluster -> Vowel Matra -> Anusvara/Chandrabindu/Visarga
"""

from __future__ import annotations

try:
    import regex as re

    _HAS_REGEX = True
except ImportError:
    import re  # type: ignore[no-redef]

    _HAS_REGEX = False

import functools

from sarathi.shakti.text.typography import synthesize_akshara_unicode

# Unicode Devanagari Character Ranges and Sets
DEVA_VIRAMA = "\u094d"  # ्
DEVA_NUKTA = "\u093c"  # ़
DEVA_REPH = "\u0930\u094d"  # र्

# Consonants: 0915 (क) to 0939 (ह), plus additional Hindi/Vedic consonants 0958-095F, 0979-097F
DEVA_CONSONANTS = "[\u0915-\u0939\u0958-\u095f\u0978-\u097f]"

# Independent Vowels: 0904-0914, 0960, 0961, 0972-0977
DEVA_INDEPENDENT_VOWELS = "[\u0904-\u0914\u0960\u0961\u0972-\u0977]"

# Dependent Vowel Signs (Matras): 093A, 093B, 093E-094C (excluding 093C Nukta and 093D Avagraha), 094E, 094F, 0955-0957, 0962, 0963
DEVA_MATRAS = "[\u093a\u093b\u093e-\u094c\u094e\u094f\u0955-\u0957\u0962\u0963]"

# Modifiers: Anusvara (0902), Visarga (0903), Chandrabindu (0901)
DEVA_MODIFIERS = "[\u0901-\u0903]"


def reorder_pre_base_matra_legacy(
    text: str,
    prefix_char: str,
    matra_unicode: str,
    consonant_chars_pattern: str,
) -> str:
    """Reorder a pre-base matra marker (e.g. Kruti 'f') across an arbitrary preceding/following consonant cluster.

    In legacy Remington typewriting, 'f' is typed immediately preceding the consonant cluster
    it qualifies:
    'fd' -> 'df' (कि)
    'fLFk' -> 'LFkf' (स्थि)
    'fnYyh' -> 'nfyYyh' (दिल्ली - 'f' moves past 'n', but NOT past 'Yy')
    'fO;' -> 'O;f' (व्यि)
    'fØ' -> 'Øf' (क्रि)
    """
    if not prefix_char or prefix_char not in text:
        return text

    pattern = re.compile(rf"{re.escape(prefix_char)}({consonant_chars_pattern})")
    # Single deterministic pass: move prefix_char directly after the qualified cluster
    return pattern.sub(r"\1" + prefix_char, text)


@functools.lru_cache(maxsize=8)
def _get_reph_patterns(reph_marker: str, reph_unicode: str) -> tuple[re.Pattern[str], re.Pattern[str], str]:
    marker_escaped = re.escape(reph_marker)
    akshara_core = (
        rf"(?:(?:{DEVA_CONSONANTS}{DEVA_NUKTA}?{DEVA_VIRAMA})*{DEVA_CONSONANTS}{DEVA_NUKTA}?|{DEVA_INDEPENDENT_VOWELS})"
    )
    p1 = re.compile(rf"({akshara_core})({DEVA_MATRAS}*)({DEVA_MODIFIERS}+){marker_escaped}")
    p2 = re.compile(rf"({akshara_core})({DEVA_MATRAS}*){marker_escaped}({DEVA_MODIFIERS}*)")
    repl = rf"{reph_unicode}\1\2\3"
    return p1, p2, repl


def reorder_reph_unicode(text: str, reph_marker: str, reph_unicode: str = DEVA_REPH) -> str:
    """Reorder a postfix reph marker to the logical start of its Devanagari Akshara.

    In legacy encoding, Reph was typed as a postfix character (e.g. 'Z' in KrutiDev):
    - 'dk;Z' mapped to 'कायZ' -> should be 'कार्य' ('र्' before 'य')
    - 'dksZ' mapped to 'कोZ' -> should be 'र्को' ('र्' before 'क', not between 'क' and 'ो')
    - 'dk;ks±' mapped to 'कायोZं' -> should be 'कार्यों'
    """
    if not reph_marker or reph_marker not in text:
        return text

    p1, p2, repl = _get_reph_patterns(reph_marker, reph_unicode)
    text = p1.sub(repl, text)
    text = p2.sub(repl, text)

    # Any remaining stray reph marker replaced with reph_unicode
    if reph_marker in text:
        text = text.replace(reph_marker, reph_unicode)

    return text

__all__ = [
    "reorder_pre_base_matra_legacy",
    "reorder_reph_unicode",
    "synthesize_akshara_unicode",
]
