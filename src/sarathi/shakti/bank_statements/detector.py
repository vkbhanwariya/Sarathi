"""Bank Statement and Profile Detector.

Performs deterministic multi-signal evidence-backed detection to distinguish
bank statements from non-bank content and identify the specific bank profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
import yaml

from sarathi.sankalpa import CanonicalDocument
from sarathi.shakti.bank_statements.models import AccountIdentity, create_account_identity

_CANONICAL_BANKS_DIR = Path(__file__).resolve().parents[4] / "data" / "banks"

_BANK_KEYWORD_SCORE = 0.3
_TABLE_HEADER_SCORE = 0.4
_ACCOUNT_METADATA_SCORE = 0.3

_BANK_INDICATORS = {
    "account statement",
    "statement of account",
    "bank statement",
    "transaction details",
    "account summary",
    "statement period",
    "opening balance",
    "closing balance",
    "clear balance",
    "drawing power",
    "mod balance",
    "cif no",
    "ifsc code",
    "micr code",
    "nomination",
}

_NON_BANK_INDICATORS = {
    "tax invoice",
    "bill of supply",
    "invoice number",
    "loan amortisation schedule",
    "repayment schedule",
    "credit card statement",
    "minimum amount due",
    "credit limit",
    "available credit",
    "purchase order",
}


@dataclass(frozen=True, slots=True)
class DetectionEvidence:
    """Factual evidence gathered during bank statement detection."""

    is_bank_statement: bool
    confidence_score: float
    matched_profile: str | None
    bank_name: str | None
    account_identity: AccountIdentity | None
    matched_keywords: tuple[str, ...]
    reasons: tuple[str, ...]


def load_bank_profiles(banks_dir: Path | None = None) -> list[dict[str, Any]]:
    """Discover and load all bank profile YAML configurations from data/banks/."""
    target_dir = banks_dir.resolve() if banks_dir is not None else _CANONICAL_BANKS_DIR
    if not target_dir.exists():
        return []

    profiles = []
    for yaml_file in target_dir.glob("*.yaml"):
        if yaml_file.name == "common.yaml":
            continue
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "profile_id" in data:
                profiles.append(data)
        except Exception:
            continue
    return profiles


def detect_bank_statement(document: CanonicalDocument, banks_dir: Path | None = None) -> DetectionEvidence:
    """Analyze a CanonicalDocument and determine if it represents a bank statement.

    Examines full document text, metadata, and extracted tables against bank keywords,
    negative non-bank indicators, and bank profile patterns.

    Args:
        document: Canonical document extracted from native file or OCR.
        banks_dir: Optional path to bank profiles directory.

    Returns:
        DetectionEvidence with factual classification and matched profile.
    """
    profiles = load_bank_profiles(banks_dir)
    full_text = document.text.lower()

    # 1. Check for negative non-bank indicators
    non_bank_matches = [kw for kw in _NON_BANK_INDICATORS if kw in full_text]
    if len(non_bank_matches) >= 2 and "bank statement" not in full_text:
        return DetectionEvidence(
            is_bank_statement=False,
            confidence_score=0.1,
            matched_profile=None,
            bank_name=None,
            account_identity=None,
            matched_keywords=tuple(non_bank_matches),
            reasons=("Document matched multiple non-bank document indicators (e.g. invoice/credit card/loan schedule).",),
        )

    matched_keywords: list[str] = [kw for kw in _BANK_INDICATORS if kw in full_text]
    reasons: list[str] = []
    score = min(_BANK_KEYWORD_SCORE, len(matched_keywords) * 0.1) if matched_keywords else 0.0
    if matched_keywords:
        reasons.append(f"Matched {len(matched_keywords)} general bank statement keywords: {matched_keywords[:4]}.")

    # 2. Check for transaction table structures across doc.tables, pages, or text lines
    has_transaction_headers = False
    all_tables = list(document.tables)
    for page in document.pages:
        all_tables.extend(page.tables)

    for table in all_tables:
        if table.rows:
            header_str = " ".join(str(c).lower().strip() for c in table.rows[0])
            has_date = any(d in header_str for d in ("date", "txn", "दिनांक", "तारीख"))
            has_debit_credit = any(dc in header_str for dc in ("debit", "credit", "withdrawal", "deposit", "dr", "cr"))
            has_balance = any(b in header_str for b in ("balance", "bal", "शेष"))
            if (has_date and has_debit_credit) or (has_date and has_balance):
                has_transaction_headers = True
                break

    if not has_transaction_headers and document.text:
        for line in document.text.splitlines():
            l_lower = line.lower()
            if ("date" in l_lower or "txn" in l_lower) and ("debit" in l_lower or "credit" in l_lower or "balance" in l_lower):
                has_transaction_headers = True
                break

    if has_transaction_headers:
        score += _TABLE_HEADER_SCORE
        reasons.append("Detected valid transaction table headers with Date and Debit/Credit/Balance columns.")

    # 3. Bank Profile Identification
    matched_profile_id: str | None = None
    matched_bank_name: str | None = None
    raw_acc_num: str | None = None
    raw_acc_holder: str | None = None

    for prof in profiles:
        all_kw = prof.get("identification_keywords", []) + prof.get("aliases", [])
        matches = [kw for kw in all_kw if kw.lower() in full_text]
        if matches:
            matched_profile_id = prof.get("profile_id")
            matched_bank_name = prof.get("bank_name")
            score += 0.2
            reasons.append(f"Matched bank profile '{matched_profile_id}' ({matched_bank_name}) on keywords {matches}.")

            patterns = prof.get("metadata_patterns", {})
            if "account_number" in patterns:
                m_acc = re.search(patterns["account_number"], document.text, re.IGNORECASE)
                if m_acc:
                    raw_acc_num = m_acc.group(1).strip()
                    score += 0.1
                    reasons.append("Extracted account number pattern.")

            if "account_holder" in patterns:
                m_holder = re.search(patterns["account_holder"], document.text, re.IGNORECASE)
                if m_holder:
                    raw_acc_holder = m_holder.group(1).strip()
                    reasons.append(f"Extracted account holder: {raw_acc_holder}")
            break

    if score >= 0.5 and matched_profile_id is None:
        matched_profile_id = "generic"
        matched_bank_name = "Generic Bank"

    account_identity: AccountIdentity | None = None
    if matched_bank_name:
        account_identity = create_account_identity(
            bank_name=matched_bank_name,
            raw_account_number=raw_acc_num,
            account_holder=raw_acc_holder,
            bank_profile=matched_profile_id,
        )

    return DetectionEvidence(
        is_bank_statement=score >= 0.5,
        confidence_score=min(1.0, score),
        matched_profile=matched_profile_id,
        bank_name=matched_bank_name,
        account_identity=account_identity,
        matched_keywords=tuple(matched_keywords),
        reasons=tuple(reasons),
    )
