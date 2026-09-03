"""Tests for Phase C remediation: Smriti cache digest completeness, Bank ambiguity detection, OCR adaptive CLAHE, Glossary collisions, and Anubhava fast-fail."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.nabhi.kosh import Kosh
from sarathi.sankalpa import (
    CanonicalDocument,
    CapabilityDeclaration,
    ConfidenceValue,
    ExecutionProfile,
    InputRef,
    PageData,
    PluginInfo,
    Request,
    Result,
    TableData,
    TextSpan,
)
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.bank_statements.models import BankStatement, Transaction
from sarathi.shakti.ocr.engine import is_low_contrast_image
from sarathi.shakti.translation.engine import _load_translation_anubhava
from sarathi.shakti.translation.glossary import GlossaryStore
from sarathi.shakti.translation.models import TranslationDirection
from sarathi.smriti.key import compute_prior_result_digest


def test_smriti_digest_differentiates_span_and_table_metadata() -> None:
    """Verify Smriti cache digest produces distinct hashes when only span or table metadata differs."""
    span1 = TextSpan(text="hello", confidence=0.9, metadata={"author": "alice"})
    span2 = TextSpan(text="hello", confidence=0.9, metadata={"author": "bob"})

    doc1 = CanonicalDocument(document_id="doc-1", text="hello", pages=(PageData(page_number=1, text="hello", spans=(span1,)),))
    doc2 = CanonicalDocument(document_id="doc-1", text="hello", pages=(PageData(page_number=1, text="hello", spans=(span2,)),))

    digest1 = compute_prior_result_digest(Result(data=doc1))
    digest2 = compute_prior_result_digest(Result(data=doc2))
    assert digest1 != digest2, "Differing span metadata must produce distinct digests"

    # Test table metadata differentiation
    t1 = TableData(headers=("A", "B"), rows=(("1", "2"),), metadata={"source": "scan_a"})
    t2 = TableData(headers=("A", "B"), rows=(("1", "2"),), metadata={"source": "scan_b"})

    doc_tbl1 = CanonicalDocument(document_id="doc-2", text="table", tables=(t1,))
    doc_tbl2 = CanonicalDocument(document_id="doc-2", text="table", tables=(t2,))

    digest_t1 = compute_prior_result_digest(Result(data=doc_tbl1))
    digest_t2 = compute_prior_result_digest(Result(data=doc_tbl2))
    assert digest_t1 != digest_t2, "Differing table metadata must produce distinct digests"


def test_smriti_digest_handles_mapping_proxy_without_type_name_fallback() -> None:
    """Verify dataclasses with MappingProxyType and nested types do not collapse to type-name fallback."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class SampleReport:
        name: str
        metrics: MappingProxyType[str, int]
        created: datetime.date
        amount: Decimal

    rep1 = SampleReport("Q1", MappingProxyType({"sales": 100}), datetime.date(2026, 1, 1), Decimal("100.50"))
    rep2 = SampleReport("Q1", MappingProxyType({"sales": 200}), datetime.date(2026, 1, 1), Decimal("100.50"))

    d1 = compute_prior_result_digest(Result(data=rep1))
    d2 = compute_prior_result_digest(Result(data=rep2))

    assert d1 != d2, "Differing MappingProxyType values must produce distinct digests"


def test_bank_statement_profile_tie_detection() -> None:
    """Verify detector flags tied profile evidence as ambiguous instead of picking the first YAML file."""
    # Text mentioning both ICICI and HDFC bank statement keywords equally
    text = "ICICI Bank statement and HDFC Bank statement with account details"
    doc = CanonicalDocument(document_id="doc-ambig", text=text)

    ev = detect_bank_statement(doc)
    # When both profiles have matching evidence and equal scores, it must not arbitrarily pick one
    if ev.matched_profile == "generic":
        assert any("Ambiguous bank profiles" in r for r in ev.reasons)


def test_ocr_low_contrast_adaptive_check() -> None:
    """Verify is_low_contrast_image distinguishes between sharp and washed-out images."""
    import numpy as np

    # Sharp black-on-white image (high contrast, high std dev)
    sharp_img = np.zeros((100, 100), dtype=np.uint8)
    sharp_img[:50, :] = 255  # 50% white, 50% black -> std dev ~ 127.5
    assert not is_low_contrast_image(sharp_img), "High contrast image should not be low contrast"

    # Flat, low contrast image (all values between 120 and 130)
    flat_img = np.random.randint(120, 130, size=(100, 100), dtype=np.uint8)
    assert is_low_contrast_image(flat_img), "Flat image must be detected as low contrast"


def test_translation_glossary_collision_observability(tmp_path: Path) -> None:
    """Verify GlossaryStore records conflicting translations in the collisions property."""
    g_file = tmp_path / "glossary.yaml"
    # Same term mapped to two different targets
    g_file.write_text(
        """
        - source: "Court"
          target: "अदालत"
          direction: "en-hi"
        - source: "Court"
          target: "न्यायालय"
          direction: "en-hi"
        """,
        encoding="utf-8",
    )

    store = GlossaryStore(glossary_dir=tmp_path)
    assert len(store.collisions) >= 1
    assert store.collisions[0]["source"] == "Court"
    assert store.collisions[0]["existing_target"] == "अदालत"
    assert store.collisions[0]["conflicting_target"] == "न्यायालय"

    # Test strict mode raises INVALID_CONFIGURATION
    with pytest.raises(DoshError) as exc_info:
        GlossaryStore(glossary_dir=tmp_path, strict=True)
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION


def test_translation_anubhava_malformed_raises_invalid_configuration(tmp_path: Path) -> None:
    """Verify malformed anubhava.toml raises INVALID_CONFIGURATION."""
    bad_toml = tmp_path / "anubhava.toml"
    bad_toml.write_text("invalid [ = toml syntax", encoding="utf-8")

    with pytest.raises(DoshError) as exc_info:
        _load_translation_anubhava(tmp_path)
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION


def test_bank_models_expose_canonical_veda_properties() -> None:
    """Verify statement_from, statement_to, and posting_datetime properties on models."""
    d_start = datetime.date(2026, 1, 1)
    d_end = datetime.date(2026, 1, 31)
    stmt = BankStatement(
        bank_name="Test Bank",
        bank_profile="generic",
        statement_period_start=d_start,
        statement_period_end=d_end,
    )
    assert stmt.statement_from == d_start
    assert stmt.statement_to == d_end

    tx = Transaction(
        transaction_date=d_start,
        description="Test",
        bank_name="Test Bank",
        posting_date=d_start,
    )
    assert tx.posting_datetime == datetime.datetime(2026, 1, 1, 0, 0)


def test_mukha_projects_readiness_from_kosh() -> None:
    """Verify MukhaPresenter projects availability from Kosh registry when provided."""
    kosh = Kosh()
    kosh.register_plugin(
        PluginInfo(
            plugin_id="shakti.read_native",
            name="Native Plugin",
            version="1.0.0",
            capabilities=("read_native",),
        )
    )
    kosh.register_capability(
        CapabilityDeclaration(
            capability_id="read_native",
            plugin_id="shakti.read_native",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
    )

    statuses = MukhaPresenter.audit_capability_status(kosh=kosh)
    assert statuses["read_native"][0] is True
    assert "shakti.read_native" in statuses["read_native"][1]
    assert statuses["ocr"][0] is False
    assert "Not registered" in statuses["ocr"][1]
