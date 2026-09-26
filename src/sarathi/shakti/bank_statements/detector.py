"""Bank Statement and Profile Detector.

Performs deterministic multi-signal evidence-backed detection to distinguish
bank statements from non-bank content and identify the specific bank profile.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sarathi.sankalpa import CanonicalDocument
from sarathi.shakti.bank_statements.bank_registry import get_bank_registry
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


def detect_bank_statement(
    document: CanonicalDocument,
    banks_dir: Path | None = None,
    profiles: Sequence[dict[str, Any]] | None = None,
) -> DetectionEvidence:
    """Analyze a CanonicalDocument and determine if it represents a bank statement.

    Examines full document text, metadata, and extracted tables against bank keywords,
    negative non-bank indicators, and bank profile patterns.

    Args:
        document: Canonical document extracted from native file or OCR.
        banks_dir: Optional path to bank profiles directory.
        profiles: Optional pre-loaded bank profile dictionaries. If None, loaded from banks_dir.

    Returns:
        DetectionEvidence with factual classification and matched profile.
    """
    profiles = list(profiles) if profiles is not None else load_bank_profiles(banks_dir)

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

    src_hint = (
        str(document.metadata.get("source_name", ""))
        + " "
        + str(document.metadata.get("source_path", ""))
        + " "
        + str(document.document_id or "")
    ).strip()
    composite_raw = document.text + " " + " ".join(table_texts)
    if src_hint:
        composite_raw = composite_raw + " " + src_hint
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

    meta_headers: list[str] = []
    for t in all_tables:
        if t.name:
            meta_headers.append(t.name)
        if t.headers:
            meta_headers.append(" ".join(str(h) for h in t.headers))
        for r in t.rows[:3]:
            meta_headers.append(" ".join(str(c) for c in r))
    if document.pages:
        for p in document.pages[:2]:
            if p.text:
                meta_headers.append(p.text[:1500])

    bank_ident_text = (document.text[:3000] + " " + " ".join(meta_headers) + " " + src_hint).lower()

    # Collect all table header and cell strings from first 20 rows of all tables
    table_cell_tokens: set[str] = set()
    table_col_counts: set[int] = set()
    for t in all_tables:
        if t.headers:
            table_col_counts.add(len(t.headers))
            for h in t.headers:
                if h is not None:
                    h_str = str(h).strip().strip('"').strip("'").lower()
                    if h_str:
                        table_cell_tokens.add(h_str)
        for r in t.rows[:20]:
            table_col_counts.add(len(r))
            for c in r:
                if c is not None:
                    c_str = str(c).strip().strip('"').strip("'").lower()
                    if c_str:
                        table_cell_tokens.add(c_str)

    all_candidates: list[dict[str, Any]] = []

    for prof in profiles:
        prof_id = prof.get("profile_id", "")
        bank_name = prof.get("bank_name", prof_id)
        parent_bank = prof.get("parent_bank", prof_id)
        prof_container = prof.get("container_format", "").lower()
        doc_type = (document.detected_type or "").lower()
        if doc_type in ("xlsx", "xls", "xls_legacy", "html_table", "xml"):
            doc_type = "excel"
        elif doc_type in ("csv", "csv_or_text", "tsv", "delimited"):
            doc_type = "csv"
        if prof_container and doc_type and prof_container != doc_type:
            continue

        all_kw = prof.get("identification_keywords", []) + prof.get("aliases", [])
        matches = []
        for kw in all_kw:
            kw_clean = str(kw).strip().lower()
            if not kw_clean:
                continue
            if kw_clean == "bank of india":
                if re.search(r"\b(?<!state\s)(?<!union\s)(?<!central\s)(?<!reserve\s)bank\s+of\s+india\b", bank_ident_text):
                    matches.append(kw)
            elif len(kw_clean) <= 4:
                if re.search(rf"\b{re.escape(kw_clean)}\b", bank_ident_text):
                    matches.append(kw)
            else:
                if kw_clean in bank_ident_text:
                    matches.append(kw)

        # Check table header role matches
        prof_headers = prof.get("headers", {})
        matched_header_roles = 0
        for _role, synonyms in prof_headers.items():
            if any(str(syn).strip().lower() in table_cell_tokens for syn in synonyms):
                matched_header_roles += 1

        # Check column count
        col_count_matched = False
        sig = prof.get("layout_signature", {})
        exp_cols = sig.get("column_count", {}).get("expected")
        if exp_cols and exp_cols in table_col_counts:
            col_count_matched = True

        if not matches:
            continue

        cand_score = 0.1 * len(matches)
        cand_reasons = [f"Matched bank profile '{prof_id}' ({bank_name}) on keywords {matches[:4]}."]

        if prof_container and doc_type and prof_container == doc_type:
            cand_score += 0.2
            cand_reasons.append(f"Matched container format '{doc_type}'.")

        if matched_header_roles > 0:
            cand_score += 0.12 * matched_header_roles
            cand_reasons.append(f"Matched {matched_header_roles} table header column definitions.")

        if col_count_matched:
            cand_score += 0.1
            cand_reasons.append(f"Matched expected column count {exp_cols}.")

        patterns = prof.get("metadata_patterns", {})
        search_target = composite_raw if composite_raw.strip() else document.text

        m_acc_val: str | None = None
        if "account_number" in patterns:
            m_acc = re.search(patterns["account_number"], search_target, re.IGNORECASE)
            if m_acc:
                m_acc_val = m_acc.group(1).strip()
                cand_score += 0.25
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

        all_candidates.append({
            "score": round(cand_score, 3),
            "profile_id": prof_id,
            "bank_name": bank_name,
            "parent_bank": parent_bank,
            "acc_num": m_acc_val,
            "acc_holder": m_holder_val,
            "ifsc": m_ifsc_val,
            "reasons": cand_reasons,
            "matched_header_roles": matched_header_roles,
            "matches_count": len(matches),
        })

    if all_candidates:
        all_candidates.sort(
            key=lambda c: (
                c["score"],
                c["matched_header_roles"],
                1 if c["acc_num"] else 0,
                c["matches_count"],
            ),
            reverse=True,
        )
        best = all_candidates[0]
        # Check if there is an exact tie with a competing candidate of a different parent bank
        competing_ties = [
            c
            for c in all_candidates[1:]
            if c["score"] == best["score"]
            and c["matched_header_roles"] == best["matched_header_roles"]
            and (bool(c["acc_num"]) == bool(best["acc_num"]))
            and c["parent_bank"] != best["parent_bank"]
        ]
        if not competing_ties:
            score += best["score"]
            matched_profile_id = best["profile_id"]
            matched_bank_name = best["bank_name"]
            raw_acc_num = best["acc_num"]
            raw_acc_holder = best["acc_holder"]
            raw_ifsc = best["ifsc"]
            reasons.extend(best["reasons"])
        else:
            # Exact tie between competing profiles of different banks
            tied_names = [best["profile_id"]] + [c["profile_id"] for c in competing_ties]
            cand_score = best["score"]
            matched_profile_id = "generic"
            matched_bank_name = None
            score += cand_score
            reasons.append(
                f"Ambiguous bank profiles with identical evidence score ({cand_score:.2f}): {tied_names}. Defaulted to generic profile."
            )

    has_signed = (
        any(t in table_cell_tokens for t in ("cr/dr", "dr/cr", "cr / dr", "dr / cr", "type", "txn type", "cr dr", "dr cr"))
        and any(t in table_cell_tokens for t in ("amount", "txn amount", "transaction amount"))
        and not (
            any(t in table_cell_tokens for t in ("debit", "withdrawal", "withdrawals"))
            and any(t in table_cell_tokens for t in ("credit", "deposit", "deposits"))
        )
    )
    universal_profile = "universal_signed_amount" if has_signed else "universal_dual_amount"

    if score >= 0.4 and (matched_profile_id is None or matched_profile_id == "generic"):
        matched_profile_id = universal_profile

    target_dir = banks_dir.resolve() if banks_dir is not None else _CANONICAL_BANKS_DIR
    common_cfg = load_bank_profile_yaml(target_dir / "common.yaml")
    gen_patterns = common_cfg.get("metadata_patterns", {})
    search_target = composite_raw if composite_raw.strip() else document.text
    if raw_acc_num is None and "account_number" in gen_patterns:
        m_acc = re.search(gen_patterns["account_number"], search_target, re.IGNORECASE)
        if m_acc:
            raw_acc_num = m_acc.group(1).strip()
    if raw_acc_holder is None and "account_holder" in gen_patterns:
        m_holder = re.search(gen_patterns["account_holder"], search_target, re.IGNORECASE)
        if m_holder:
            raw_acc_holder = m_holder.group(1).strip()
    if raw_ifsc is None and "ifsc" in gen_patterns:
        m_ifsc = re.search(gen_patterns["ifsc"], search_target, re.IGNORECASE)
        if m_ifsc:
            raw_ifsc = m_ifsc.group(1).strip()

    # Resolve bank name strictly against the official Indian bank registry
    catalog_path = target_dir / "banks_catalog.json"
    registry = get_bank_registry(catalog_path if catalog_path.exists() else None)
    search_target = composite_raw if composite_raw.strip() else document.text
    canonical_bank = registry.identify_bank(
        text=search_target,
        ifsc=raw_ifsc,
        candidate_name=matched_bank_name,
    )

    if canonical_bank:
        matched_bank_name = canonical_bank
        reasons.append(f"Identified bank '{matched_bank_name}' from official Indian bank registry.")
    elif score >= 0.4:
        matched_bank_name = "Unknown Bank"
        reasons.append(
            "Bank could not be identified against the compiled list of Indian banks. Marked as 'Unknown Bank'."
        )
    else:
        matched_bank_name = None

    account_identity: AccountIdentity | None = None
    if matched_bank_name:
        account_identity = create_account_identity(
            bank_name=matched_bank_name,
            raw_account_number=raw_acc_num,
            account_holder=raw_acc_holder,
            bank_profile=matched_profile_id or "generic",
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
