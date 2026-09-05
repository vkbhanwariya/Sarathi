"""Akshara-aware Devanagari Syllable Synthesis and Reordering for Roopa.

Handles Devanagari syllable structure:
- Consonant clusters: [Half consonants (C + virama)]* + Base consonant + [Nukta]?
- Pre-base matras (e.g. chhoti-i 'ि') moving after the full consonant cluster
- Postfix reph ('र्') moving to the logical start of the Akshara
- Subscript ra ('्र') and conjunct modifiers
- Canonical Unicode ordering: Reph -> Consonant Cluster -> Vowel Matra -> Anusvara/Chandrabindu/Visarga
"""

from __future__ import annotations

import re
import unicodedata

# Unicode Devanagari Character Ranges and Sets
DEVA_VIRAMA = "\u094d"  # ्
DEVA_NUKTA = "\u093c"   # ़
DEVA_REPH = "\u0930\u094d"  # र्

# Consonants: 0915 (क) to 0939 (ह), plus additional Hindi/Vedic consonants 0958-095F, 0979-097F
DEVA_CONSONANTS = (
    "[\u0915-\u0939\u0958-\u095f\u0978-\u097f]"
)

# Independent Vowels: 0904-0914, 0960, 0961, 0972-0977
DEVA_INDEPENDENT_VOWELS = (
    "[\u0904-\u0914\u0960\u0961\u0972-\u0977]"
)

# Dependent Vowel Signs (Matras): 093A-094C, 094E, 094F, 0955-0957, 0962, 0963
DEVA_MATRAS = (
    "[\u093a-\u094c\u094e\u094f\u0955-\u0957\u0962\u0963]"
)

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

    pattern = re.compile(
        rf"{re.escape(prefix_char)}({consonant_chars_pattern})"
    )
    # Single deterministic pass: move prefix_char directly after the qualified cluster
    return pattern.sub(r"\1" + prefix_char, text)


def reorder_reph_unicode(text: str, reph_marker: str, reph_unicode: str = DEVA_REPH) -> str:
    """Reorder a postfix reph marker to the logical start of its Devanagari Akshara.

    In legacy encoding, Reph was typed as a postfix character (e.g. 'Z' in KrutiDev):
    - 'dk;Z' mapped to 'कायZ' -> should be 'कार्य' ('र्' before 'य')
    - 'dksZ' mapped to 'कोZ' -> should be 'र्को' ('र्' before 'क', not between 'क' and 'ो')
    - 'dk;ks±' mapped to 'कायोZं' -> should be 'कार्यों'
    """
    if not reph_marker or reph_marker not in text:
        return text

    marker_escaped = re.escape(reph_marker)

    # Akshara pattern: consonant cluster OR independent vowel
    akshara_core = rf"(?:(?:{DEVA_CONSONANTS}{DEVA_NUKTA}?{DEVA_VIRAMA})*{DEVA_CONSONANTS}{DEVA_NUKTA}?|{DEVA_INDEPENDENT_VOWELS})"

    # 1. Match core + matras + modifiers + reph_marker
    p1 = re.compile(
        rf"({akshara_core})({DEVA_MATRAS}*)({DEVA_MODIFIERS}+){marker_escaped}"
    )
    text = p1.sub(rf"{reph_unicode}\1\2\3", text)

    # 2. Match core + matras + reph_marker + modifiers
    p2 = re.compile(
        rf"({akshara_core})({DEVA_MATRAS}*){marker_escaped}({DEVA_MODIFIERS}*)"
    )
    text = p2.sub(rf"{reph_unicode}\1\2\3", text)

    # 3. Any remaining stray reph marker replaced with reph_unicode
    if reph_marker in text:
        text = text.replace(reph_marker, reph_unicode)

    return text


def synthesize_akshara_unicode(text: str) -> str:
    """Ensure canonical Unicode ordering inside every Devanagari Akshara.

    Canonical sequence:
    1. Consonant / Cluster
    2. Nukta (़)
    3. Virama (्) (between consonants)
    4. Dependent Vowel Matras (ा, ि, ी, ु, ू, ृ, े, ै, ो, ौ)
    5. Anusvara (ं), Chandrabindu (ँ), Visarga (ः)
    """
    # Fix misplaced matra before virama: e.g. ि् -> ्ि
    text = text.replace("\u093f\u094d", "\u094d\u093f")
    # Resolve invalid virama immediately followed by a dependent vowel matra:
    # On typewriters, typists often typed the half-consonant key followed by a matra (e.g. ख् + े -> खे, ख् + ु -> खु).
    text = re.sub(r"\u094d([\u0941-\u0944\u0947-\u094c])", r"\1", text)
    # Fix misplaced modifiers: e.g. Anusvara before Matra (ंी -> ीं, ंा -> ां, ें -> ें)
    text = re.sub(
        rf"({DEVA_MODIFIERS})({DEVA_MATRAS})",
        r"\2\1",
        text,
    )
    # Fix doubled virama
    text = re.sub(rf"{DEVA_VIRAMA}+", DEVA_VIRAMA, text)

    # Compose Devanagari 2-part vowel matras:
    # aa matra (\u093e) + e matra (\u0947) -> o matra (\u094b)
    # aa matra (\u093e) + ai matra (\u0948) -> au matra (\u094c)
    text = text.replace("\u093e\u0947", "\u094b")
    text = text.replace("\u093e\u0948", "\u094c")

    # Resolve conflicting consecutive e/ai matras (e.g. \u0947\u0948 -> \u0948)
    text = re.sub(r"[\u0947\u0948]{2,}", "\u0948", text)

    # Normalize Remington typewriter artifacts for 'हूँ' (candra-e \u0945 + badi-oo \u0942 combinations)
    text = re.sub(r"[\u0945\u0942]{2,}", "\u0942\u0901", text)
    text = re.sub(r"\u0945\u0942|\u0942\u0945", "\u0942\u0901", text)

    # Clean up orphan chhoti-i matra preceded by another dependent vowel matra
    text = re.sub(rf"({DEVA_MATRAS})\u093f", r"\1", text)

    # Standard NFC normalization
    return unicodedata.normalize("NFC", text)
