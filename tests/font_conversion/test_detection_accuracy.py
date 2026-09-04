"""Tests for Legacy Font Detection Accuracy, Hints, and Schema Validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.font_conversion.detector import (
    _validate_and_compile_profile,
    decide_run_profile,
    load_font_profiles,
    rank_profiles_from_text,
    resolve_profile_from_font_name,
)


def test_schema_validation_duplicate_profile_id(tmp_path: Path) -> None:
    """Verify load_font_profiles rejects duplicate profile IDs."""
    data = {
        "profile_id": "dup010",
        "family": "krutidev",
        "name": "Dup Font",
        "aliases": ["dup font"],
        "prefixes": {},
        "postfix_reph": "Z",
        "reph_unicode": "र्",
        "mappings": {"k": "ा"},
    }
    seen_ids: set[str] = {"dup010"}
    seen_aliases: dict[str, str] = {}
    with pytest.raises(DoshError) as exc_info:
        _validate_and_compile_profile(data, "dup.json", seen_ids, seen_aliases)
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION
    assert "Duplicate font profile_id" in exc_info.value.message


def test_schema_validation_alias_collision(tmp_path: Path) -> None:
    """Verify load_font_profiles rejects alias collisions across profiles."""
    data = {
        "profile_id": "font2",
        "family": "krutidev",
        "name": "Font Two",
        "aliases": ["shared_alias"],
        "prefixes": {},
        "postfix_reph": "Z",
        "reph_unicode": "र्",
        "mappings": {"k": "ा"},
    }
    seen_ids: set[str] = set()
    seen_aliases: dict[str, str] = {"sharedalias": "font1"}
    with pytest.raises(DoshError) as exc_info:
        _validate_and_compile_profile(data, "font2.json", seen_ids, seen_aliases)
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION
    assert "conflicts with profile" in exc_info.value.message


def test_schema_validation_missing_required_fields() -> None:
    """Verify profile loader rejects JSON files missing mandatory fields."""
    data = {
        "profile_id": "incomplete010",
        # Missing family, name, prefixes, etc.
    }
    with pytest.raises(DoshError) as exc_info:
        _validate_and_compile_profile(data, "incomplete.json", set(), {})
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION
    assert "missing a valid" in exc_info.value.message


def test_resolve_profile_from_font_name() -> None:
    """Verify trusted font resolution independent of digraph evidence."""
    profiles = load_font_profiles()

    # Exact legacy alias match
    prof_id, fam = resolve_profile_from_font_name("Kruti Dev 010", profiles)
    assert prof_id == "krutidev010"
    assert fam == "krutidev"

    prof_id_d, fam_d = resolve_profile_from_font_name("DevLys 010 Normal", profiles)
    assert prof_id_d == "devlys010"
    assert fam_d == "devlys"

    # Known modern Unicode font
    prof_m, fam_m = resolve_profile_from_font_name("Mangal", profiles)
    assert prof_m is None
    assert fam_m == "modern"

    prof_c, fam_c = resolve_profile_from_font_name("Calibri", profiles)
    assert prof_c is None
    assert fam_c == "modern"

    # Generic or unknown font
    prof_u, fam_u = resolve_profile_from_font_name("UnknownCustomFont", profiles)
    assert prof_u is None
    assert fam_u == "unknown"


def test_exact_font_plus_short_text_decision() -> None:
    """Verify exact legacy font alias enables conversion on short text runs."""
    profiles = load_font_profiles()
    decision = decide_run_profile(
        run_font="Kruti Dev 010",
        run_text="d",  # single character 'क'
        doc_profile=None,
        profiles=profiles,
    )
    assert decision.decision == "convert"
    assert decision.profile == "krutidev010"
    assert decision.reason == "exact_source_font_alias"


def test_modern_font_override_preserves_even_with_legacy_doc_profile() -> None:
    """Verify modern fonts (Mangal, Arial, etc.) are never converted even if document has legacy hint."""
    profiles = load_font_profiles()
    for modern in ("Mangal", "Aparajita", "Kokila", "Arial", "Times New Roman", "Calibri"):
        decision = decide_run_profile(
            run_font=modern,
            run_text="Hkkjr",  # text might even contain legacy digraphs
            doc_profile="krutidev010",
            profiles=profiles,
        )
        assert decision.decision == "preserve"
        assert decision.reason == "known_modern_unicode_font"


def test_krutidev_vs_devlys_ambiguity_detection() -> None:
    """Verify tie between KrutiDev and DevLys without font alias returns ambiguous."""
    profiles = load_font_profiles()
    # "Hkkjr ljdkj" has identical mappings in KrutiDev and DevLys
    decision = decide_run_profile(
        run_font=None,
        run_text="Hkkjr ljdkj",
        doc_profile=None,
        profiles=profiles,
    )
    assert decision.decision == "ambiguous"
    assert decision.reason == "conflicting_profile_evidence"
    assert decision.candidate_rank == 1


def test_krutidev_vs_devlys_disambiguated_by_doc_hint() -> None:
    """Verify KrutiDev vs DevLys tie is resolved when document-level font hint is provided."""
    profiles = load_font_profiles()
    decision = decide_run_profile(
        run_font=None,
        run_text="Hkkjr ljdkj",
        doc_profile="devlys010",
        profiles=profiles,
    )
    assert decision.decision == "convert"
    assert decision.profile == "devlys010"
    assert decision.reason == "exact_source_font_alias"


def test_rank_profiles_negative_signatures_penalize() -> None:
    """Verify candidate scoring strictly penalizes negative signatures."""
    profiles = load_font_profiles()
    # Chanakya text tested against KrutiDev
    chanakya_sample = "¥æð °ð Ûæ ÿæ"
    candidates = rank_profiles_from_text(chanakya_sample, profiles)
    assert candidates[0].profile_id == "chanakya010"
    kruti_cand = next((c for c in candidates if c.profile_id == "krutidev010"), None)
    assert kruti_cand is not None
    assert len(kruti_cand.negative_signatures) > 0
    assert kruti_cand.score < 0
