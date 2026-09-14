"""Phonetic Transliteration Transducer from Romanized Hindi (Hinglish) to Unicode Devanagari.

Provides deterministic phonetic transliteration for mixed-script administrative documents,
supporting standard ITRANS, common Hinglish typing conventions, and common administrative vocabularies.
"""

from __future__ import annotations

import re
import unicodedata

# Common administrative Hinglish terms with exact canonical Unicode mappings
_CANONICAL_ADMIN_LEXICON: dict[str, str] = {
    "kripya": "कृपया",
    "kripaya": "कृपया",
    "dhanyawad": "धन्यवाद",
    "dhanyavad": "धन्यवाद",
    "namaste": "नमस्ते",
    "namaskar": "नमस्कार",
    "aavedan": "आवेदन",
    "aavedak": "आवेदक",
    "patra": "पत्र",
    "pradan": "प्रदान",
    "karein": "करें",
    "karna": "करना",
    "kiye": "किए",
    "sarkar": "सरकार",
    "adhikari": "अधिकारी",
    "aadesh": "आदेश",
    "suchana": "सूचना",
    "vivaran": "विवरण",
    "praman": "प्रमाण",
    "shasan": "शासन",
    "karyalay": "कार्यालय",
    "prathmik": "प्राथमिक",
    "madhyamik": "माध्यमिक",
    "dinank": "दिनांक",
    "yojana": "योजना",
    "sahayata": "सहायता",
    "bhavan": "भवन",
    "vibhag": "विभाग",
    "prativedan": "प्रतिवेदन",
    "niyam": "नियम",
    "anurodh": "अनुरोध",
    "aapka": "आपका",
    "hamara": "हमारा",
    "shriman": "श्रीमान",
    "mahoday": "महोदय",
    "parinam": "परिणाम",
    "prapt": "प्राप्त",
    "bharat": "भारत",
}

_INITIAL_VOWELS: list[tuple[str, str]] = [
    ("aa", "आ"),
    ("a", "अ"),
    ("ee", "ई"),
    ("ii", "ई"),
    ("i", "इ"),
    ("oo", "ऊ"),
    ("uu", "ऊ"),
    ("u", "उ"),
    ("ri", "ऋ"),
    ("ai", "ऐ"),
    ("ei", "ऐ"),
    ("e", "ए"),
    ("au", "औ"),
    ("ou", "औ"),
    ("o", "ओ"),
]

_DEPENDENT_MATRAS: list[tuple[str, str]] = [
    ("aa", "ा"),
    ("a", ""),
    ("ee", "ी"),
    ("ii", "ी"),
    ("i", "ि"),
    ("oo", "ू"),
    ("uu", "ू"),
    ("u", "ु"),
    ("ri", "ृ"),
    ("ai", "ै"),
    ("ei", "ै"),
    ("e", "े"),
    ("au", "ौ"),
    ("ou", "ौ"),
    ("o", "ो"),
]

_CONSONANTS: list[tuple[str, str]] = [
    ("chh", "छ"),
    ("ch", "च"),
    ("kh", "ख"),
    ("gh", "घ"),
    ("jh", "झ"),
    ("th", "थ"),
    ("dh", "ध"),
    ("ph", "फ"),
    ("bh", "भ"),
    ("shh", "ष"),
    ("sh", "श"),
    ("ksh", "क्ष"),
    ("tr", "त्र"),
    ("gy", "ज्ञ"),
    ("k", "क"),
    ("g", "ग"),
    ("j", "ज"),
    ("t", "त"),
    ("d", "द"),
    ("n", "न"),
    ("p", "प"),
    ("b", "ब"),
    ("m", "म"),
    ("y", "य"),
    ("r", "र"),
    ("l", "ल"),
    ("v", "व"),
    ("w", "व"),
    ("s", "स"),
    ("h", "ह"),
    ("f", "फ़"),
    ("z", "ज़"),
    ("q", "क़"),
]

_WORD_SPLIT_RE = re.compile(r"([A-Za-z]+|[^A-Za-z]+)")


def is_romanized_hindi(text: str) -> bool:
    """Return True if text contains significant Romanized Hindi (Hinglish) diagnostic words."""
    if not text or not text.strip():
        return False
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
    if not words:
        return False
    matched = words & _CANONICAL_ADMIN_LEXICON.keys()
    return len(matched) > 0 and (len(matched) >= 2 or len(words) <= 3)


def transliterate_word(word: str) -> str:
    """Transliterate a single Romanized Hindi word into Unicode Devanagari."""
    w = word.lower().strip()
    if not w:
        return word

    # 1. Check exact canonical administrative vocabulary
    if w in _CANONICAL_ADMIN_LEXICON:
        return _CANONICAL_ADMIN_LEXICON[w]

    # 2. Phonetic token-based finite state transliteration
    i = 0
    n = len(w)
    res: list[str] = []

    while i < n:
        if i == 0:
            v_match = None
            for rom, uni in _INITIAL_VOWELS:
                if w.startswith(rom, i):
                    v_match = (rom, uni)
                    break
            if v_match:
                res.append(v_match[1])
                i += len(v_match[0])
                continue

        c_match = None
        for rom, uni in _CONSONANTS:
            if w.startswith(rom, i):
                c_match = (rom, uni)
                break

        if c_match:
            i += len(c_match[0])
            m_match = None
            for rom, uni in _DEPENDENT_MATRAS:
                if w.startswith(rom, i):
                    m_match = (rom, uni)
                    break

            if m_match:
                res.append(c_match[1] + m_match[1])
                i += len(m_match[0])
            else:
                if i >= n:
                    # Final consonant: standard inherent 'a' termination
                    res.append(c_match[1])
                else:
                    # Non-final consonant with no following vowel: halant cluster
                    res.append(c_match[1] + "्")
            continue

        # Non-matched Latin letter: preserve as-is
        res.append(w[i])
        i += 1

    transliterated = "".join(res)
    return unicodedata.normalize("NFC", transliterated)


def transliterate_romanized_hindi(text: str) -> str:
    """Transliterate Romanized Hindi text into normalized Unicode Devanagari, preserving whitespace and symbols."""
    if not text:
        return text

    parts = _WORD_SPLIT_RE.findall(text)
    out: list[str] = []
    for part in parts:
        if part.isalpha():
            out.append(transliterate_word(part))
        else:
            out.append(part)

    return "".join(out)


__all__ = [
    "is_romanized_hindi",
    "transliterate_romanized_hindi",
    "transliterate_word",
]
