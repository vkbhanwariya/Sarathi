"""In-place OpenXML DOCX document transformation and XML tree processing."""

from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    WarningRecord,
)
from sarathi.shakti.docx_exporter.constants import (
    _DEFAULT_HALF_PT,
    _DEVANAGARI_CHAR_RE,
    _DOCX_MIME_TYPE,
    _ENGLISH_FONT,
    _HINDI_FONT,
    _NON_DELETABLE_RUN_CHILDREN,
    _W_NS,
)
from sarathi.shakti.docx_exporter.font_size_normalizer import get_font_size_adjustment
from sarathi.shakti.docx_exporter.scripts import segment_text_by_script
from sarathi.shakti.docx_exporter.styles import DocxStyleResolver, resolve_neutral_ooxml_font
from sarathi.shakti.text.legacy_detection import _KNOWN_MODERN_FONTS


def _serialize_xml_preserving_namespaces(
    tree: ET.Element,
    raw_entry: bytes,
) -> bytes:
    """Serialize an ElementTree root element to bytes, preserving root namespace declarations."""
    # 1. Register all namespace prefixes declared in the source XML
    try:
        for event, (prefix, uri) in ET.iterparse(io.BytesIO(raw_entry), events=["start-ns"]):
            if prefix:
                try:
                    ET.register_namespace(prefix, uri)
                except (ValueError, KeyError):
                    pass
    except (ET.ParseError, ValueError):
        pass

    # 2. Serialize tree with ElementTree
    serialized = ET.tostring(tree, encoding="utf-8", xml_declaration=True)

    # 3. Extract all xmlns and xmlns:prefix declarations from source root element
    root_match = re.search(rb"<([a-zA-Z0-9_:-]+)\b([^>]*)>", raw_entry)
    if not root_match:
        return serialized

    root_attrs_raw = root_match.group(2).decode("utf-8", errors="ignore")
    source_xmlns = re.findall(r'(xmlns(?::[a-zA-Z0-9_.-]+)?)=["\']([^"\']+)["\']', root_attrs_raw)
    if not source_xmlns:
        return serialized

    # Check which xmlns declarations are present in the serialized root tag
    ser_match = re.search(rb"<([a-zA-Z0-9_:-]+)\b([^>]*)>", serialized)
    if not ser_match:
        return serialized

    ser_attrs_raw = ser_match.group(2).decode("utf-8", errors="ignore")
    existing_xmlns_attrs = set(re.findall(r'(xmlns(?::[a-zA-Z0-9_.-]+)?)=', ser_attrs_raw))

    missing_xmlns = []
    for attr_name, uri in source_xmlns:
        if attr_name not in existing_xmlns_attrs:
            missing_xmlns.append(f'{attr_name}="{uri}"')

    if missing_xmlns:
        injection = (" " + " ".join(missing_xmlns)).encode("utf-8")
        root_end = ser_match.end() - 1
        if serialized[root_end - 1 : root_end] == b"/":
            root_end -= 1
        return serialized[:root_end] + injection + serialized[root_end:]

    return serialized


def transform_docx_artifact(
    input_bytes: bytes,
    converter_fn: Callable[[str], str],
    filename: str,
    role: str = "converted_document",
    warnings: list[WarningRecord] | None = None,
    preserve_modern_fonts: bool | None = None,
    preserve_typography: bool = False,
    legacy_target_font: str | None = None,
    profiles: Mapping[str, Any] | None = None,
    font_resolver: Callable[..., str | None] | None = None,
    profile_resolver: Callable[..., tuple[str | None, str | None]] | None = None,
) -> ArtifactPayload:
    """Transform an existing DOCX file in-place, preserving OpenXML layout and document structure."""
    try:
        in_buf = io.BytesIO(input_bytes)
        out_buf = io.BytesIO()
        should_preserve_modern = preserve_modern_fonts if preserve_modern_fonts is not None else (role == "converted_document")

        with zipfile.ZipFile(in_buf, "r") as in_zf, zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as out_zf:
            styles_xml = in_zf.read("word/styles.xml") if "word/styles.xml" in in_zf.namelist() else None
            style_resolver = DocxStyleResolver(styles_xml, font_resolver=font_resolver)

            for item in in_zf.infolist():
                raw_entry = in_zf.read(item.filename)

                # Process visible story parts: document, headers, footers, footnotes, endnotes, comments
                is_target_xml = (
                    item.filename == "word/document.xml"
                    or (item.filename.startswith("word/header") and item.filename.endswith(".xml"))
                    or (item.filename.startswith("word/footer") and item.filename.endswith(".xml"))
                    or (item.filename.startswith("word/footnotes") and item.filename.endswith(".xml"))
                    or (item.filename.startswith("word/endnotes") and item.filename.endswith(".xml"))
                    or (item.filename.startswith("word/comments") and item.filename.endswith(".xml"))
                )

                if is_target_xml:
                    try:
                        tree = ET.fromstring(raw_entry)
                        _transform_xml_tree(
                            tree,
                            converter_fn,
                            preserve_modern_fonts=should_preserve_modern,
                            preserve_typography=preserve_typography,
                            style_resolver=style_resolver,
                            legacy_target_font=legacy_target_font,
                            profiles=profiles,
                            font_resolver=font_resolver,
                            profile_resolver=profile_resolver,
                        )
                        updated_entry = _serialize_xml_preserving_namespaces(tree, raw_entry)
                        out_zf.writestr(item, updated_entry)
                        continue
                    except ET.ParseError as exc:
                        if item.filename == "word/document.xml":
                            raise DoshError(
                                code=FailureCode.VALIDATION_FAILED,
                                message="Failed to parse main DOCX document body XML.",
                            ) from exc
                        if warnings is not None:
                            warnings.append(
                                WarningRecord(
                                    code="DOCX_PART_CONVERSION_FAILED",
                                    message=f"Failed to parse and convert DOCX part: {item.filename}",
                                    stage="docx_exporter",
                                )
                            )

                out_zf.writestr(item, raw_entry)

        return ArtifactPayload(
            intent=ArtifactIntent(name=filename, role=role, media_type=_DOCX_MIME_TYPE),
            content=out_buf.getvalue(),
        )
    except Exception as exc:
        if isinstance(exc, DoshError):
            raise
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Failed to transform DOCX document structure.",
        ) from exc


def normalize_font_family(font_name: str | None) -> str:
    """Normalize a font family name for visual style equality comparisons."""
    if not font_name:
        return ""
    return "".join(c for c in font_name.lower() if c.isalnum())


def _get_run_visual_style(r: ET.Element) -> tuple:
    rpr = r.find(f"{{{_W_NS}}}rPr")
    if rpr is None:
        return ()
    style_tags = []
    for child in rpr:
        tag_name = child.tag.split("}")[-1]
        if tag_name in ("b", "bCs", "i", "iCs", "u", "strike", "dstrike", "color", "highlight", "sz", "szCs"):
            val = child.attrib.get(f"{{{_W_NS}}}val", "true")
            style_tags.append((tag_name, val))
        elif tag_name == "rFonts":
            fonts = tuple(sorted({
                normalize_font_family(v)
                for k, v in child.attrib.items()
                if k.split("}")[-1] in ("ascii", "cs", "hAnsi", "eastAsia") and v and normalize_font_family(v)
            }))
            if fonts:
                style_tags.append(("rFonts", str(fonts)))
    return tuple(sorted(style_tags))


def _merge_adjacent_compatible_runs(container: ET.Element) -> None:
    """Merge adjacent compatible <w:r> elements without deleting semantic nodes."""
    r_tag = f"{{{_W_NS}}}r"
    t_tag = f"{{{_W_NS}}}t"

    children = list(container)
    if len(children) < 2:
        return

    i = 0
    while i < len(container) - 1:
        c1 = container[i]
        c2 = container[i + 1]
        if c1.tag == r_tag and c2.tag == r_tag:
            # Check if c2 contains any non-deletable child
            has_non_deletable = any(
                child.tag.split("}")[-1] in _NON_DELETABLE_RUN_CHILDREN
                for child in c2
            )
            style1 = _get_run_visual_style(c1)
            style2 = _get_run_visual_style(c2)
            if style1 == style2:
                t1 = c1.find(t_tag)
                t2 = c2.find(t_tag)
                if t1 is not None and t2 is not None and t2.text:
                    t1.text = (t1.text or "") + t2.text
                    if not has_non_deletable:
                        container.remove(c2)
                        continue
                    else:
                        t2.text = ""
        i += 1


def _classify_run_font(
    font_name: str | None,
    profiles: Mapping[str, Any] | None = None,
    profile_resolver: Callable[..., tuple[str | None, str | None]] | None = None,
) -> tuple[str | None, str | None]:
    """Classify run font as modern, legacy profile, or unknown."""
    if profile_resolver is not None:
        return profile_resolver(font_name, profiles)
    if not font_name or not font_name.strip():
        return None, None
    cleaned = "".join(c for c in font_name.lower() if c.isalnum())
    if not cleaned:
        return None, None
    if cleaned in _KNOWN_MODERN_FONTS:
        return None, "modern"
    if profiles:
        cleaned_base = re.sub(r"(normal|regular|bold|italic|oblique|medium)$", "", cleaned)
        for prof in profiles.values():
            aliases = getattr(prof, "aliases", ())
            name = getattr(prof, "name", "")
            pid = getattr(prof, "profile_id", "")
            fam = getattr(prof, "family", "legacy")
            cand_keys = [pid, name] + list(aliases)
            for cand in cand_keys:
                cand_cleaned = "".join(c for c in cand.lower() if c.isalnum())
                if cleaned == cand_cleaned or cleaned_base == cand_cleaned:
                    return pid, fam
    return None, "unknown"


_DEFAULT_PROFILES_LOADER: Callable[[], Mapping[str, Any]] | None = None
_CACHED_NEUTRAL_PROFILES: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class NeutralFontProfile:
    """Lightweight metadata for font profile symbols and aliases."""

    profile_id: str
    family: str
    name: str
    aliases: tuple[str, ...] = ()
    symbols: Mapping[str, str] = field(default_factory=dict)


def register_default_profiles_loader(loader: Callable[[], Mapping[str, Any]]) -> None:
    """Register a provider/loader for default font profiles via Dependency Injection."""
    global _DEFAULT_PROFILES_LOADER
    _DEFAULT_PROFILES_LOADER = loader


def _load_neutral_font_profiles() -> dict[str, NeutralFontProfile]:
    global _CACHED_NEUTRAL_PROFILES
    if _CACHED_NEUTRAL_PROFILES is not None:
        return _CACHED_NEUTRAL_PROFILES

    fonts_dir = Path(__file__).resolve().parents[4] / "data" / "fonts"
    profiles: dict[str, NeutralFontProfile] = {}
    if fonts_dir.exists():
        for json_file in fonts_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    pid = str(data.get("profile_id", "")).strip()
                    if pid:
                        profiles[pid] = NeutralFontProfile(
                            profile_id=pid,
                            family=str(data.get("family", "legacy")),
                            name=str(data.get("name", pid)),
                            aliases=tuple(str(a) for a in data.get("aliases", ())),
                            symbols=dict(data.get("symbols", {})),
                        )
            except Exception:
                continue

    _CACHED_NEUTRAL_PROFILES = profiles
    return profiles


def get_default_profiles() -> Mapping[str, Any]:
    """Retrieve default font profiles, falling back to neutral data/fonts profiles."""
    if _DEFAULT_PROFILES_LOADER is not None:
        try:
            return _DEFAULT_PROFILES_LOADER()
        except Exception:
            pass
    return _load_neutral_font_profiles()


def _transform_xml_tree(
    tree: ET.Element,
    converter_fn: Callable[[str], str],
    preserve_modern_fonts: bool = False,
    preserve_typography: bool = False,
    style_resolver: DocxStyleResolver | None = None,
    legacy_target_font: str | None = None,
    profiles: Mapping[str, Any] | None = None,
    font_resolver: Callable[..., str | None] | None = None,
    profile_resolver: Callable[..., tuple[str | None, str | None]] | None = None,
) -> None:
    """Transform paragraphs and runs within an ElementTree OpenXML element."""
    p_tag = f"{{{_W_NS}}}p"
    r_tag = f"{{{_W_NS}}}r"
    t_tag = f"{{{_W_NS}}}t"
    sym_tag = f"{{{_W_NS}}}sym"
    rpr_tag = f"{{{_W_NS}}}rPr"
    rfonts_tag = f"{{{_W_NS}}}rFonts"
    sz_tag = f"{{{_W_NS}}}sz"
    szcs_tag = f"{{{_W_NS}}}szCs"

    profiles = profiles if profiles is not None else get_default_profiles()

    import inspect
    converter_takes_font = False
    try:
        sig = inspect.signature(converter_fn)
        converter_takes_font = len(sig.parameters) >= 2 or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
    except Exception:
        converter_takes_font = False

    # Process all containers that can hold runs (paragraphs, table cells, hyperlinks, sdt)
    for p in tree.iter(p_tag):
        # Merge runs at paragraph level and within sub-containers like w:hyperlink
        _merge_adjacent_compatible_runs(p)
        for sub_container in p.findall(f"{{{_W_NS}}}hyperlink"):
            _merge_adjacent_compatible_runs(sub_container)

        # Iterate all runs in paragraph (including nested)
        for parent in [p] + p.findall(f"{{{_W_NS}}}hyperlink"):
            children = list(parent)
            for child in children:
                if child.tag != r_tag:
                    continue

                # 1. Check and convert <w:sym> elements
                for sym in list(child.findall(sym_tag)):
                    sym_font = sym.attrib.get(f"{{{_W_NS}}}font")
                    sym_char = sym.attrib.get(f"{{{_W_NS}}}char")
                    if sym_font and sym_char:
                        prof_id, _ = _classify_run_font(sym_font, profiles, profile_resolver)
                        if prof_id and profiles and prof_id in profiles:
                            prof = profiles[prof_id]
                            hex_code = sym_char.upper()
                            if hex_code in prof.symbols:
                                mapped_char = prof.symbols[hex_code]
                                s_idx = list(child).index(sym)
                                child.remove(sym)
                                new_t = ET.Element(t_tag)
                                new_t.attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
                                new_t.text = mapped_char
                                child.insert(s_idx, new_t)

                # 2. Check text inside run
                t_elems = child.findall(t_tag)
                if not t_elems:
                    continue

                full_run_text = "".join(t.text for t in t_elems if t.text)
                if not full_run_text:
                    continue

                # Resolve effective font name using StyleResolver
                effective_font: str | None = None
                if style_resolver is not None:
                    effective_font = style_resolver.resolve_run_font(
                        child, p, text=full_run_text, font_resolver=font_resolver
                    )
                if not effective_font:
                    rpr = child.find(rpr_tag)
                    if rpr is not None:
                        rf = rpr.find(rfonts_tag)
                        if rf is not None:
                            if font_resolver is not None:
                                effective_font = font_resolver(
                                    ascii_font=rf.attrib.get(f"{{{_W_NS}}}ascii"),
                                    hansi_font=rf.attrib.get(f"{{{_W_NS}}}hAnsi"),
                                    cs_font=rf.attrib.get(f"{{{_W_NS}}}cs"),
                                    run_text=full_run_text,
                                    profiles=profiles,
                                )
                            else:
                                effective_font = resolve_neutral_ooxml_font(
                                    ascii_font=rf.attrib.get(f"{{{_W_NS}}}ascii"),
                                    hansi_font=rf.attrib.get(f"{{{_W_NS}}}hAnsi"),
                                    cs_font=rf.attrib.get(f"{{{_W_NS}}}cs"),
                                    run_text=full_run_text,
                                )

                # Detect if run font is modern or legacy
                resolved_prof, fam = _classify_run_font(effective_font, profiles, profile_resolver)
                is_modern_run = (fam == "modern") and preserve_modern_fonts

                if is_modern_run:
                    converted_text = full_run_text
                else:
                    if converter_takes_font and effective_font:
                        converted_text = converter_fn(full_run_text, font_name=effective_font)
                    else:
                        converted_text = converter_fn(full_run_text)

                if legacy_target_font:
                    raw_segments = segment_text_by_script(full_run_text)
                    segments: list[tuple[str, bool]] = []
                    for raw_chunk, is_dev in raw_segments:
                        if is_dev:
                            if converter_takes_font and effective_font:
                                conv_chunk = converter_fn(raw_chunk, font_name=effective_font)
                            else:
                                conv_chunk = converter_fn(raw_chunk)
                            segments.append((conv_chunk, True))
                        else:
                            segments.append((raw_chunk, False))
                else:
                    segments = segment_text_by_script(converted_text)

                if not segments:
                    for t in t_elems:
                        t.text = ""
                    continue

                rpr = child.find(rpr_tag)
                if rpr is None:
                    rpr = ET.Element(rpr_tag)
                    child.insert(0, rpr)

                # If unconverted legacy text remains untouched (converted_text == full_run_text and not modern),
                # do not disguise it as modern formatting.
                is_unconverted_legacy = (
                    not legacy_target_font
                    and converted_text == full_run_text
                    and fam != "modern"
                    and not any(_DEVANAGARI_CHAR_RE.match(c) for c in converted_text)
                )

                if len(segments) == 1:
                    chunk, is_dev = segments[0]
                    if not is_unconverted_legacy:
                        _apply_font_to_rpr(
                            rpr,
                            is_dev,
                            rfonts_tag,
                            sz_tag,
                            szcs_tag,
                            preserve_typography=preserve_typography,
                            legacy_target_font=legacy_target_font,
                            source_font=effective_font,
                            style_resolver=style_resolver,
                            p=p,
                        )
                    t_elems[0].text = chunk
                    t_elems[0].attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
                    for extra_t in t_elems[1:]:
                        child.remove(extra_t)
                else:
                    chunk0, is_dev0 = segments[0]
                    orig_rpr_xml = ET.tostring(rpr)

                    if not is_unconverted_legacy:
                        _apply_font_to_rpr(
                            rpr,
                            is_dev0,
                            rfonts_tag,
                            sz_tag,
                            szcs_tag,
                            preserve_typography=preserve_typography,
                            legacy_target_font=legacy_target_font,
                            source_font=effective_font,
                            style_resolver=style_resolver,
                            p=p,
                        )
                    t_elems[0].text = chunk0
                    t_elems[0].attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
                    for extra_t in t_elems[1:]:
                        child.remove(extra_t)

                    c_idx = list(parent).index(child)
                    for offset, (chunk, is_dev) in enumerate(segments[1:], start=1):
                        new_r = ET.Element(r_tag)
                        new_rpr = ET.fromstring(orig_rpr_xml)
                        if not is_unconverted_legacy:
                            _apply_font_to_rpr(
                                new_rpr,
                                is_dev,
                                rfonts_tag,
                                sz_tag,
                                szcs_tag,
                                preserve_typography=preserve_typography,
                                legacy_target_font=legacy_target_font,
                                source_font=effective_font,
                                style_resolver=style_resolver,
                                p=p,
                            )
                        new_r.append(new_rpr)
                        new_t = ET.Element(t_tag)
                        new_t.attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
                        new_t.text = chunk
                        new_r.append(new_t)
                        parent.insert(c_idx + offset, new_r)


def _apply_font_to_rpr(
    rpr: ET.Element,
    is_devanagari: bool,
    rfonts_tag: str,
    sz_tag: str,
    szcs_tag: str,
    preserve_typography: bool = False,
    legacy_target_font: str | None = None,
    source_font: str | None = None,
    style_resolver: DocxStyleResolver | None = None,
    p: ET.Element | None = None,
) -> None:
    """Set font on a <w:rPr> element, dynamically normalizing size according to calibration table."""
    if legacy_target_font:
        font = legacy_target_font if is_devanagari else _ENGLISH_FONT
    else:
        font = _HINDI_FONT if is_devanagari else _ENGLISH_FONT

    # Fonts
    rfonts = rpr.find(rfonts_tag)
    if rfonts is None:
        rfonts = ET.SubElement(rpr, rfonts_tag)
    rfonts.attrib[f"{{{_W_NS}}}ascii"] = font
    rfonts.attrib[f"{{{_W_NS}}}hAnsi"] = font
    rfonts.attrib[f"{{{_W_NS}}}cs"] = font

    # Size: only standardize if preserve_typography is False
    if not preserve_typography:
        size_str = str(_DEFAULT_HALF_PT)
        sz = rpr.find(sz_tag)
        if sz is None:
            sz = ET.SubElement(rpr, sz_tag)
        sz.attrib[f"{{{_W_NS}}}val"] = size_str

        szcs = rpr.find(szcs_tag)
        if szcs is None:
            szcs = ET.SubElement(rpr, szcs_tag)
        szcs.attrib[f"{{{_W_NS}}}val"] = size_str
    else:
        # Dynamic visual font-size normalization preserving document hierarchy
        adj = get_font_size_adjustment(
            anchor_font=source_font or "",
            target_font=font,
        )

        cur_half_pt: float | None = None
        sz_elem = rpr.find(sz_tag)
        if sz_elem is not None and f"{{{_W_NS}}}val" in sz_elem.attrib:
            try:
                cur_half_pt = float(sz_elem.attrib[f"{{{_W_NS}}}val"])
            except ValueError:
                pass
        elif style_resolver is not None:
            cur_half_pt = style_resolver.resolve_run_size_half_pt(rpr, p)

        if cur_half_pt is not None and (adj.scale != 1.0 or adj.offset_pt != 0.0):
            cur_pt = cur_half_pt / 2.0
            adj_pt = adj.apply(cur_pt)
            new_half_pt = max(2, int(round(adj_pt * 2.0)))
            size_str = str(new_half_pt)

            if sz_elem is None:
                sz_elem = ET.SubElement(rpr, sz_tag)
            sz_elem.attrib[f"{{{_W_NS}}}val"] = size_str

            szcs = rpr.find(szcs_tag)
            if szcs is None:
                szcs = ET.SubElement(rpr, szcs_tag)
            szcs.attrib[f"{{{_W_NS}}}val"] = size_str
