"""CLI Audit Tool for Legacy Fonts and CMap Signatures.

Inspects TrueType/OpenType fonts, verifies name records, OpenType GSUB Devanagari presence,
CMap encoding tables, anchor glyph outline fingerprints, and cross-references against
Sarathi's font conversion profiles.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sarathi.shakti.font_conversion.detector import load_font_profiles
from sarathi.shakti.font_conversion.font_inspector import (
    inspect_font_bytes,
)

try:
    from fontTools.ttLib import TTFont

    _HAS_FONTTOOLS = True
except ImportError:
    TTFont = None
    _HAS_FONTTOOLS = False


def audit_font_file(font_path: Path, profile_id: str | None = None) -> dict[str, object]:
    """Run a comprehensive structural and profile audit on a TTF/OTF font file."""
    if not font_path.exists():
        raise FileNotFoundError(f"Font file not found: {font_path}")

    font_bytes = font_path.read_bytes()
    profiles = load_font_profiles()
    meta = inspect_font_bytes(font_bytes, profiles=profiles)

    target_profile_id = profile_id or meta.candidate_profile
    profile_data = profiles.get(target_profile_id) if target_profile_id else None

    # Deeper cmap coverage analysis if fontTools is available
    cmap_coverage: dict[str, object] = {}
    if _HAS_FONTTOOLS and TTFont is not None:
        try:
            import io

            font = TTFont(io.BytesIO(font_bytes))
            cmap = font.getBestCmap() or {}
            if not cmap and "cmap" in font and font["cmap"].tables:
                cmap = getattr(font["cmap"].tables[0], "cmap", {})

            cmap_cps = set(cmap.keys())
            glyph_set = set(font.getGlyphSet().keys())

            if profile_data:
                profile_mapped_chars = set(profile_data.mappings.keys())
                # Check which mapped chars exist in font
                mapped_in_font = 0
                dead_mappings: list[str] = []
                for ch in sorted(profile_mapped_chars):
                    cp = ord(ch[0]) if len(ch) == 1 else None
                    if cp and (cp in cmap_cps or (0xF000 + cp) in cmap_cps):
                        mapped_in_font += 1
                    else:
                        dead_mappings.append(ch)

                cmap_coverage = {
                    "total_cmap_entries": len(cmap),
                    "total_glyphs": len(glyph_set),
                    "profile_mapped_entries": len(profile_mapped_chars),
                    "active_mapped_in_font": mapped_in_font,
                    "dead_mapping_count": len(dead_mappings),
                    "dead_mappings_sample": dead_mappings[:20],
                }
            else:
                cmap_coverage = {
                    "total_cmap_entries": len(cmap),
                    "total_glyphs": len(glyph_set),
                }
        except Exception as exc:
            cmap_coverage = {"error": str(exc)}

    return {
        "file": str(font_path),
        "file_size_bytes": len(font_bytes),
        "postscript_name": meta.postscript_name,
        "family_name": meta.family_name,
        "full_name": meta.full_name,
        "is_modern_unicode": meta.is_modern_unicode,
        "is_legacy_symbol": meta.is_legacy_symbol,
        "is_unsupported_legacy": meta.is_unsupported_legacy,
        "has_gsub_deva": meta.has_gsub_deva,
        "has_symbol_cmap": meta.has_symbol_cmap,
        "has_macroman_cmap": meta.has_macroman_cmap,
        "cmap_platforms": meta.cmap_platforms,
        "cmap_signature": meta.cmap_signature,
        "candidate_profile": target_profile_id,
        "confidence": meta.confidence,
        "outline_fingerprints": meta.outline_fingerprints,
        "cmap_coverage": cmap_coverage,
    }


def main() -> None:
    """CLI entry point for audit_legacy_font."""
    parser = argparse.ArgumentParser(description="Audit TTF/OTF fonts for legacy Devanagari conversion.")
    parser.add_argument("font", type=Path, help="Path to TTF/OTF font file.")
    parser.add_argument("--profile", type=str, default=None, help="Specific profile ID to cross-reference against.")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = parser.parse_args()

    try:
        report = audit_font_file(args.font, profile_id=args.profile)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(f"=== Font Audit Report: {report['file']} ===")
            print(f"Family: {report['family_name']} | Full: {report['full_name']} | PS: {report['postscript_name']}")
            print(f"Classification: Modern={report['is_modern_unicode']}, Legacy={report['is_legacy_symbol']}, Unsupported={report['is_unsupported_legacy']}")
            print(f"GSUB Devanagari: {report['has_gsub_deva']}")
            print(f"CMap Platforms: {report['cmap_platforms']}")
            print(f"CMap Signature: {report['cmap_signature']}")
            print(f"Candidate Profile: {report['candidate_profile']} (confidence: {report['confidence']:.2f})")
            if report.get("outline_fingerprints"):
                print("Anchor Outlines:")
                for k, v in report["outline_fingerprints"].items():  # type: ignore[union-attr]
                    print(f"  {k!r}: {v}")
            cov = report.get("cmap_coverage", {})
            if cov:
                print("Coverage:")
                for k, v in cov.items():  # type: ignore[union-attr]
                    print(f"  {k}: {v}")
    except Exception as exc:
        print(f"Error during font audit: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
