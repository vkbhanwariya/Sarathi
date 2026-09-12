"""Unit tests for Font Conversion visual font-size normalization."""

import pytest

from sarathi.shakti.docx_exporter.font_size_normalizer import (
    FontSizeAdjustment,
    get_font_size_adjustment,
    normalize_font_name,
    normalize_font_size,
)


def test_font_name_normalization() -> None:
    """Verify defensive whitespace trimming and case-folding."""
    assert normalize_font_name("Times New Roman") == "times new roman"
    assert normalize_font_name("  TIMES   NEW   ROMAN  ") == "times new roman"
    assert normalize_font_name("Kruti Dev 010") == "kruti dev 010"
    assert normalize_font_name("  nirmala   ui ") == "nirmala ui"
    assert normalize_font_name("") == ""


def test_identity_fallback_unknown_pair() -> None:
    """Unknown font pairs must safely fall back to 1.0 scale and 0.0 offset."""
    adj = get_font_size_adjustment(anchor_font="Comic Sans", target_font="Times New Roman")
    assert adj.scale == 1.0
    assert adj.offset_pt == 0.0

    res = normalize_font_size(14.0, anchor_font="Comic Sans", target_font="Times New Roman")
    assert res == pytest.approx(14.0)


def test_kruti_dev_pair_baseline() -> None:
    """Kruti Dev 010 <-> Times New Roman / Nirmala UI: 16 pt maps to 12 pt (scale 0.75)."""
    res = normalize_font_size(16.0, anchor_font="Kruti Dev 010", target_font="Times New Roman")
    assert res == pytest.approx(12.0)

    # Heading scaling preserved (24 pt -> 18 pt)
    res_heading = normalize_font_size(24.0, anchor_font="Kruti Dev 010", target_font="Nirmala UI")
    assert res_heading == pytest.approx(18.0)

    # Reverse pair (12 pt -> 16 pt)
    res_rev = normalize_font_size(12.0, anchor_font="Times New Roman", target_font="Kruti Dev 010")
    assert res_rev == pytest.approx(16.0)


def test_devlys_pair_baseline() -> None:
    """DevLys 010 <-> Nirmala UI / Times New Roman: 16 pt maps to 12 pt (scale 0.75)."""
    res = normalize_font_size(16.0, anchor_font="DevLys 010", target_font="Nirmala UI")
    assert res == pytest.approx(12.0)

    # Title scaling preserved (20 pt -> 15 pt)
    res_title = normalize_font_size(20.0, anchor_font="DevLys 010", target_font="Nirmala UI")
    assert res_title == pytest.approx(15.0)

    # Reverse pair (12 pt -> 16 pt)
    res_rev = normalize_font_size(12.0, anchor_font="Nirmala UI", target_font="DevLys 010")
    assert res_rev == pytest.approx(16.0)


def test_nirmala_ui_pair_baseline() -> None:
    """Nirmala UI <-> Times New Roman: modern-to-modern baseline scale is strictly 1.0."""
    res = normalize_font_size(16.0, anchor_font="Nirmala UI", target_font="Times New Roman")
    assert res == pytest.approx(16.0)

    res_rev = normalize_font_size(12.0, anchor_font="Times New Roman", target_font="Nirmala UI")
    assert res_rev == pytest.approx(12.0)


def test_case_and_whitespace_insensitivity_in_lookup() -> None:
    """Lookup must match regardless of casing or extra whitespace."""
    res = normalize_font_size(
        16.0,
        anchor_font="  KRUTI   DEV 010  ",
        target_font="  times new roman ",
    )
    assert res == pytest.approx(12.0)



def test_invalid_font_size_rejected() -> None:
    """Font sizes <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="greater than zero"):
        normalize_font_size(0.0, anchor_font="Kruti Dev 010", target_font="Times New Roman")

    with pytest.raises(ValueError, match="greater than zero"):
        normalize_font_size(-2.5, anchor_font="Kruti Dev 010", target_font="Times New Roman")


def test_formula_behavior_synthetic_adjustment() -> None:
    """Verify formula calculation: logical_size * scale + offset_pt."""
    adj = FontSizeAdjustment(scale=0.95, offset_pt=0.25)
    assert adj.apply(10.0) == pytest.approx(9.75)
