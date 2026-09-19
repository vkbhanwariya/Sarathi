"""Byte normalizer for repairing MacRoman-encoded legacy Devanagari streams."""

from __future__ import annotations

# Diagnostic MacRoman signature characters produced when PDF generators embed
# 8-bit legacy Devanagari fonts under /Encoding /MacRomanEncoding rather than /WinAnsiEncoding.
# PyMuPDF decodes bytes 0x80..0xFF into MacRoman Unicode representations.
MACROMAN_SIGNATURES: frozenset[str] = frozenset(
    {
        "\u2044",  # ⁄ (fraction slash, MacRoman 0xDA)
        "\u25ca",  # ◊ (lozenge, MacRoman 0xD7)
        "\u201a",  # ‚ (single low-9 quotation mark, MacRoman 0xE2)
        "\ufb02",  # ﬂ (latin small ligature fl, MacRoman 0xDE)
        "\ufb01",  # ﬁ (latin small ligature fi, MacRoman 0xDD)
        "\u0178",  # Ÿ (latin capital letter y with diaeresis, MacRoman 0xD9)
        "\u00ca",  # Ê (latin capital letter e with circumflex, MacRoman 0x83 / 0xE6)
    }
)


def has_macroman_signatures(text: str) -> bool:
    """Return True if text contains diagnostic MacRoman signature characters."""
    if not text or not isinstance(text, str):
        return False
    return any(ch in MACROMAN_SIGNATURES for ch in text)


def is_macroman_text(text: str) -> bool:
    """Alias for has_macroman_signatures."""
    return has_macroman_signatures(text)


def normalize_macroman_bytes(text: str) -> str:
    """Invert MacRoman encoding to recover original Windows-1252 keystroke bytes.

    When PDF generators embed 8-bit legacy Devanagari fonts with MacRoman encoding,
    bytes 0x80..0xFF are decoded into MacRoman Unicode characters. This function
    encodes the string back to raw 8-bit bytes using MacRoman and re-decodes
    as Windows-1252, restoring the exact keystrokes expected by legacy font mapping tables.

    This operation is completely idempotent and zero-op for normal text streams.
    """
    if not text or not isinstance(text, str) or not has_macroman_signatures(text):
        return text

    try:
        raw_bytes = text.encode("mac_roman")
        return raw_bytes.decode("cp1252", errors="replace")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
