"""OpenXML style and docDefaults hierarchy resolution for run font and size properties."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from sarathi.shakti.docx_exporter.constants import _W_NS


def _is_complex_script_char(c: str) -> bool:
    """Check if character belongs to complex script ranges (Indic, Arabic, Thai, Khmer), excluding Latin/General Punctuation."""
    code = ord(c)
    return (
        0x0900 <= code <= 0x0DFF
        or 0xA8E0 <= code <= 0xA8FF
        or 0x1CD0 <= code <= 0x1CFF
        or 0x0590 <= code <= 0x08FF
        or 0x0E00 <= code <= 0x109F
        or 0x1780 <= code <= 0x17FF
    )


def resolve_neutral_ooxml_font(
    *,
    ascii_font: str | None = None,
    hansi_font: str | None = None,
    cs_font: str | None = None,
    run_text: str = "",
) -> str | None:
    """Resolve effective font following ECMA-376 OpenXML character rules.

    If run_text contains complex script characters (e.g. Devanagari Unicode),
    the complex script channel (cs) takes precedence. Otherwise, ascii/hAnsi applies.
    """
    if run_text and any(_is_complex_script_char(c) for c in run_text):
        return cs_font or ascii_font or hansi_font
    return ascii_font or hansi_font or cs_font


class DocxStyleResolver:
    """Resolves effective OpenXML run fonts through styles and docDefaults hierarchy."""

    def __init__(
        self,
        styles_xml: bytes | None = None,
        font_resolver: Callable[..., str | None] | None = None,
    ) -> None:
        self.doc_default_fonts: dict[str, str] = {}
        self.doc_default_size_half_pt: float | None = None
        self.styles: dict[str, dict[str, Any]] = {}
        self._font_resolver = font_resolver
        if styles_xml:
            self._parse_styles(styles_xml)

    def _parse_styles(self, styles_xml: bytes) -> None:
        try:
            root = ET.fromstring(styles_xml)
        except (ET.ParseError, ValueError):
            return

        # 1. docDefaults
        rpr_def = root.find(f".//{{{_W_NS}}}docDefaults/{{{_W_NS}}}rPrDefault/{{{_W_NS}}}rPr")
        if rpr_def is not None:
            rf = rpr_def.find(f"{{{_W_NS}}}rFonts")
            if rf is not None:
                for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
                    val = rf.attrib.get(f"{{{_W_NS}}}{attr}")
                    if val:
                        self.doc_default_fonts[attr] = val
            sz = rpr_def.find(f"{{{_W_NS}}}sz")
            if sz is not None and f"{{{_W_NS}}}val" in sz.attrib:
                try:
                    self.doc_default_size_half_pt = float(sz.attrib[f"{{{_W_NS}}}val"])
                except ValueError:
                    pass

        # 2. styles
        for s in root.findall(f"{{{_W_NS}}}style"):
            style_id = s.attrib.get(f"{{{_W_NS}}}styleId")
            if not style_id:
                continue
            style_type = s.attrib.get(f"{{{_W_NS}}}type", "paragraph")
            based_on = None
            bo_elem = s.find(f"{{{_W_NS}}}basedOn")
            if bo_elem is not None:
                based_on = bo_elem.attrib.get(f"{{{_W_NS}}}val")

            fonts: dict[str, str] = {}
            size_half_pt: float | None = None
            rpr = s.find(f"{{{_W_NS}}}rPr")
            if rpr is not None:
                rf = rpr.find(f"{{{_W_NS}}}rFonts")
                if rf is not None:
                    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
                        val = rf.attrib.get(f"{{{_W_NS}}}{attr}")
                        if val:
                            fonts[attr] = val
                sz = rpr.find(f"{{{_W_NS}}}sz")
                if sz is not None and f"{{{_W_NS}}}val" in sz.attrib:
                    try:
                        size_half_pt = float(sz.attrib[f"{{{_W_NS}}}val"])
                    except ValueError:
                        pass

            self.styles[style_id] = {
                "type": style_type,
                "based_on": based_on,
                "fonts": fonts,
                "size_half_pt": size_half_pt,
            }

    def _find_size_in_style_hierarchy(self, style_id: str | None) -> float | None:
        visited: set[str] = set()
        curr = style_id
        while curr and curr not in visited:
            visited.add(curr)
            s_info = self.styles.get(curr)
            if not s_info:
                break
            sz_val = s_info.get("size_half_pt")
            if sz_val is not None:
                return sz_val
            curr = s_info.get("based_on")
        return None

    def resolve_run_size_half_pt(
        self,
        r_or_rpr: ET.Element,
        p: ET.Element | None = None,
    ) -> float | None:
        """Resolve effective font size in half-points following the OpenXML hierarchy."""
        rpr = r_or_rpr if r_or_rpr.tag.endswith("rPr") else r_or_rpr.find(f"{{{_W_NS}}}rPr")
        if rpr is not None:
            sz = rpr.find(f"{{{_W_NS}}}sz")
            if sz is not None and f"{{{_W_NS}}}val" in sz.attrib:
                try:
                    return float(sz.attrib[f"{{{_W_NS}}}val"])
                except ValueError:
                    pass
            rstyle = rpr.find(f"{{{_W_NS}}}rStyle")
            if rstyle is not None:
                sid = rstyle.attrib.get(f"{{{_W_NS}}}val")
                val = self._find_size_in_style_hierarchy(sid)
                if val is not None:
                    return val

        if p is not None:
            ppr = p.find(f"{{{_W_NS}}}pPr")
            if ppr is not None:
                pstyle = ppr.find(f"{{{_W_NS}}}pStyle")
                if pstyle is not None:
                    sid = pstyle.attrib.get(f"{{{_W_NS}}}val")
                    val = self._find_size_in_style_hierarchy(sid)
                    if val is not None:
                        return val

        return self.doc_default_size_half_pt

    def resolve_run_font_channels(
        self,
        r: ET.Element,
        p: ET.Element | None = None,
    ) -> dict[str, str]:
        """Resolve all available font channels (ascii, hAnsi, cs, eastAsia) for run r."""
        channels: dict[str, str] = {}

        # 1. Direct rPr / rFonts
        rpr = r.find(f"{{{_W_NS}}}rPr")
        if rpr is not None:
            rf = rpr.find(f"{{{_W_NS}}}rFonts")
            if rf is not None:
                for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
                    val = rf.attrib.get(f"{{{_W_NS}}}{attr}")
                    if val:
                        channels[attr] = val

            # 2. Character style (rStyle)
            rstyle = rpr.find(f"{{{_W_NS}}}rStyle")
            if rstyle is not None:
                sid = rstyle.attrib.get(f"{{{_W_NS}}}val")
                self._fill_channels_from_style(sid, channels)

        # 3. Paragraph style (pStyle)
        if p is not None:
            ppr = p.find(f"{{{_W_NS}}}pPr")
            if ppr is not None:
                pstyle = ppr.find(f"{{{_W_NS}}}pStyle")
                if pstyle is not None:
                    sid = pstyle.attrib.get(f"{{{_W_NS}}}val")
                    self._fill_channels_from_style(sid, channels)

        # 4. Document defaults
        for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
            if attr not in channels and attr in self.doc_default_fonts:
                channels[attr] = self.doc_default_fonts[attr]

        return channels

    def _fill_channels_from_style(self, style_id: str | None, channels: dict[str, str]) -> None:
        visited: set[str] = set()
        curr = style_id
        while curr and curr not in visited:
            visited.add(curr)
            s_info = self.styles.get(curr)
            if not s_info:
                break
            fonts = s_info.get("fonts", {})
            for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
                if attr not in channels and attr in fonts:
                    channels[attr] = fonts[attr]
            curr = s_info.get("based_on")

    def resolve_run_font(
        self,
        r: ET.Element,
        p: ET.Element | None = None,
        is_ascii_text: bool = True,
        text: str | None = None,
        font_resolver: Callable[..., str | None] | None = None,
    ) -> str | None:
        """Resolve effective font name for run r following the OpenXML hierarchy."""
        channels = self.resolve_run_font_channels(r, p)
        if not channels:
            return None

        if text is not None:
            resolver = font_resolver or self._font_resolver
            if resolver is not None:
                return resolver(
                    ascii_font=channels.get("ascii"),
                    hansi_font=channels.get("hAnsi"),
                    cs_font=channels.get("cs"),
                    run_text=text,
                )
            return resolve_neutral_ooxml_font(
                ascii_font=channels.get("ascii"),
                hansi_font=channels.get("hAnsi"),
                cs_font=channels.get("cs"),
                run_text=text,
            )

        if is_ascii_text:
            return channels.get("ascii") or channels.get("hAnsi") or channels.get("cs")
        return channels.get("cs") or channels.get("ascii") or channels.get("hAnsi")

    def get_primary_modern_cs_font(self) -> str | None:
        """Inspect document defaults and styles to detect the declared modern complex script font."""
        cs = self.doc_default_fonts.get("cs")
        if cs:
            return cs
        normal_style = self.styles.get("Normal")
        if normal_style:
            cs = normal_style.get("fonts", {}).get("cs")
            if cs:
                return cs
        for s_info in self.styles.values():
            cs = s_info.get("fonts", {}).get("cs")
            if cs:
                return cs
        return None
