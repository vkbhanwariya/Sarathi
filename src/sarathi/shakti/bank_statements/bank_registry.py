"""Canonical Indian Bank Master Registry for Sarathi.

Enforces strict bank name identification against the official catalog of all banks in India.
Any statement whose bank cannot be identified against this catalog is marked as 'Unknown Bank'
with an explicit non-fatal ValidationIssue warning.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_CANONICAL_BANKS_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "data" / "banks"
_CATALOG_FILE: Final[str] = "banks_catalog.json"

# Deterministic 4-letter IFSC prefix mapping to official canonical bank names
_IFSC_PREFIX_MAP: Final[dict[str, str]] = {
    "SBIN": "State Bank of India",
    "HDFC": "HDFC Bank Limited",
    "ICIC": "ICICI Bank Limited",
    "UTIB": "Axis Bank Limited",
    "PUNB": "Punjab National Bank",
    "BARB": "Bank of Baroda",
    "CNRB": "Canara Bank",
    "UBIN": "Union Bank of India",
    "BKID": "Bank of India",
    "CBIN": "Central Bank of India",
    "MAHB": "Bank of Maharashtra",
    "IOBA": "Indian Overseas Bank",
    "IDIB": "Indian Bank",
    "PSIB": "Punjab & Sind Bank",
    "UCBA": "UCO Bank",
    "KKBK": "Kotak Mahindra Bank Limited",
    "INDB": "IndusInd Bank Limited",
    "YESB": "YES Bank Limited",
    "IDFB": "IDFC FIRST Bank Limited",
    "FDRL": "Federal Bank Limited",
    "BDBL": "Bandhan Bank Limited",
    "IBKL": "IDBI Bank Limited",
    "KVBL": "Karur Vysya Bank Limited",
    "KARB": "Karnataka Bank Limited",
    "CSBK": "CSB Bank Limited",
    "CIUB": "City Union Bank Limited",
    "DCBL": "DCB Bank Limited",
    "DLXB": "Dhanlaxmi Bank Limited",
    "JAKA": "Jammu & Kashmir Bank Limited",
    "NTBL": "Nainital Bank Limited",
    "RATN": "RBL Bank Limited",
    "SIBL": "South Indian Bank Limited",
    "TMBL": "Tamilnad Mercantile Bank Limited",
    "AUBL": "Au Small Finance Bank Limited",
    "CSFB": "Capital Small Finance Bank Limited",
    "ESFB": "Equitas Small Finance Bank Limited",
    "ESAF": "ESAF Small Finance Bank Limited",
    "SURY": "Suryoday Small Finance Bank Limited",
    "UJVN": "Ujjivan Small Finance Bank Limited",
    "UTKS": "Utkarsh Small Finance Bank Limited",
    "JSFB": "Jana Small finance Bank Limited",
    "SMCB": "Shivalik Small Finance Bank Limited",
    "UNBA": "Unity Small Finance Bank Limited",
    "AIRP": "Airtel Payments Bank Limited",
    "IPOS": "India Post Payments Bank Limited",
    "FINO": "Fino Payments Bank Limited",
    "JIOP": "Jio Payments Bank Limited",
    "NSPB": "NSDL Payments Bank Limited",
    "PYTM": "Paytm Payments Bank Limited",
    "SCBL": "Standard Chartered Bank",
    "HSBC": "Hong Kong and Shanghai Banking Corporation Limited",
    "CITI": "Citibank N.A.",
    "BARC": "Barclays Bank Plc.",
    "DEUT": "Deutsche Bank A.G.",
    "DBSS": "DBS Bank India Limited (Subsidiary of DBS Bank Ltd.)",
    "CHAS": "J.P. Morgan Chase Bank N.A.",
    "AMEX": "American Express Banking Corporation",
    "ANZB": "Australia and New Zealand Banking Group Ltd.",
    "BNPA": "BNP Paribas",
    "BOTM": "MUFG Bank, Ltd.",
    "SMBC": "Sumitomo Mitsui Banking Corporation",
    "MHCB": "Mizuho Bank Ltd.",
    "SOCG": "Societe Generale",
    "DOHB": "Doha Bank Q.P.S.C",
    "EBIL": "Emirates NBD Bank P.J.S.C",
    "FABI": "First Abu Dhabi Bank PJSC",
    "FIRN": "FirstRand Bank Limited",
    "KKOO": "Kookmin Bank",
    "MSHQ": "Mashreqbank P.S.C",
    "QNBA": "Qatar National Bank (Q.P.S.C.)",
    "SABR": "Sberbank",
    "STCB": "SBM Bank (India) Limited (Subsidiary of SBM Group)",
    "SHBK": "Shinhan Bank",
    "UOVB": "United Overseas Bank Limited",
    "UBSW": "UBS AG",
    "HBNI": "KEB Hana Bank",
    "JCBL": "Jain Co-operative Bank Limited",
    "HDFC0CJCBL": "Jain Co-operative Bank Limited",
}

# Standard Indian banking acronyms and colloquial aliases mapped to canonical names
_CANONICAL_ALIASES: Final[dict[str, str]] = {
    "sbi": "State Bank of India",
    "state bank": "State Bank of India",
    "state bank of india": "State Bank of India",
    "onlinesbi": "State Bank of India",
    "hdfc": "HDFC Bank Limited",
    "hdfc bank": "HDFC Bank Limited",
    "icici": "ICICI Bank Limited",
    "icici bank": "ICICI Bank Limited",
    "axis": "Axis Bank Limited",
    "axis bank": "Axis Bank Limited",
    "pnb": "Punjab National Bank",
    "punjab national bank": "Punjab National Bank",
    "bob": "Bank of Baroda",
    "bank of baroda": "Bank of Baroda",
    "kotak": "Kotak Mahindra Bank Limited",
    "kotak bank": "Kotak Mahindra Bank Limited",
    "kotak mahindra bank": "Kotak Mahindra Bank Limited",
    "canara": "Canara Bank",
    "canara bank": "Canara Bank",
    "union bank": "Union Bank of India",
    "union bank of india": "Union Bank of India",
    "ubi": "Union Bank of India",
    "bank of india": "Bank of India",
    "boi": "Bank of India",
    "central bank": "Central Bank of India",
    "central bank of india": "Central Bank of India",
    "cbi": "Central Bank of India",
    "indian bank": "Indian Bank",
    "indian overseas bank": "Indian Overseas Bank",
    "iob": "Indian Overseas Bank",
    "punjab & sind bank": "Punjab & Sind Bank",
    "punjab and sind bank": "Punjab & Sind Bank",
    "psb": "Punjab & Sind Bank",
    "uco bank": "UCO Bank",
    "uco": "UCO Bank",
    "bank of maharashtra": "Bank of Maharashtra",
    "bom": "Bank of Maharashtra",
    "mahabank": "Bank of Maharashtra",
    "idfc first": "IDFC FIRST Bank Limited",
    "idfc first bank": "IDFC FIRST Bank Limited",
    "idfc bank": "IDFC FIRST Bank Limited",
    "idfc": "IDFC FIRST Bank Limited",
    "indusind": "IndusInd Bank Limited",
    "indusind bank": "IndusInd Bank Limited",
    "yes bank": "YES Bank Limited",
    "federal bank": "Federal Bank Limited",
    "bandhan bank": "Bandhan Bank Limited",
    "bandhan": "Bandhan Bank Limited",
    "bdbl": "Bandhan Bank Limited",
    "idbi": "IDBI Bank Limited",
    "idbi bank": "IDBI Bank Limited",
    "au": "Au Small Finance Bank Limited",
    "aubl": "Au Small Finance Bank Limited",
    "au bank": "Au Small Finance Bank Limited",
    "au small finance bank": "Au Small Finance Bank Limited",
    "airtel payments bank": "Airtel Payments Bank Limited",
    "airtel bank": "Airtel Payments Bank Limited",
    "paytm payments bank": "Paytm Payments Bank Limited",
    "paytm bank": "Paytm Payments Bank Limited",
    "standard chartered": "Standard Chartered Bank",
    "standard chartered bank": "Standard Chartered Bank",
    "stanchart": "Standard Chartered Bank",
    "hsbc": "Hong Kong and Shanghai Banking Corporation Limited",
    "hsbc bank": "Hong Kong and Shanghai Banking Corporation Limited",
    "citibank": "Citibank N.A.",
    "citi bank": "Citibank N.A.",
    "barclays": "Barclays Bank Plc.",
    "barclays bank": "Barclays Bank Plc.",
    "deutsche bank": "Deutsche Bank A.G.",
    "dbs": "DBS Bank India Limited (Subsidiary of DBS Bank Ltd.)",
    "dbs bank": "DBS Bank India Limited (Subsidiary of DBS Bank Ltd.)",
    "jp morgan": "J.P. Morgan Chase Bank N.A.",
    "jpmorgan": "J.P. Morgan Chase Bank N.A.",
    "j.p. morgan": "J.P. Morgan Chase Bank N.A.",
    "jain co-operative bank": "Jain Co-operative Bank Limited",
    "jain cooperative bank": "Jain Co-operative Bank Limited",
    "jain bank": "Jain Co-operative Bank Limited",
    "jcbl": "Jain Co-operative Bank Limited",
    "karnataka bank": "Karnataka Bank Limited",
    "kbl": "Karnataka Bank Limited",
    "jammu & kashmir bank": "Jammu & Kashmir Bank Limited",
    "jammu and kashmir bank": "Jammu & Kashmir Bank Limited",
    "j&k bank": "Jammu & Kashmir Bank Limited",
    "jk bank": "Jammu & Kashmir Bank Limited",
}


@dataclass(frozen=True, slots=True)
class BankInfo:
    """Canonical bank metadata record."""

    bank_name: str
    category: str


def _normalize_name(name: str) -> str:
    """Normalize bank name by lowercasing, stripping corporate noise and non-alphanumeric chars."""
    cleaned = name.lower()
    # Strip common corporate suffixes
    cleaned = re.sub(r"\b(limited|ltd\.?|plc\.?|corp\.?|corporation|inc\.?)\b", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return " ".join(cleaned.split())


class BankRegistry:
    """Canonical registry and lookup service for all RBI-recognized Indian banks."""

    def __init__(self, catalog_path: Path | None = None) -> None:
        target = catalog_path.resolve() if catalog_path is not None else (_CANONICAL_BANKS_DIR / _CATALOG_FILE)
        self._catalog_path = target
        self._banks: list[BankInfo] = []
        self._canonical_set: set[str] = set()
        self._normalized_map: dict[str, str] = {}
        self._load_catalog()

    def _load_catalog(self) -> None:
        if not self._catalog_path.exists():
            return
        try:
            raw = json.loads(self._catalog_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and "bank_name" in item:
                        b_name = str(item["bank_name"]).strip()
                        cat = str(item.get("category", "")).strip()
                        if b_name:
                            self._banks.append(BankInfo(bank_name=b_name, category=cat))
                            self._canonical_set.add(b_name)
                            norm = _normalize_name(b_name)
                            if norm:
                                self._normalized_map[norm] = b_name
        except Exception:
            pass

    @property
    def total_banks(self) -> int:
        return len(self._banks)

    @property
    def canonical_names(self) -> frozenset[str]:
        return frozenset(self._canonical_set)

    def is_canonical_bank_name(self, name: str | None) -> bool:
        """Check if name is an exact match for an official canonical bank name."""
        if not name:
            return False
        return name.strip() in self._canonical_set

    def identify_bank(
        self,
        text: str = "",
        ifsc: str | None = None,
        candidate_name: str | None = None,
    ) -> str | None:
        """Deterministically identify canonical bank name from IFSC, candidate string, or text.

        Evaluation order:
        1. IFSC 4-letter prefix lookup (authoritative).
        2. Exact match against canonical bank list.
        3. Normalized candidate name / alias lookup.
        4. Scanned document text / headers matching known banks or aliases.

        Returns:
            Official canonical bank name string, or None if unverified.
        """
        # 1. Authoritative IFSC prefix (checking specific sub-clearing codes before 4-letter sponsor codes)
        if ifsc and len(ifsc.strip()) >= 4:
            clean_ifsc = ifsc.strip().upper()
            for length in (10, 8, 6, 4):
                prefix = clean_ifsc[:length]
                if prefix in _IFSC_PREFIX_MAP:
                    return _IFSC_PREFIX_MAP[prefix]

        # 2. Exact canonical match on candidate name
        if candidate_name:
            cand_clean = candidate_name.strip()
            if cand_clean in self._canonical_set:
                return cand_clean

            # Normalized & alias match on candidate
            cand_lower = cand_clean.lower()
            if cand_lower in _CANONICAL_ALIASES:
                return _CANONICAL_ALIASES[cand_lower]

            cand_base = cand_lower.split("_")[0]
            if cand_base in _CANONICAL_ALIASES:
                return _CANONICAL_ALIASES[cand_base]

            cand_norm = _normalize_name(cand_clean)
            if cand_norm in self._normalized_map:
                return self._normalized_map[cand_norm]

        # 3. Check for explicitly labeled IFSC in header text (e.g. IFSC: AUBL...)
        if text and not ifsc:
            m_labeled_ifsc = re.search(
                r"(?:ifsc|rtgs|neft)\s*(?:code)?\s*[:\-]?\s*([A-Z]{4})0[A-Z0-9]{6}\b",
                text,
                re.IGNORECASE,
            )
            if m_labeled_ifsc:
                prefix = m_labeled_ifsc.group(1).upper()
                if prefix in _IFSC_PREFIX_MAP:
                    return _IFSC_PREFIX_MAP[prefix]

            m_aubl = re.search(r"\bAUBL[A-Z0-9]{10,}\b|@aubl\d+", text, re.IGNORECASE)
            if m_aubl:
                return _IFSC_PREFIX_MAP.get("AUBL")

        # 4. Document text search for canonical bank names (header block up to 5000 chars)
        if text:
            text_lower = text[:5000].lower()

            # Check multi-word canonical bank names (longer names first for specificity)
            matched_candidates: list[tuple[int, str]] = []
            for b in self._banks:
                b_low = b.bank_name.lower()
                if b_low in text_lower:
                    matched_candidates.append((len(b_low), b.bank_name))

            if matched_candidates:
                matched_candidates.sort(key=lambda x: x[0], reverse=True)
                return matched_candidates[0][1]

            # Check normalized names
            for norm_key, canon_name in self._normalized_map.items():
                if len(norm_key) >= 5 and norm_key in text_lower:
                    matched_candidates.append((len(norm_key), canon_name))

            if matched_candidates:
                matched_candidates.sort(key=lambda x: x[0], reverse=True)
                return matched_candidates[0][1]

            # Check alias / acronym tokens with word boundary enforcement
            alias_matches: list[tuple[int, str]] = []
            for alias, canon_name in _CANONICAL_ALIASES.items():
                pattern = rf"\b{re.escape(alias)}\b"
                if re.search(pattern, text_lower):
                    alias_matches.append((len(alias), canon_name))

            if alias_matches:
                alias_matches.sort(key=lambda x: x[0], reverse=True)
                return alias_matches[0][1]

        # 5. Fallback: bare unlabeled IFSC in the statement header block (first 1200 chars only)
        if text and not ifsc:
            header_text = text[:1200]
            m_ifsc = re.search(r"\b([A-Z]{4})0[A-Z0-9]{6}\b", header_text.upper())
            if m_ifsc:
                prefix = m_ifsc.group(1)
                if prefix in _IFSC_PREFIX_MAP:
                    return _IFSC_PREFIX_MAP[prefix]

        return None


# Global singleton instance
_GLOBAL_REGISTRY: BankRegistry | None = None


def get_bank_registry(catalog_path: Path | None = None) -> BankRegistry:
    """Get or create singleton BankRegistry instance."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None or catalog_path is not None:
        reg = BankRegistry(catalog_path=catalog_path)
        if catalog_path is None:
            _GLOBAL_REGISTRY = reg
        return reg
    return _GLOBAL_REGISTRY
