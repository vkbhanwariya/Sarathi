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
import unicodedata

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

# Precompiled canonical Akshara synthesis regexes
_RE_VIRAMA_DEP_MATRA = re.compile(r"\u094d([\u0941-\u0944\u0947-\u094c])")
_RE_MODIFIERS_MATRAS = re.compile(rf"({DEVA_MODIFIERS})({DEVA_MATRAS})")
_RE_DOUBLE_VIRAMA = re.compile(rf"{DEVA_VIRAMA}+")
_RE_DOUBLE_VISARGA = re.compile(r"\u0903{2,}")
_RE_DOUBLE_DANDA = re.compile(r"\u0964{2,}")
_RE_STRAY_ZWNJ_BEFORE_MATRA = re.compile(rf"{DEVA_VIRAMA}[\u200c\u200d]+({DEVA_MATRAS})")
_RE_NUKTA_REORDER = re.compile(rf"({DEVA_CONSONANTS})({DEVA_MATRAS}|{DEVA_VIRAMA})({DEVA_NUKTA})")
_RE_DOUBLE_NUKTA = re.compile(rf"{DEVA_NUKTA}+")
_RE_DOUBLE_E_AI = re.compile(r"[\u0947\u0948]{2,}")
_RE_REMD_HUNG = re.compile(r"[\u0945\u0942]{2,}")
_RE_REMD_HUNG_PAIR = re.compile(r"\u0945\u0942|\u0942\u0945")
_RE_ORPHAN_CHHOTI_I = re.compile(rf"({DEVA_MATRAS})\u093f")
_RE_SPACED_MATRA = re.compile(rf"({DEVA_CONSONANTS}{DEVA_NUKTA}?)\s+({DEVA_MATRAS}|{DEVA_VIRAMA})")
_RE_SPACED_VIRAMA = re.compile(rf"({DEVA_CONSONANTS}{DEVA_NUKTA}?{DEVA_VIRAMA})\s+({DEVA_CONSONANTS})")


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
    text = _RE_VIRAMA_DEP_MATRA.sub(r"\1", text)
    # Fix misplaced modifiers: e.g. Anusvara before Matra (ंी -> ीं, ंा -> ां, ें -> ें)
    text = _RE_MODIFIERS_MATRAS.sub(r"\2\1", text)
    # Fix doubled virama
    text = _RE_DOUBLE_VIRAMA.sub(DEVA_VIRAMA, text)

    # Compose Devanagari 2-part vowel matras (both forward and reverse typing orders):
    # aa matra (\u093e) + e matra (\u0947) -> o matra (\u094b)
    # e matra (\u0947) + aa matra (\u093e) -> o matra (\u094b)
    # aa matra (\u093e) + ai matra (\u0948) -> au matra (\u094c)
    # ai matra (\u0948) + aa matra (\u093e) -> au matra (\u094c)
    # aa matra (\u093e) + candra-e (\u0945) -> candra-o (\u0949)
    # candra-e (\u0945) + aa matra (\u093e) -> candra-o (\u0949)
    text = text.replace("\u093e\u0947", "\u094b")
    text = text.replace("\u0947\u093e", "\u094b")
    text = text.replace("\u093e\u0948", "\u094c")
    text = text.replace("\u0948\u093e", "\u094c")
    text = text.replace("\u093e\u0945", "\u0949")
    text = text.replace("\u0945\u093e", "\u0949")

    # Compose Devanagari independent vowels typed as base vowel + dependent matras:
    # 'अ' (\u0905) + aa matra (\u093e) -> 'आ' (\u0906)
    # 'अ' (\u0905) + o matra (\u094b)  -> 'ओ' (\u0913)
    # 'अ' (\u0905) + au matra (\u094c) -> 'औ' (\u0914)
    # 'अ' (\u0905) + candra-e (\u0945) -> 'ऑ' (\u0911)
    # 'ए' (\u090f) + e matra (\u0947)  -> 'ऐ' (\u0910)
    text = text.replace("\u0905\u093e", "\u0906")
    text = text.replace("\u0905\u094b", "\u0913")
    text = text.replace("\u0905\u094c", "\u0914")
    text = text.replace("\u0905\u0945", "\u0911")
    text = text.replace("\u090f\u0947", "\u0910")

    # Reorder misplaced Nukta typed after dependent matra or virama to immediately follow consonant
    text = _RE_NUKTA_REORDER.sub(r"\1\3\2", text)
    text = _RE_DOUBLE_NUKTA.sub(DEVA_NUKTA, text)

    # Resolve conflicting consecutive e/ai matras (e.g. \u0947\u0948 -> \u0948)
    text = _RE_DOUBLE_E_AI.sub("\u0948", text)

    # Normalize Remington typewriter artifacts for 'हूँ' (candra-e \u0945 + badi-oo \u0942 combinations)
    text = _RE_REMD_HUNG.sub("\u0942\u0901", text)
    text = _RE_REMD_HUNG_PAIR.sub("\u0942\u0901", text)

    # Clean up orphan chhoti-i matra preceded by another dependent vowel matra
    text = _RE_ORPHAN_CHHOTI_I.sub(r"\1", text)

    # Normalize typewriter keyboard slips: doubled Visarga and doubled Danda
    text = _RE_DOUBLE_VISARGA.sub("\u0903", text)
    text = _RE_DOUBLE_DANDA.sub("\u0965", text)

    # Normalize stray ZWNJ before dependent vowel matras
    text = _RE_STRAY_ZWNJ_BEFORE_MATRA.sub(r"\1", text)

    # Repair inadvertent typist spacing between consonant/cluster and dependent vowel matra or virama
    text = _RE_SPACED_MATRA.sub(r"\1\2", text)
    # Repair spacing after virama before next consonant in split conjuncts
    text = _RE_SPACED_VIRAMA.sub(r"\1\2", text)

    # Standard NFC normalization
    return unicodedata.normalize("NFC", text)
