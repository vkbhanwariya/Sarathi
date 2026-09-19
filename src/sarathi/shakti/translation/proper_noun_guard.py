"""Proper-Noun Legal Transliteration Guard for NMT Translation.

Protects Indian names, kinship designations, and revenue/administrative localities
from semantic translation hallucinations (e.g. 'सूर्यभान' -> 'Sun Light') by
combining honorific/kinship regex detection with phonetic transliteration and
placeholder isolation.
"""

from __future__ import annotations

import re

# Consonant transliterations
_CONSONANTS = {
    "क": "k",
    "ख": "kh",
    "ग": "g",
    "घ": "gh",
    "ङ": "ng",
    "च": "ch",
    "छ": "chh",
    "ज": "j",
    "झ": "jh",
    "ञ": "ny",
    "ट": "t",
    "ठ": "th",
    "ड": "d",
    "ढ": "dh",
    "ण": "n",
    "त": "t",
    "थ": "th",
    "द": "d",
    "ध": "dh",
    "न": "n",
    "प": "p",
    "फ": "ph",
    "ब": "b",
    "भ": "bh",
    "म": "m",
    "य": "y",
    "र": "r",
    "ल": "l",
    "व": "v",
    "श": "sh",
    "ष": "sh",
    "स": "s",
    "ह": "h",
    "क़": "q",
    "ख़": "kh",
    "ग़": "gh",
    "ज़": "z",
    "ड़": "r",
    "ढ़": "rh",
    "फ़": "f",
}

# Vowel / Matra transliterations
_VOWELS = {
    "अ": "a",
    "आ": "a",
    "इ": "i",
    "ई": "ee",
    "उ": "u",
    "ऊ": "oo",
    "ऋ": "ri",
    "ए": "e",
    "ऐ": "ai",
    "ओ": "o",
    "औ": "au",
}

_MATRAS = {
    "ा": "a",
    "ि": "i",
    "ी": "i",
    "ु": "u",
    "ू": "u",
    "ृ": "ri",
    "े": "e",
    "ै": "ai",
    "ो": "o",
    "ौ": "au",
    "ं": "n",
    "ँ": "n",
}

# Regex prefix patterns for Indian proper nouns
_HONORIFIC_PREFIXES = r"(?:श्री|श्रीमती|सुश्री|डॉ[०.]|पं[०.]|कु[०.]|मोहम्मद|चौधरी|ठाकुर|सैयद)"
_KINSHIP_PREFIXES = r"(?:पुत्र|पुत्री|सुपुत्र|सुपुत्री|आत्मज|पत्नी|बेवा)"
_ADMIN_PREFIXES = r"(?:ग्राम|तहसील|जिला|थाना|मौजा|खसरा|खाता)"
_RESERVED_FOLLOWING = r"(?:पुत्र|पुत्री|सुपुत्र|सुपुत्री|आत्मज|पत्नी|बेवा|निवासी|ग्राम|तहसील|जिला|थाना|मौजा|खसरा|खाता|\d|।|$)"

_PROPER_NOUN_RE = re.compile(
    rf"({_HONORIFIC_PREFIXES}|{_KINSHIP_PREFIXES}|{_ADMIN_PREFIXES})\s+([क-ह][\u0900-\u094f\u0950-\u097f]+(?:\s+(?!{_RESERVED_FOLLOWING})[क-ह][\u0900-\u094f\u0950-\u097f]+){{0,2}})"
)


def transliterate_devanagari_to_latin(text: str) -> str:
    """Phonetically transliterate Devanagari proper names into Romanized Latin."""
    words = text.split()
    trans_words: list[str] = []

    for word in words:
        clean_w = word.rstrip("।.,;:")
        if clean_w.endswith("पुर") and len(clean_w) > 3:
            # Common town/village suffix 'pur'
            stem = clean_w[:-3]
            stem_trans = transliterate_devanagari_to_latin(stem)
            trans_words.append(f"{stem_trans}pur")
            continue

        chars = list(clean_w)
        out: list[str] = []
        n = len(chars)
        i = 0
        while i < n:
            c = chars[i]
            if c in _VOWELS:
                out.append(_VOWELS[c])
                i += 1
            elif c in _CONSONANTS:
                base = _CONSONANTS[c]
                # Check next character
                if i + 1 < n:
                    nxt = chars[i + 1]
                    if nxt == "्":  # Virama (half-letter)
                        out.append(base)
                        i += 2
                    elif nxt in _MATRAS:
                        out.append(base + _MATRAS[nxt])
                        i += 2
                    elif i + 2 < n and chars[i + 2] == "्":
                        # Followed by consonant cluster -> schwa deletion
                        out.append(base)
                        i += 1
                    else:
                        # Followed by another consonant -> implicit 'a'
                        out.append(base + "a")
                        i += 1
                else:
                    # Word-final consonant (Hindi schwa deletion)
                    out.append(base)
                    i += 1
            elif c in _MATRAS:
                out.append(_MATRAS[c])
                i += 1
            elif c == "्":
                i += 1
            else:
                out.append(c)
                i += 1

        trans_word = "".join(out).capitalize()
        trans_words.append(trans_word)

    return " ".join(trans_words)


class ProperNounGuard:
    """Shields proper nouns with transliterated placeholders during NMT translation."""

    def __init__(self) -> None:
        self._pattern = _PROPER_NOUN_RE

    def protect(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        """Detect proper nouns, transliterate, and substitute with opaque placeholders.

        Returns:
            tuple[protected_text, list[tuple[placeholder, transliterated_name]]]
        """
        placeholders: list[tuple[str, str]] = []
        counter = 1

        def _replace_match(m: re.Match[str]) -> str:
            nonlocal counter
            raw_name = m.group(2).strip().rstrip("।.,;:")
            # Transliterate raw Devanagari name to Latin
            trans_name = transliterate_devanagari_to_latin(raw_name)
            ph = f"__NAME_{counter}__"
            placeholders.append((ph, trans_name))
            counter += 1
            # Return prefix + placeholder
            return f"{m.group(1)} {ph}"

        # Run replacement
        protected_text = self._pattern.sub(_replace_match, text)

        return protected_text, placeholders

    def restore(self, translated_text: str, placeholders: list[tuple[str, str]]) -> str:
        """Substitute opaque placeholders with the transliterated Latin proper names."""
        restored = translated_text
        for ph, trans_name in placeholders:
            restored = restored.replace(ph, trans_name)
            # Handle potential whitespace variations introduced by NMT tokenizers
            ph_spaced = ph.replace("_", " _ ")
            if ph_spaced in restored:
                restored = restored.replace(ph_spaced, trans_name)

        return restored
