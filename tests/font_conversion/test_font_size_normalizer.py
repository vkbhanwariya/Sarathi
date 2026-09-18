"""Unit tests for Font Conversion visual font-size normalization."""

import pytest

from sarathi.shakti.docx_exporter.font_size_normalizer import (
    FontSizeAdjustment,
    get_font_size_adjustment,
    normalize_font_name,
    normalize_font_size,
)


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("Times New Roman", "times new roman"),
        ("  TIMES   NEW   ROMAN  ", "times new roman"),
        ("Kruti Dev 010", "kruti dev 010"),
        ("  nirmala   ui ", "nirmala ui"),
        ("", ""),
    ],
)
def test_font_name_normalization(raw_name: str, expected: str) -> None:
    """Verify defensive whitespace trimming and case-folding."""
    assert normalize_font_name(raw_name) == expected


def test_identity_fallback_unknown_pair() -> None:
    """Unknown font pairs must safely fall back to 1.0 scale and 0.0 offset."""
    adj = get_font_size_adjustment(anchor_font="Comic Sans", target_font="Times New Roman")
    assert adj.scale == 1.0
    assert adj.offset_pt == 0.0

    res = normalize_font_size(14.0, anchor_font="Comic Sans", target_font="Times New Roman")
    assert res == pytest.approx(14.0)


@pytest.mark.parametrize(
    ("source_size", "anchor_font", "target_font", "expected_size"),
    [
        (16.0, "Kruti Dev 010", "Times New Roman", 12.0),
        (24.0, "Kruti Dev 010", "Nirmala UI", 18.0),
        (12.0, "Times New Roman", "Kruti Dev 010", 16.0),
        (16.0, "DevLys 010", "Nirmala UI", 12.0),
        (20.0, "DevLys 010", "Nirmala UI", 15.0),
        (12.0, "Nirmala UI", "DevLys 010", 16.0),
        (16.0, "Nirmala UI", "Times New Roman", 16.0),
        (12.0, "Times New Roman", "Nirmala UI", 12.0),
    ],
)
def test_font_pair_baselines(
    source_size: float, anchor_font: str, target_font: str, expected_size: float
) -> None:
    """Verify legacy-to-modern and modern-to-modern baseline scaling rules."""
    res = normalize_font_size(source_size, anchor_font=anchor_font, target_font=target_font)
    assert res == pytest.approx(expected_size)


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
