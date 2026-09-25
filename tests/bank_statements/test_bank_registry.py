"""Tests for Canonical Indian Bank Master Registry in Sarathi."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.shakti.bank_statements.bank_registry import BankRegistry, get_bank_registry


@pytest.fixture
def registry() -> BankRegistry:
    return get_bank_registry()


def test_registry_loads_all_158_canonical_banks(registry: BankRegistry) -> None:
    """Registry must load all 158 RBI-recognized Indian banks from banks_catalog.json."""
    assert registry.total_banks == 158
    assert len(registry.canonical_names) == 158
    assert "State Bank of India" in registry.canonical_names
    assert "HDFC Bank Limited" in registry.canonical_names
    assert "ICICI Bank Limited" in registry.canonical_names
    assert "Punjab National Bank" in registry.canonical_names
    assert "Bank of Baroda" in registry.canonical_names
    assert "Canara Bank" in registry.canonical_names
    assert "Au Small Finance Bank Limited" in registry.canonical_names
    assert "Paytm Payments Bank Limited" in registry.canonical_names
    assert "Citibank N.A." in registry.canonical_names
    assert "The Maharashtra State Co-operative Bank Ltd." in registry.canonical_names


@pytest.mark.parametrize(
    ("ifsc", "expected_bank"),
    [
        ("SBIN0001234", "State Bank of India"),
        ("HDFC0000001", "HDFC Bank Limited"),
        ("ICIC0000123", "ICICI Bank Limited"),
        ("UTIB0000001", "Axis Bank Limited"),
        ("PUNB0123400", "Punjab National Bank"),
        ("BARB0KOLKAT", "Bank of Baroda"),
        ("CNRB0001234", "Canara Bank"),
        ("UBIN0530123", "Union Bank of India"),
        ("BKID0001001", "Bank of India"),
        ("CBIN0280001", "Central Bank of India"),
        ("KKBK0000123", "Kotak Mahindra Bank Limited"),
        ("IDFB0000123", "IDFC FIRST Bank Limited"),
        ("YESB0000001", "YES Bank Limited"),
        ("AUBL0002134", "Au Small Finance Bank Limited"),
        ("PYTM0123456", "Paytm Payments Bank Limited"),
        ("AIRP0000001", "Airtel Payments Bank Limited"),
        ("CITI0000001", "Citibank N.A."),
        ("SCBL0036001", "Standard Chartered Bank"),
        ("HSBC0110001", "Hong Kong and Shanghai Banking Corporation Limited"),
    ],
)
def test_identify_bank_by_ifsc_code(registry: BankRegistry, ifsc: str, expected_bank: str) -> None:
    """Authoritative IFSC 4-letter prefix must resolve directly to canonical bank name."""
    assert registry.identify_bank(ifsc=ifsc) == expected_bank


@pytest.mark.parametrize(
    ("candidate", "expected_bank"),
    [
        ("State Bank of India", "State Bank of India"),
        ("HDFC Bank", "HDFC Bank Limited"),
        ("HDFC Bank Limited", "HDFC Bank Limited"),
        ("ICICI Bank", "ICICI Bank Limited"),
        ("Axis Bank", "Axis Bank Limited"),
        ("Punjab National Bank", "Punjab National Bank"),
        ("Bank of Baroda", "Bank of Baroda"),
        ("Kotak Mahindra Bank", "Kotak Mahindra Bank Limited"),
        ("Kotak Bank", "Kotak Mahindra Bank Limited"),
        ("Canara Bank", "Canara Bank"),
        ("Union Bank", "Union Bank of India"),
        ("IDFC First Bank", "IDFC FIRST Bank Limited"),
        ("AU Small Finance Bank", "Au Small Finance Bank Limited"),
        ("Standard Chartered", "Standard Chartered Bank"),
        ("Citibank", "Citibank N.A."),
    ],
)
def test_identify_bank_by_candidate_name(registry: BankRegistry, candidate: str, expected_bank: str) -> None:
    """Candidate names and colloquial aliases must resolve to official canonical bank names."""
    assert registry.identify_bank(candidate_name=candidate) == expected_bank


def test_identify_bank_from_document_text(registry: BankRegistry) -> None:
    """Document text containing bank names, aliases, or embedded IFSC must resolve properly."""
    # Text with bank name
    assert (
        registry.identify_bank(text="Welcome to State Bank of India Account Statement for Ramesh")
        == "State Bank of India"
    )
    # Text with colloquial alias
    assert (
        registry.identify_bank(text="Detailed transaction report from HDFC Bank for customer")
        == "HDFC Bank Limited"
    )
    # Text with embedded IFSC pattern
    assert (
        registry.identify_bank(text="Customer Account Summary IFSC Code: PUNB0123400 Branch: New Delhi")
        == "Punjab National Bank"
    )


def test_identify_bank_unrecognized_returns_none(registry: BankRegistry) -> None:
    """Unrecognized text, generic headers, or non-bank text must return None."""
    assert registry.identify_bank(text="Account Statement\nDate | Narration | Debit | Credit | Balance") is None
    assert registry.identify_bank(text="XYZ Enterprises Pvt Ltd\nTax Invoice") is None
    assert registry.identify_bank(candidate_name="Random Excel Header") is None
    assert registry.identify_bank(candidate_name="Generic Bank") is None


def test_is_canonical_bank_name(registry: BankRegistry) -> None:
    """is_canonical_bank_name must return True strictly for official compiled bank names."""
    assert registry.is_canonical_bank_name("State Bank of India") is True
    assert registry.is_canonical_bank_name("HDFC Bank Limited") is True
    assert registry.is_canonical_bank_name("Generic Bank") is False
    assert registry.is_canonical_bank_name("Unknown Bank") is False
    assert registry.is_canonical_bank_name("Random Header") is False
    assert registry.is_canonical_bank_name(None) is False


def test_capability_identifies_canonical_bank_and_warns_on_unknown(tmp_path: Path) -> None:
    """Capability must emit canonical bank name for known banks and emit Unknown Bank with warning otherwise."""
    from sarathi.sankalpa import (
        CanonicalDocument,
        ExecutionContext,
        InputRef,
        PageData,
        Request,
        Result,
        TableData,
    )
    from sarathi.shakti.bank_statements.capability import BankStatementCapability
    from sarathi.shakti.bank_statements.models import ValidationStatus

    cap = BankStatementCapability()

    # 1. Statement with unidentifiable bank
    unknown_text = "Account Statement\nAccount Number: 1122334455\n"
    unknown_table = TableData(
        rows=(
            ("Date", "Description", "Debit", "Credit", "Balance"),
            ("01/01/2026", "OPENING BALANCE", "", "", "10,000.00"),
            ("05/01/2026", "TEST DEBIT", "500.00", "", "9,500.00"),
        )
    )
    unknown_doc = CanonicalDocument(
        document_id="doc-unknown",
        text=unknown_text,
        tables=(unknown_table,),
        pages=(PageData(page_number=1, text=unknown_text, tables=(unknown_table,)),),
        source_input_id="inp-unknown",
    )

    prior_unknown = Result(data=(unknown_doc,))
    req_u = Request(
        request_id="req-u",
        requirement="bank_statements",
        inputs=(InputRef("inp-unknown", Path("unknown.xlsx"), "unknown.xlsx", 100),),
    )
    res_u = cap.execute(req_u, ExecutionContext("run-u", "req-u", "t1", "s1"), prior_result=prior_unknown)
    stmt_u = res_u.data.statements[0]
    assert stmt_u.bank_name == "Unknown Bank"
    assert any(iss.code == "UNKNOWN_BANK" for iss in stmt_u.issues)
    assert stmt_u.status == ValidationStatus.WARNING
    assert all(tx.bank_name == "Unknown Bank" for tx in stmt_u.transactions)

    # 2. Statement with identifiable bank via text/IFSC
    known_text = "CANARA BANK Account Statement\nAccount Number: 9988776655\nIFSC: CNRB0001234\n"
    known_table = TableData(
        rows=(
            ("Date", "Description", "Debit", "Credit", "Balance"),
            ("01/01/2026", "OPENING BALANCE", "", "", "20,000.00"),
            ("06/01/2026", "TEST SALARY", "", "50,000.00", "70,000.00"),
        )
    )
    known_doc = CanonicalDocument(
        document_id="doc-known",
        text=known_text,
        tables=(known_table,),
        pages=(PageData(page_number=1, text=known_text, tables=(known_table,)),),
        source_input_id="inp-known",
    )

    prior_known = Result(data=(known_doc,))
    req_k = Request(
        request_id="req-k",
        requirement="bank_statements",
        inputs=(InputRef("inp-known", Path("canara.xlsx"), "canara.xlsx", 100),),
    )
    res_k = cap.execute(req_k, ExecutionContext("run-k", "req-k", "t1", "s1"), prior_result=prior_known)
    stmt_k = res_k.data.statements[0]
    assert stmt_k.bank_name == "Canara Bank"
    assert not any(iss.code == "UNKNOWN_BANK" for iss in stmt_k.issues)
    assert all(tx.bank_name == "Canara Bank" for tx in stmt_k.transactions)
