"""Visual Glyph Sheet Generator for Legacy Font Auditing.

Generates a standalone, beautiful HTML audit sheet rendering vector glyph crops
alongside byte codepoints, ASCII character representations, and profile mapping targets.
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sarathi.shakti.font_conversion.detector import load_font_profiles  # noqa: E402

try:
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.ttLib import TTFont

    _HAS_FONTTOOLS = True
except ImportError:
    TTFont = None
    SVGPathPen = None
    _HAS_FONTTOOLS = False


def generate_glyph_sheet_html(
    font_path: Path,
    profile_id: str | None = None,
    max_glyphs: int = 256,
) -> str:
    """Generate HTML report with rendered SVG glyph shapes from a TTF font."""
    if not _HAS_FONTTOOLS or TTFont is None or SVGPathPen is None:
        raise RuntimeError("fontTools is required to generate visual glyph sheets.")

    font = TTFont(font_path)
    glyph_set = font.getGlyphSet()
    units_per_em = font["head"].unitsPerEm if "head" in font else 1000

    cmap = font.getBestCmap() or {}
    if not cmap and "cmap" in font and font["cmap"].tables:
        cmap = getattr(font["cmap"].tables[0], "cmap", {})

    profiles = load_font_profiles()
    profile = profiles.get(profile_id) if profile_id else None

    # Collect entries
    cards_html: list[str] = []
    seen_glyphs: set[str] = set()

    # Iterate codepoints 32..255 (standard 8-bit range) first, then remaining
    ordered_cps = list(range(32, 256))
    for cp in sorted(cmap.keys()):
        if cp not in ordered_cps:
            ordered_cps.append(cp)

    count = 0
    for cp in ordered_cps:
        if count >= max_glyphs:
            break
        gname = cmap.get(cp) or cmap.get(0xF000 + cp)
        if not gname or gname not in glyph_set or gname in seen_glyphs:
            continue
        seen_glyphs.add(gname)
        count += 1

        glyph = glyph_set[gname]
        pen = SVGPathPen(glyph_set)
        glyph.draw(pen)
        svg_d = pen.getCommands()

        char_repr = chr(cp) if (32 <= cp <= 126 or 160 <= cp <= 255) else f"\\x{cp:02x}"
        mapped_target = profile.mappings.get(char_repr, "") if profile else ""

        card = f"""
        <div class="glyph-card">
            <div class="glyph-svg-wrap">
                <svg viewBox="0 -{units_per_em * 0.2:.0f} {units_per_em} {units_per_em * 1.2:.0f}" transform="scale(1, -1)">
                    <path d="{svg_d}" fill="#2d3748" />
                </svg>
            </div>
            <div class="glyph-info">
                <div class="cp-hex">0x{cp:02X} ({cp})</div>
                <div class="char-sym">Char: <code>{html.escape(char_repr)}</code></div>
                <div class="glyph-name">{html.escape(gname)}</div>
                {f'<div class="mapped-target">Maps to: <b>{html.escape(mapped_target)}</b></div>' if mapped_target else ""}
            </div>
        </div>
        """
        cards_html.append(card)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Visual Glyph Sheet: {html.escape(font_path.name)}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f7fafc; margin: 24px; }}
        h1 {{ color: #1a202c; font-size: 20px; margin-bottom: 8px; }}
        .meta {{ color: #718096; font-size: 14px; margin-bottom: 24px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 16px; }}
        .glyph-card {{ background: white; border-radius: 8px; border: 1px solid #e2e8f0; padding: 12px; display: flex; flex-direction: column; align-items: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
        .glyph-svg-wrap {{ width: 80px; height: 80px; display: flex; align-items: center; justify-content: center; background: #edf2f7; border-radius: 4px; margin-bottom: 8px; }}
        svg {{ width: 64px; height: 64px; }}
        .glyph-info {{ font-size: 11px; text-align: center; color: #4a5568; width: 100%; }}
        .cp-hex {{ font-weight: 600; color: #2b6cb0; }}
        .char-sym {{ margin-top: 2px; }}
        .glyph-name {{ color: #a0aec0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .mapped-target {{ margin-top: 4px; color: #2f855a; background: #f0fff4; border-radius: 2px; padding: 2px 4px; }}
    </style>
</head>
<body>
    <h1>Glyph Sheet: {html.escape(font_path.name)}</h1>
    <div class="meta">Total Glyphs Rendered: {len(cards_html)} | Profile: {html.escape(str(profile_id))}</div>
    <div class="grid">
        {"".join(cards_html)}
    </div>
</body>
</html>
"""


def main() -> None:
    """CLI entry point for glyph_sheet."""
    parser = argparse.ArgumentParser(description="Generate visual HTML glyph sheet from TTF font.")
    parser.add_argument("font", type=Path, help="Path to TTF font.")
    parser.add_argument("--profile", type=str, default=None, help="Profile ID to show target mappings.")
    parser.add_argument("--output", type=Path, default=Path("glyph_sheet.html"), help="Output HTML file path.")
    parser.add_argument("--max-glyphs", type=int, default=256, help="Maximum glyphs to render.")
    args = parser.parse_args()

    html_content = generate_glyph_sheet_html(args.font, profile_id=args.profile, max_glyphs=args.max_glyphs)
    args.output.write_text(html_content, encoding="utf-8")
    print(f"Glyph sheet generated successfully at: {args.output.resolve()}")


if __name__ == "__main__":
    main()
