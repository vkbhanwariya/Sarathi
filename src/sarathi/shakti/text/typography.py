"""Shared output typography primitives for Shakti document capabilities."""

from __future__ import annotations

import re

ENGLISH_FONT: str = "Times New Roman"
DEVANAGARI_FONT: str = "Nirmala UI"
DEFAULT_SIZE_PT: float = 12.0

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F\u1CD0-\u1CFF\uA8E0-\uA8FF]")
DEVANAGARI_RE = _DEVANAGARI_RE


_DEVANAGARI_COMBINING = re.compile(r" +([\u0901-\u0903\u093c\u093e-\u094f\u0951-\u0954])")
_DEVANAGARI_HALANT_GAP = re.compile(r"(\u094d) +([\u0915-\u0939])")


def contains_devanagari(text: str) -> bool:
    """Return whether text contains any Devanagari-script character."""
    if not isinstance(text, str) or not text:
        return False
    return bool(_DEVANAGARI_RE.search(text))


def heal_devanagari_matra_spacing(text: str) -> str:
    """Repair inadvertent spacing between consonants and combining Devanagari vowel matras or virama."""
    if not text or not contains_devanagari(text):
        return text
    text = _DEVANAGARI_COMBINING.sub(r"\1", text)
    text = _DEVANAGARI_HALANT_GAP.sub(r"\1\2", text)
    return text


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
    "classify_page_lines",
    "contains_devanagari",
    "detect_running_headers_footers",
    "heal_devanagari_matra_spacing",
    "normalize_header_template",
    "normalize_size",
    "normalize_text_spacing",
    "output_font",
    "reconstruct_line_from_spans",
]
