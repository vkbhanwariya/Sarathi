"""Tests for Run Stitching, Split Akshara Resolution, and Semantic Node Preservation."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from sarathi.shakti.docx_exporter import (
    _W_NS,
    _merge_adjacent_compatible_runs,
)
from sarathi.shakti.font_conversion.converter import FontConverter


def test_two_run_split_akshara_stitching() -> None:
    """Verify prefix matra 'f' in run 1 and consonant 'd' in run 2 stitch and convert to 'कि'."""
    p = ET.Element(f"{{{_W_NS}}}p")

    # Run 1: 'f'
    r1 = ET.SubElement(p, f"{{{_W_NS}}}r")
    rpr1 = ET.SubElement(r1, f"{{{_W_NS}}}rPr")
    rf1 = ET.SubElement(rpr1, f"{{{_W_NS}}}rFonts")
    rf1.attrib[f"{{{_W_NS}}}ascii"] = "Kruti Dev 010"
    t1 = ET.SubElement(r1, f"{{{_W_NS}}}t")
    t1.text = "f"

    # Run 2: 'd'
    r2 = ET.SubElement(p, f"{{{_W_NS}}}r")
    rpr2 = ET.SubElement(r2, f"{{{_W_NS}}}rPr")
    rf2 = ET.SubElement(rpr2, f"{{{_W_NS}}}rFonts")
    rf2.attrib[f"{{{_W_NS}}}ascii"] = "Kruti Dev 010"
    t2 = ET.SubElement(r2, f"{{{_W_NS}}}t")
    t2.text = "d"

    assert len(p.findall(f"{{{_W_NS}}}r")) == 2
    _merge_adjacent_compatible_runs(p)
    assert len(p.findall(f"{{{_W_NS}}}r")) == 1

    merged_t = p.find(f".//{{{_W_NS}}}t")
    assert merged_t is not None and merged_t.text == "fd"

    converter = FontConverter()
    assert converter.convert(merged_t.text, profile_id="krutidev010") == "कि"


def test_three_run_split_akshara_stitching() -> None:
    """Verify 3 compatible runs stitch across a complex word cluster."""
    p = ET.Element(f"{{{_W_NS}}}p")

    # Three runs forming "Hkkjr" (भारत): "Hk" + "k" + "jr"
    parts = ["Hk", "k", "jr"]
    for part in parts:
        r = ET.SubElement(p, f"{{{_W_NS}}}r")
        rpr = ET.SubElement(r, f"{{{_W_NS}}}rPr")
        rf = ET.SubElement(rpr, f"{{{_W_NS}}}rFonts")
        rf.attrib[f"{{{_W_NS}}}ascii"] = "Kruti Dev 010"
        t = ET.SubElement(r, f"{{{_W_NS}}}t")
        t.text = part

    assert len(p.findall(f"{{{_W_NS}}}r")) == 3
    _merge_adjacent_compatible_runs(p)
    assert len(p.findall(f"{{{_W_NS}}}r")) == 1

    merged_t = p.find(f".//{{{_W_NS}}}t")
    assert merged_t is not None and merged_t.text == "Hkkjr"
    converter = FontConverter()
    assert converter.convert(merged_t.text, profile_id="krutidev010") == "भारत"


def test_incompatible_runs_not_stitched() -> None:
    """Verify runs with different visual styles (e.g. bold vs non-bold or different sz) are NOT stitched."""
    p = ET.Element(f"{{{_W_NS}}}p")

    # Run 1: bold
    r1 = ET.SubElement(p, f"{{{_W_NS}}}r")
    rpr1 = ET.SubElement(r1, f"{{{_W_NS}}}rPr")
    ET.SubElement(rpr1, f"{{{_W_NS}}}b")
    t1 = ET.SubElement(r1, f"{{{_W_NS}}}t")
    t1.text = "f"

    # Run 2: not bold
    r2 = ET.SubElement(p, f"{{{_W_NS}}}r")
    ET.SubElement(r2, f"{{{_W_NS}}}rPr")
    t2 = ET.SubElement(r2, f"{{{_W_NS}}}t")
    t2.text = "d"

    _merge_adjacent_compatible_runs(p)
    # Must remain 2 separate runs to preserve visual distinction
    assert len(p.findall(f"{{{_W_NS}}}r")) == 2


def test_non_deletable_run_children_preserved() -> None:
    """Verify runs containing <w:tab>, <w:drawing>, or <w:br> are never removed from XML DOM."""
    p = ET.Element(f"{{{_W_NS}}}p")

    # Run 1: normal text
    r1 = ET.SubElement(p, f"{{{_W_NS}}}r")
    ET.SubElement(r1, f"{{{_W_NS}}}rPr")
    t1 = ET.SubElement(r1, f"{{{_W_NS}}}t")
    t1.text = "Item"

    # Run 2: text + tab
    r2 = ET.SubElement(p, f"{{{_W_NS}}}r")
    ET.SubElement(r2, f"{{{_W_NS}}}rPr")
    t2 = ET.SubElement(r2, f"{{{_W_NS}}}t")
    t2.text = " Details"
    ET.SubElement(r2, f"{{{_W_NS}}}tab")

    assert len(p.findall(f"{{{_W_NS}}}r")) == 2
    _merge_adjacent_compatible_runs(p)

    # Run 2 MUST NOT be deleted because it contains a <w:tab>!
    runs = p.findall(f"{{{_W_NS}}}r")
    assert len(runs) == 2
    # Text merged into run 1
    assert runs[0].find(f"{{{_W_NS}}}t").text == "Item Details"
    # Run 2 text cleared, but tab element remains intact
    assert runs[1].find(f"{{{_W_NS}}}t").text == ""
    assert runs[1].find(f"{{{_W_NS}}}tab") is not None
