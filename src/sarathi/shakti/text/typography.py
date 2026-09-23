"""Shared output typography primitives for Shakti document capabilities."""

from __future__ import annotations

import re
import unicodedata

ENGLISH_FONT: str = "Times New Roman"
DEVANAGARI_FONT: str = "Nirmala UI"
DEFAULT_SIZE_PT: float = 12.0

KNOWN_INDIC_FONTS: frozenset[str] = frozenset(
    {
        "nirmala ui",
        "mangal",
        "aparajita",
        "kokila",
        "utsaah",
        "akshar unicode",
        "kalimati",
        "lohit devanagari",
        "noto sans devanagari",
        "noto serif devanagari",
        "arial unicode ms",
        "shree-dev",
        "dv-ttyogesh",
        "gautami",
        "kartika",
        "latha",
        "raavi",
        "shruti",
        "tunga",
        "vrinda",
    }
)


def is_indic_font(font_name: str | None) -> bool:
    """Return whether a font name corresponds to a genuine Indic/Devanagari font."""
    if not font_name or not isinstance(font_name, str):
        return False
    norm = " ".join(font_name.strip().casefold().split())
    if norm in KNOWN_INDIC_FONTS:
        return True
    return any(pfx in norm for pfx in ("nirmala", "mangal", "aparajita", "kokila", "utsaah", "devanagari", "akshar"))


_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F\u1CD0-\u1CFF\uA8E0-\uA8FF]")
DEVANAGARI_RE = _DEVANAGARI_RE

DEVA_VIRAMA = "\u094d"  # ्
DEVA_NUKTA = "\u093c"  # ़
DEVA_REPH = "\u0930\u094d"  # र्

DEVA_CONSONANTS = "[\u0915-\u0939\u0958-\u095f\u0978-\u097f]"
DEVA_INDEPENDENT_VOWELS = "[\u0904-\u0914\u0960\u0961\u0972-\u0977]"
DEVA_MATRAS = "[\u093a\u093b\u093e-\u094c\u094e\u094f\u0955-\u0957\u0962\u0963]"
DEVA_MODIFIERS = "[\u0901-\u0903]"

_RE_VIRAMA_DEP_MATRA = re.compile(r"\u094d([\u0941-\u0944\u0947-\u094c])")
_RE_MODIFIERS_MATRAS = re.compile(rf"({DEVA_MODIFIERS})({DEVA_MATRAS})")
_RE_DOUBLE_VIRAMA = re.compile(rf"{DEVA_VIRAMA}+")
_RE_DOUBLE_VISARGA = re.compile(r"\u0903{2,}")
_RE_DOUBLE_DANDA = re.compile(r"\u0964{2,}|\u0965{2,}")
_RE_STRAY_ZWNJ_BEFORE_MATRA = re.compile(rf"{DEVA_VIRAMA}[\u200c\u200d]+({DEVA_MATRAS})")
_RE_NUKTA_REORDER = re.compile(rf"({DEVA_CONSONANTS})({DEVA_MATRAS}|{DEVA_VIRAMA})({DEVA_NUKTA})")
_RE_DOUBLE_NUKTA = re.compile(rf"{DEVA_NUKTA}+")
_RE_DOUBLE_E_AI = re.compile(r"[\u0947\u0948]{2,}")
_RE_REMD_HUNG = re.compile(r"[\u0945\u0942]{2,}")
_RE_REMD_HUNG_PAIR = re.compile(r"\u0945\u0942|\u0942\u0945")
_RE_ORPHAN_CHHOTI_I = re.compile(rf"({DEVA_MATRAS})\u093f")
_RE_SPACED_MATRA = re.compile(rf"({DEVA_CONSONANTS}{DEVA_NUKTA}?)\s+({DEVA_MATRAS}|{DEVA_VIRAMA})")
_RE_SPACED_VIRAMA = re.compile(rf"({DEVA_CONSONANTS}{DEVA_NUKTA}?{DEVA_VIRAMA})\s+({DEVA_CONSONANTS})")


def contains_devanagari(text: str) -> bool:
    """Return whether text contains any Devanagari-script character."""
    if not isinstance(text, str) or not text:
        return False
    return bool(_DEVANAGARI_RE.search(text))


def synthesize_akshara_unicode(text: str) -> str:
    """Ensure canonical Unicode ordering inside every Devanagari Akshara.

    Canonical sequence:
    1. Consonant / Cluster
    2. Nukta (़)
    3. Virama (्) (between consonants)
    4. Dependent Vowel Matras (ा, ि, ी, ु, ू, ृ, े, ै, ो, ौ)
    5. Anusvara (ं), Chandrabindu (ँ), Visarga (ः)
    """
    if not text or not contains_devanagari(text):
        return text

    # Fix misplaced matra before virama: e.g. ि् -> ्ि
    text = text.replace("\u093f\u094d", "\u094d\u093f")
    # Resolve invalid virama immediately followed by a dependent vowel matra
    text = _RE_VIRAMA_DEP_MATRA.sub(r"\1", text)
    # Fix misplaced modifiers: e.g. Anusvara before Matra (ंी -> ीं, ंा -> ां)
    text = _RE_MODIFIERS_MATRAS.sub(r"\2\1", text)
    # Fix doubled virama
    text = _RE_DOUBLE_VIRAMA.sub(DEVA_VIRAMA, text)

    # Compose Devanagari 2-part vowel matras (both forward and reverse typing orders):
    text = text.replace("\u093e\u0947", "\u094b")
    text = text.replace("\u0947\u093e", "\u094b")
    text = text.replace("\u093e\u0948", "\u094c")
    text = text.replace("\u0948\u093e", "\u094c")
    text = text.replace("\u093e\u0945", "\u0949")
    text = text.replace("\u0945\u093e", "\u0949")

    # Compose Devanagari independent vowels typed as base vowel + dependent matras:
    text = text.replace("\u0905\u093e", "\u0906")
    text = text.replace("\u0905\u094b", "\u0913")
    text = text.replace("\u0905\u094c", "\u0914")
    text = text.replace("\u0905\u0945", "\u0911")
    text = text.replace("\u090f\u0947", "\u0910")

    # Reorder misplaced Nukta typed after dependent matra or virama to immediately follow consonant
    text = _RE_NUKTA_REORDER.sub(r"\1\3\2", text)
    text = _RE_DOUBLE_NUKTA.sub(DEVA_NUKTA, text)

    # Resolve conflicting consecutive e/ai matras
    text = _RE_DOUBLE_E_AI.sub("\u0948", text)

    # Normalize Remington typewriter artifacts for 'हूँ'
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

    return unicodedata.normalize("NFC", text)


def heal_devanagari_matra_spacing(text: str) -> str:
    """Repair inadvertent spacing and matra ordering in Devanagari text."""
    if not text or not contains_devanagari(text):
        return text
    return synthesize_akshara_unicode(text)


def normalize_text_spacing(text: str) -> str:
    """Normalize extracted text spacing, punctuation padding, and Devanagari combining marks."""
    if not text:
        return ""
    # 1. Collapse multiple horizontal whitespace/tab characters (preserving line breaks)
    text = re.sub(r"[^\S\n]+", " ", text)
    # 2. Normalize spaces before closing punctuation
    text = re.sub(r" +([,.:;?!%\)\]\}])", r"\1", text)
    # 3. Normalize spaces after opening punctuation
    text = re.sub(r"([(\[\{]) +", r"\1", text)
    # 4. Repair Devanagari combining mark spacing
    text = heal_devanagari_matra_spacing(text)
    # 5. Clean up each line and trim trailing/leading spaces
    lines = [line.strip() for line in text.splitlines()]
    result = "\n".join(lines)
    # 6. Collapse 3+ consecutive newlines to clean paragraph breaks (2 newlines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def reconstruct_line_from_spans(
    spans: list[tuple[str, tuple[float, float, float, float], float]],
) -> str:
    """Reconstruct line text from spatial spans using font-metric gap analysis.

    Instead of unconditionally inserting spaces between spans (which breaks words like 'C orporation'
    or spaces out punctuation), this computes horizontal displacement delta_x = sx0 - last_x1.
    A space is only inserted when delta_x >= 0.20 * font_size.
    """
    if not spans:
        return ""
    line_parts: list[str] = []
    last_x1: float | None = None
    last_size: float = 12.0

    for text, bbox, size in spans:
        if not text:
            continue
        sx0, _, sx1, _ = bbox
        eff_size = max(1.0, min(size, last_size))
        if last_x1 is not None:
            gap = sx0 - last_x1
            if gap >= 0.20 * eff_size and line_parts and not line_parts[-1].endswith(" ") and not text.startswith(" "):
                line_parts.append(" ")
        line_parts.append(text)
        last_x1 = sx1
        last_size = size

    return normalize_text_spacing("".join(line_parts))


_DEVA_NUMERALS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize_devanagari_numerals(text: str) -> str:
    """Convert Devanagari numerals (०-९) to standard ASCII/Arabic digits (0-9)."""
    if not text or not isinstance(text, str):
        return "" if text is None else text
    return text.translate(_DEVA_NUMERALS)


def normalize_header_template(text: str) -> str:
    """Normalize text into an invariant template for cross-page recurring header/footer matching.

    Replaces Devanagari and ASCII numerals with '#' and collapses whitespace so that
    running headers with dynamic page numbers or dates match across pages.
    """
    if not text or not isinstance(text, str):
        return ""
    t = text.translate(_DEVA_NUMERALS)
    t = re.sub(r"\d+", "#", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def detect_running_headers_footers(
    pages_items: list[list[tuple[str, tuple[float, float, float, float]]]],
    page_heights: list[float],
    *,
    header_margin_ratio: float = 0.18,
    footer_margin_ratio: float = 0.15,
) -> tuple[set[str], set[str]]:
    """Detect recurring running header and footer text templates across multi-page documents.

    Args:
        pages_items: For each page, a list of (text, bbox) tuples.
        page_heights: Height of each page.
        header_margin_ratio: Upper fraction of page height considered header margin (default 18%).
        footer_margin_ratio: Lower fraction of page height considered footer margin (default 15%).

    Returns:
        tuple[set[str], set[str]]: (header_templates, footer_templates)
    """
    total_pages = len(pages_items)
    if total_pages < 2:
        return set(), set()

    from collections import defaultdict

    header_page_counts: dict[str, set[int]] = defaultdict(set)
    footer_page_counts: dict[str, set[int]] = defaultdict(set)

    for p_idx, (items, p_height) in enumerate(zip(pages_items, page_heights)):
        eff_h = max(100.0, float(p_height))
        hdr_cutoff = eff_h * header_margin_ratio
        ftr_cutoff = eff_h * (1.0 - footer_margin_ratio)

        for text, bbox in items:
            trimmed = text.strip()
            if not trimmed:
                continue
            tmpl = normalize_header_template(trimmed)
            if not tmpl:
                continue

            _, y0, _, y1 = bbox
            if y1 <= hdr_cutoff or y0 <= hdr_cutoff * 0.75:
                header_page_counts[tmpl].add(p_idx)
            elif y0 >= ftr_cutoff or y1 >= ftr_cutoff * 1.05:
                footer_page_counts[tmpl].add(p_idx)

    # A running header or footer must recur across at least 2 distinct pages
    min_pages = 2
    header_templates = {tmpl for tmpl, p_set in header_page_counts.items() if len(p_set) >= min_pages}
    footer_templates = {tmpl for tmpl, p_set in footer_page_counts.items() if len(p_set) >= min_pages}

    return header_templates, footer_templates


def classify_page_lines(
    items: list[tuple[str, tuple[float, float, float, float]]],
    page_height: float,
    header_templates: set[str],
    footer_templates: set[str],
    *,
    header_margin_ratio: float = 0.20,
    footer_margin_ratio: float = 0.18,
) -> tuple[list[str], list[str], list[str]]:
    """Classify items on a single page into body, header, and footer text lines.

    Returns:
        tuple[list[str], list[str], list[str]]: (body_lines, header_lines, footer_lines)
    """
    eff_h = max(100.0, float(page_height))
    hdr_cutoff = eff_h * header_margin_ratio
    ftr_cutoff = eff_h * (1.0 - footer_margin_ratio)

    body_lines: list[str] = []
    header_lines: list[str] = []
    footer_lines: list[str] = []

    for text, bbox in items:
        trimmed = text.strip()
        if not trimmed:
            continue
        tmpl = normalize_header_template(trimmed)
        _, y0, _, y1 = bbox

        if (y1 <= hdr_cutoff or y0 <= hdr_cutoff * 0.75) and tmpl in header_templates:
            header_lines.append(trimmed)
        elif (y0 >= ftr_cutoff or y1 >= ftr_cutoff * 1.05) and tmpl in footer_templates:
            footer_lines.append(trimmed)
        else:
            body_lines.append(trimmed)

    return body_lines, header_lines, footer_lines


def output_font(*, contains_devanagari: bool) -> str:
    """Choose the canonical output font for Latin-only or Devanagari content."""
    return DEVANAGARI_FONT if contains_devanagari else ENGLISH_FONT


def normalize_size(
    size_pt: float | None = None,
    *,
    default_size_pt: float = DEFAULT_SIZE_PT,
) -> float:
    """Preserve a positive logical font size or use the canonical default."""
    eff_size = default_size_pt if size_pt is None else float(size_pt)
    if eff_size <= 0:
        raise ValueError("font size must be greater than zero")
    return eff_size


__all__ = [
    "DEFAULT_SIZE_PT",
    "DEVANAGARI_FONT",
    "DEVANAGARI_RE",
    "ENGLISH_FONT",
    "KNOWN_INDIC_FONTS",
    "classify_page_lines",
    "contains_devanagari",
    "detect_running_headers_footers",
    "heal_devanagari_matra_spacing",
    "is_indic_font",
    "normalize_devanagari_numerals",
    "normalize_header_template",
    "normalize_size",
    "normalize_text_spacing",
    "output_font",
    "reconstruct_line_from_spans",
    "synthesize_akshara_unicode",
]
