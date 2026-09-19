"""Unit and Integration Tests for Visual Font Fallback and Metric Retrieval (Phase 4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.shakti.font_conversion.visual_resolver import (
    DEFAULT_FAMILY_THRESHOLDS,
    VECTOR_DIM,
    VisualFontEvidence,
    VisualFontResolver,
    _cosine_similarity,
    _unit_norm,
    deserialize_prototypes_bin,
    generate_seed_prototype,
    serialize_prototypes_bin,
)
from tools.benchmark_ocr_legacy_gold import (
    calculate_adaptive_dpi,
    compute_cer,
    compute_wer,
    run_synthetic_or_real_benchmark,
)


def test_unit_norm_and_cosine_similarity() -> None:
    """Verify vector math helpers satisfy unit norm and cosine properties."""
    v1 = [1.0, 2.0, 3.0]
    u1 = _unit_norm(v1)
    # Norm of u1 must be 1.0
    assert pytest.approx(sum(x * x for x in u1), rel=1e-5) == 1.0

    # Self similarity is 1.0
    assert pytest.approx(_cosine_similarity(u1, u1), rel=1e-5) == 1.0

    # Orthogonal similarity is 0.0
    u_orth = [-u1[1], u1[0], 0.0]
    u_orth_norm = _unit_norm(u_orth)
    assert pytest.approx(_cosine_similarity(u1, u_orth_norm), abs=1e-5) == 0.0


def test_serialize_and_deserialize_prototypes_bin(tmp_path: Path) -> None:
    """Verify binary serialization round-trip for legacy_prototypes.bin."""
    target_bin = tmp_path / "test_prototypes.bin"
    protos = {
        "krutidev010": (generate_seed_prototype("krutidev010"), 0.73),
        "devlys010": (generate_seed_prototype("devlys010"), 0.71),
    }
    serialize_prototypes_bin(protos, target_bin)
    assert target_bin.exists()

    loaded = deserialize_prototypes_bin(target_bin)
    assert len(loaded) == 2
    assert "krutidev010" in loaded
    assert "devlys010" in loaded
    assert loaded["krutidev010"][1] == pytest.approx(0.73, rel=1e-4)
    assert len(loaded["krutidev010"][0]) == VECTOR_DIM


def test_visual_resolver_open_set_rejection() -> None:
    """Verify that unknown/dissimilar text crops trigger open-set rejection."""
    resolver = VisualFontResolver()
    # Provide pure random/empty noise crops that don't match any profile
    noise_crops = [b"unseen_strange_noise_123456789"]

    evidence = resolver.resolve_font(noise_crops, doc_id="doc_test", font_xref=999)
    assert isinstance(evidence, VisualFontEvidence)
    assert evidence.evaluated_crops_count == 1
    # Max score on noise should not satisfy 0.70+ threshold
    assert evidence.is_unknown is True
    assert evidence.best_profile is None


def test_visual_resolver_exact_prototype_retrieval() -> None:
    """Verify that matching crop embeddings correctly retrieve candidate profile."""
    resolver = VisualFontResolver()

    # Create synthetic crop matching 'krutidev010' prototype
    target_pid = "krutidev010"
    target_vec, thresh = resolver._prototypes[target_pid]

    # Mock extract_crop_embedding to simulate a crop belonging to target profile
    original_extract = resolver.extract_crop_embedding
    resolver.extract_crop_embedding = lambda crop: list(target_vec)  # type: ignore[method-assign]

    try:
        evidence = resolver.resolve_font([b"crop_1", b"crop_2"], doc_id="doc_kruti", font_xref=10)
        assert evidence.is_unknown is False
        assert evidence.best_profile == target_pid
        assert evidence.confidence >= thresh
        assert evidence.evaluated_crops_count == 2
        assert len(evidence.candidates) == len(DEFAULT_FAMILY_THRESHOLDS)
        assert evidence.candidates[0].profile_id == target_pid
        assert evidence.candidates[0].passed is True
    finally:
        resolver.extract_crop_embedding = original_extract  # type: ignore[method-assign]


def test_visual_resolver_document_cache() -> None:
    """Verify that subsequent resolutions for the same doc and font_xref hit the cache."""
    resolver = VisualFontResolver()
    crops = [b"sample_crop_abc"]

    ev1 = resolver.resolve_font(crops, doc_id="doc_cached", font_xref=42)
    ev2 = resolver.resolve_font(crops, doc_id="doc_cached", font_xref=42)
    assert ev1 is ev2


def test_calculate_adaptive_dpi_normalization() -> None:
    """Verify glyph line-height content-adaptive DPI formula."""
    # Standard 32px height at 200 DPI -> 200 DPI
    assert calculate_adaptive_dpi(h_median=32.0, base_dpi=200) == 200

    # Very small font (16px) -> doubles DPI to 400
    assert calculate_adaptive_dpi(h_median=16.0, base_dpi=200) == 400

    # Extremely tiny font (10px) -> clamped to max 400 DPI
    assert calculate_adaptive_dpi(h_median=10.0, base_dpi=200) == 400

    # Large font (48px) -> clamped to min 150 DPI
    assert calculate_adaptive_dpi(h_median=48.0, base_dpi=200) == 150


def test_compute_cer_and_wer_metrics() -> None:
    """Verify Character Error Rate and Word Error Rate calculations."""
    gold = "भारत सरकार"
    assert compute_cer(gold, gold) == 0.0
    assert compute_wer(gold, gold) == 0.0

    # 1 character changed in 10 characters
    hyp_1_err = "भारत सरकोर"
    assert compute_cer(gold, hyp_1_err) > 0.0
    assert compute_cer(gold, hyp_1_err) <= 0.20
    # 1 word out of 2 words corrupted
    assert compute_wer(gold, hyp_1_err) == 0.50


def test_benchmark_ocr_dry_run_sweep() -> None:
    """Verify synthetic OCR benchmark sweep generates valid Pareto report."""
    report = run_synthetic_or_real_benchmark(dry_run=True)
    assert len(report.sweeps) == 6
    assert report.sweeps[0].dpi == 150
    assert report.sweeps[-1].dpi == 400
    # Accuracy should monotonically improve
    assert report.sweeps[-1].accuracy > report.sweeps[0].accuracy
    assert report.adaptive_dpi_recommended > 0
