"""Bank Statement and Profile Detector.

Performs deterministic multi-signal evidence-backed detection to distinguish
bank statements from non-bank content and identify the specific bank profile.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sarathi.sankalpa import CanonicalDocument
from sarathi.shakti.bank_statements.mapper import load_bank_profile_yaml
from sarathi.shakti.bank_statements.models import AccountIdentity, create_account_identity
from sarathi.sutra import get_canonical_data_root

_CANONICAL_BANKS_DIR = get_canonical_data_root() / "banks"

_BANK_KEYWORD_SCORE = 0.3
_TABLE_HEADER_SCORE = 0.4
_ACCOUNT_METADATA_SCORE = 0.3

_BANK_INDICATORS = {
    "account number",
    "account statement",
    "statement of account",
    "bank statement",
    "transaction details",
    "available balance",
    "closing balance",
    "opening balance",
    "debit",
    "credit",
    "cheque no",
    "withdrawal",
    "deposit",
    "ifsc",
    "micr",
    "branch",
    "value date",
    "particulars",
}

_NON_BANK_INDICATORS = {
    "invoice",
    "bill to",
    "ship to",
    "tax invoice",
    "purchase order",
    "credit card statement",
    "payment receipt",
    "delivery challan",
    "bill of supply",
    "loan account statement",
    "total amount due",
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
    ifsc: str | None = None


def load_bank_profiles(banks_dir: Path | None = None) -> list[dict[str, Any]]:
    """Discover and load all bank profile YAML configurations from data/banks/."""
    target_dir = banks_dir.resolve() if banks_dir is not None else _CANONICAL_BANKS_DIR
    if not target_dir.exists():
        return []

    profiles = []
    for yaml_file in sorted(target_dir.glob("*.yaml")):
        if yaml_file.name == "common.yaml":
            continue
        data = load_bank_profile_yaml(yaml_file)
        if isinstance(data, dict) and "profile_id" in data:
            profiles.append(data)
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

    all_tables = list(document.tables)
    for page in document.pages:
        all_tables.extend(page.tables)

    # Build composite text from full text, pages, and structured table headers/cells
    table_texts: list[str] = []
    for t in all_tables:
        if t.headers:
            table_texts.append(" ".join(str(h) for h in t.headers))
        for r in t.rows:
            table_texts.append(" ".join(str(c) for c in r))
    for p in document.pages:
        if p.text:
            table_texts.append(p.text)

    composite_raw = document.text + " " + " ".join(table_texts)
    full_text = composite_raw.lower()

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
            reasons=(
                "Document matched multiple non-bank document indicators (e.g. invoice/credit card/loan schedule).",
            ),
        )

    matched_keywords: list[str] = [kw for kw in _BANK_INDICATORS if kw in full_text]
    reasons: list[str] = []
    score = min(_BANK_KEYWORD_SCORE, len(matched_keywords) * 0.1) if matched_keywords else 0.0
    if matched_keywords:
        reasons.append(f"Matched {len(matched_keywords)} general bank statement keywords: {matched_keywords[:4]}.")

    # 2. Check for transaction table structures across doc.tables, pages, or text lines
    has_transaction_headers = False
    for table in all_tables:
        candidates: list[str] = []
        if table.headers:
            candidates.append(" ".join(str(c).lower().strip() for c in table.headers))
        if table.rows:
            # Check up to the first 30 rows to accommodate Excel/CSV statements with preceding metadata
            for r in table.rows[:30]:
                candidates.append(" ".join(str(c).lower().strip() for c in r))

        for header_str in candidates:
            has_date = any(d in header_str for d in ("date", "txn", "दिनांक", "तारीख"))
            has_debit_credit = any(
                dc in header_str for dc in ("debit", "credit", "withdrawal", "deposit", "amount", "dr", "cr")
            )
            has_balance = any(b in header_str for b in ("balance", "bal", "शेष"))
            if (has_date and has_debit_credit) or (has_date and has_balance):
                has_transaction_headers = True
                break
        if has_transaction_headers:
            break

    if not has_transaction_headers and full_text:
        for line in full_text.splitlines():
            l_lower = line.lower()
            if ("date" in l_lower or "txn" in l_lower) and (
                "debit" in l_lower or "credit" in l_lower or "balance" in l_lower
            ):
                has_transaction_headers = True
                break

    if has_transaction_headers:
        score += _TABLE_HEADER_SCORE
        reasons.append("Detected valid transaction table headers with Date and Debit/Credit/Balance columns.")

    # 3. Bank Profile Identification via multi-signal best-match evidence scoring
    matched_profile_id: str | None = None
    matched_bank_name: str | None = None
    raw_acc_num: str | None = None
    raw_acc_holder: str | None = None
    raw_ifsc: str | None = None

    top_candidates: list[tuple[float, str, str, str | None, str | None, str | None, list[str]]] = []

    for prof in profiles:
        prof_id = prof.get("profile_id", "")
        bank_name = prof.get("bank_name", prof_id)
        all_kw = prof.get("identification_keywords", []) + prof.get("aliases", [])
        matches = [kw for kw in all_kw if kw.lower() in full_text]
        if not matches:
            continue

        cand_score = min(0.4, 0.15 * len(matches))
        cand_reasons = [f"Matched bank profile '{prof_id}' ({bank_name}) on keywords {matches[:4]}."]

        patterns = prof.get("metadata_patterns", {})
        search_target = composite_raw if composite_raw.strip() else document.text

        m_acc_val: str | None = None
        if "account_number" in patterns:
            m_acc = re.search(patterns["account_number"], search_target, re.IGNORECASE)
            if m_acc:
                m_acc_val = m_acc.group(1).strip()
                cand_score += 0.2
                cand_reasons.append("Extracted account number pattern.")

        m_holder_val: str | None = None
        if "account_holder" in patterns:
            m_holder = re.search(patterns["account_holder"], search_target, re.IGNORECASE)
            if m_holder:
                m_holder_val = m_holder.group(1).strip()
                cand_score += 0.1
                cand_reasons.append("Extracted account holder pattern.")

        m_ifsc_val: str | None = None
        if "ifsc" in patterns:
            m_ifsc = re.search(patterns["ifsc"], search_target, re.IGNORECASE)
            if m_ifsc:
                m_ifsc_val = m_ifsc.group(1).strip()
                cand_score += 0.1
                cand_reasons.append(f"Extracted IFSC pattern: {m_ifsc_val}")

        cand_tuple = (cand_score, prof_id, bank_name, m_acc_val, m_holder_val, m_ifsc_val, cand_reasons)
        if not top_candidates or cand_score > top_candidates[0][0]:
            top_candidates = [cand_tuple]
        elif cand_score == top_candidates[0][0]:
            top_candidates.append(cand_tuple)

    if top_candidates:
        if len(top_candidates) == 1:
            cand_score, matched_profile_id, matched_bank_name, raw_acc_num, raw_acc_holder, raw_ifsc, cand_reasons = (
                top_candidates[0]
            )
            score += cand_score
            reasons.extend(cand_reasons)
        else:
            # Exact tie between competing profiles: mark ambiguous, default to generic
            tied_names = [c[1] for c in top_candidates]
            cand_score = top_candidates[0][0]
            matched_profile_id = "generic"
            matched_bank_name = None
            score += cand_score
            reasons.append(
                f"Ambiguous bank profiles with identical evidence score ({cand_score:.2f}): {tied_names}. Defaulted to generic profile."
            )

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
            ifsc=raw_ifsc,
        )

    return DetectionEvidence(
        is_bank_statement=score >= 0.4,
        confidence_score=min(1.0, score),
        matched_profile=matched_profile_id,
        bank_name=matched_bank_name,
        account_identity=account_identity,
        matched_keywords=tuple(matched_keywords),
        reasons=tuple(reasons),
        ifsc=raw_ifsc,
    )
