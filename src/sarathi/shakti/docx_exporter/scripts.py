"""Text script segmentation for bilingual Hindi (Devanagari) and Latin/English documents."""

from __future__ import annotations

import unicodedata

from sarathi.shakti.docx_exporter.constants import _DEVANAGARI_CHAR_RE


def segment_text_by_script(text: str) -> list[tuple[str, bool]]:
    """Segment text into contiguous chunks with a flag indicating whether it is Devanagari.

    Returns:
        list of tuples (chunk_text, is_devanagari).
    """
    if not text:
        return []

    chunks: list[tuple[str, bool]] = []
    current_chars: list[str] = []
    current_is_dev: bool | None = None

    for char in text:
        is_dev = bool(_DEVANAGARI_CHAR_RE.match(char))
        # Keep neutral whitespace/punctuation with current active script if set
        if char.isspace() or unicodedata.category(char).startswith("P"):
            if current_is_dev is None:
                current_is_dev = False
            current_chars.append(char)
            continue

        if current_is_dev is None:
            current_is_dev = is_dev
            current_chars.append(char)
        elif is_dev == current_is_dev:
            current_chars.append(char)
        else:
            if current_chars:
                chunks.append(("".join(current_chars), current_is_dev))
            current_chars = [char]
            current_is_dev = is_dev

    if current_chars:
        chunks.append(("".join(current_chars), current_is_dev if current_is_dev is not None else False))

    return chunks
