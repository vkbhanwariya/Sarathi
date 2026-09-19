"""Binary Font Inspector using fontTools for Roopa Font Conversion.

Parses TrueType and OpenType binary font headers, metadata, OpenType GSUB tables,
and cmap encodings to deterministically classify modern Unicode vs. legacy symbol fonts.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Any

from sarathi.shakti.font_conversion.detector import (
    _KNOWN_LATIN_FONTS,
    _KNOWN_MODERN_INDIC_FONTS,
    _KNOWN_UNSUPPORTED_LEGACY_FONTS,
    resolve_profile_from_font_name,
)
from sarathi.shakti.font_conversion.models import LegacyFontProfile

try:
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.ttLib import TTFont

    _HAS_FONTTOOLS = True
except ImportError:
    TTFont = None  # type: ignore[assignment,misc]
    RecordingPen = None  # type: ignore[assignment,misc]
    _HAS_FONTTOOLS = False


DEFAULT_ANCHOR_SYMBOLS: tuple[str, ...] = (
    "d",
    "x",
    "m",
    "k",
    "f",
    "Z",
    "ñ",
    "ò",
    "ö",
    "Ù",
    "Ø",
)


@dataclass(frozen=True, slots=True)
class BinaryFontMetadata:
    """Classified structural metadata extracted from a binary TTF/OTF font."""

    postscript_name: str | None = None
    family_name: str | None = None
    full_name: str | None = None
    is_modern_unicode: bool = False
    is_legacy_symbol: bool = False
    is_unsupported_legacy: bool = False
    has_gsub_deva: bool = False
    has_symbol_cmap: bool = False
    has_macroman_cmap: bool = False
    cmap_platforms: tuple[tuple[int, int], ...] = ()
    cmap_signature: str | None = None
    outline_fingerprints: dict[str, str] | None = None
    candidate_profile: str | None = None
    confidence: float = 0.0


def compute_cmap_signature(font: Any) -> str | None:
    """Compute a deterministic SHA-256 fingerprint of character-to-glyph mappings."""
    if not hasattr(font, "__getitem__") or "cmap" not in font:
        return None
    try:
        target_subtable = None
        for subtable in font["cmap"].tables:
            if (subtable.platformID == 3 and subtable.platEncID == 0) or (
                subtable.platformID == 1 and subtable.platEncID == 0
            ):
                target_subtable = subtable
                break
        if target_subtable is None and font["cmap"].tables:
            target_subtable = font["cmap"].tables[0]
        if target_subtable and hasattr(target_subtable, "cmap") and target_subtable.cmap:
            pairs = sorted(target_subtable.cmap.items())
            raw_repr = ";".join(f"{k}:{v}" for k, v in pairs)
            return hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()[:32]
    except Exception:
        pass
    return None


def compute_anchor_outline_hashes(
    font: Any,
    anchors: tuple[str, ...] = DEFAULT_ANCHOR_SYMBOLS,
) -> dict[str, str]:
    """Compute scale-invariant outline hashes for discriminative anchor characters."""
    if not _HAS_FONTTOOLS or RecordingPen is None or not hasattr(font, "getGlyphSet"):
        return {}
    results: dict[str, str] = {}
    try:
        glyph_set = font.getGlyphSet()
        cmap = font.getBestCmap() or {}
        if not cmap and "cmap" in font and font["cmap"].tables:
            cmap = getattr(font["cmap"].tables[0], "cmap", {})

        for ch in anchors:
            cp = ord(ch)
            gname = cmap.get(cp) or cmap.get(0xF000 + cp)
            if not gname or gname not in glyph_set:
                continue
            pen = RecordingPen()
            glyph_set[gname].draw(pen)
            if not pen.value:
                continue

            pts: list[tuple[float, float]] = []
            for _op, args in pen.value:
                for arg in args:
                    if isinstance(arg, (tuple, list)) and len(arg) == 2:
                        pts.append((float(arg[0]), float(arg[1])))
            if not pts:
                continue

            min_x = min(p[0] for p in pts)
            max_x = max(p[0] for p in pts)
            min_y = min(p[1] for p in pts)
            max_y = max(p[1] for p in pts)
            w = max_x - min_x or 1.0
            h = max_y - min_y or 1.0

            normalized_ops: list[str] = []
            for op, args in pen.value:
                norm_args: list[str] = []
                for arg in args:
                    if isinstance(arg, (tuple, list)) and len(arg) == 2:
                        nx = int(round((arg[0] - min_x) / w * 1000))
                        ny = int(round((arg[1] - min_y) / h * 1000))
                        norm_args.append(f"{nx},{ny}")
                    else:
                        norm_args.append(str(arg))
                normalized_ops.append(f"{op}({':'.join(norm_args)})")

            payload = ";".join(normalized_ops)
            hsh = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
            results[ch] = hsh
    except Exception:
        pass
    return results


def inspect_font_bytes(
    font_bytes: bytes,
    profiles: dict[str, LegacyFontProfile] | None = None,
) -> BinaryFontMetadata:
    """Inspect binary TTF/OTF font bytes and extract structural metadata.

    Operates fail-safe with zero exceptions if fontTools is unavailable or bytes are corrupted.
    """
    if not _HAS_FONTTOOLS or not font_bytes or len(font_bytes) < 64:
        return BinaryFontMetadata()

    try:
        font = TTFont(io.BytesIO(font_bytes))
    except Exception:
        return BinaryFontMetadata()

    postscript_name: str | None = None
    family_name: str | None = None
    full_name: str | None = None

    # 1. Parse 'name' table for canonical naming records
    if "name" in font:
        for rec in font["name"].names:
            try:
                val = rec.toUnicode().strip()
            except Exception:
                continue
            if not val:
                continue
            if rec.nameID == 6 and not postscript_name:
                postscript_name = val
            elif rec.nameID == 1 and not family_name:
                family_name = val
            elif rec.nameID == 4 and not full_name:
                full_name = val

    # 2. Parse 'GSUB' table for OpenType Devanagari script features
    has_gsub_deva = False
    if "GSUB" in font:
        try:
            gsub = font["GSUB"].table
            if hasattr(gsub, "ScriptList") and gsub.ScriptList:
                for script_record in gsub.ScriptList.ScriptRecord:
                    tag = getattr(script_record, "ScriptTag", "").strip()
                    if tag in ("deva", "dev2"):
                        has_gsub_deva = True
                        break
        except Exception:
            pass

    # 3. Parse 'cmap' table for Symbol and MacRoman encoding subtables
    has_symbol_cmap = False
    has_macroman_cmap = False
    cmap_platforms_list: list[tuple[int, int]] = []

    if "cmap" in font:
        try:
            for subtable in font["cmap"].tables:
                plat = (int(subtable.platformID), int(subtable.platEncID))
                cmap_platforms_list.append(plat)
                # Platform 3 (Windows), PlatEnc 0 (Symbol)
                if subtable.platformID == 3 and subtable.platEncID == 0:
                    has_symbol_cmap = True
                # Platform 1 (Macintosh), PlatEnc 0 (MacRoman)
                if subtable.platformID == 1 and subtable.platEncID == 0:
                    has_macroman_cmap = True
        except Exception:
            pass

    cmap_sig = compute_cmap_signature(font)
    outline_hashes = compute_anchor_outline_hashes(font)

    # 4. Arbitration classification
    names_to_check = [n for n in (family_name, full_name, postscript_name) if n]
    is_modern = has_gsub_deva
    is_legacy = has_symbol_cmap or has_macroman_cmap
    is_unsupported = False
    candidate_profile: str | None = None
    confidence = 0.0

    for name in names_to_check:
        clean = name.lower()
        if any(mod in clean for mod in _KNOWN_MODERN_INDIC_FONTS) or any(lat in clean for lat in _KNOWN_LATIN_FONTS):
            is_modern = True
            break
        if any(unsupp in clean for unsupp in _KNOWN_UNSUPPORTED_LEGACY_FONTS):
            is_unsupported = True
            is_legacy = True
            break

    # If GSUB Devanagari exists, it is definitively a modern Unicode font
    if has_gsub_deva:
        is_modern = True
        is_legacy = False
        confidence = 1.0
    elif is_unsupported:
        confidence = 0.9
    elif profiles is not None:
        for name in names_to_check:
            pid, fam = resolve_profile_from_font_name(name, profiles)
            if pid is not None:
                candidate_profile = pid
                is_legacy = True
                confidence = 0.95 if (has_symbol_cmap or has_macroman_cmap) else 0.85
                break

    return BinaryFontMetadata(
        postscript_name=postscript_name,
        family_name=family_name,
        full_name=full_name,
        is_modern_unicode=is_modern,
        is_legacy_symbol=is_legacy,
        is_unsupported_legacy=is_unsupported,
        has_gsub_deva=has_gsub_deva,
        has_symbol_cmap=has_symbol_cmap,
        has_macroman_cmap=has_macroman_cmap,
        cmap_platforms=tuple(cmap_platforms_list),
        cmap_signature=cmap_sig,
        outline_fingerprints=outline_hashes or None,
        candidate_profile=candidate_profile,
        confidence=confidence,
    )
