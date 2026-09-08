"""High-speed statutory and legal entity extractor with OCR error-tolerance."""

from __future__ import annotations

import re
from typing import Any

from sarathi.shakti.statutory.checksums import (
    CIN_PATTERN,
    CNR_PATTERN,
    DIN_PATTERN,
    GSTIN_PATTERN,
    IRN_PATTERN,
    PAN_PATTERN,
    TAN_PATTERN,
    verify_cin,
    verify_cnr,
    verify_din,
    verify_gstin,
    verify_pan,
    verify_tan,
)
from sarathi.shakti.statutory.models import (
    ECourtsMetadata,
    GSTMetadata,
    IncomeTaxMetadata,
    MCAMetadata,
    StatutoryDocumentType,
    StatutoryEntities,
)

# Common OCR confusion translation maps
_NUM_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z"})
_ALPHA_TO_NUM = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})

# Proximity Regexes
_INVOICE_NUM_RE = re.compile(
    r"(?:invoice\s*no|inv\s*no|bill\s*no|invoice\s*number)[.:\s]+([A-Za-z0-9\-\/]+)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b([0-3]?[0-9][\/\-\.][0-1]?[0-9][\/\-\.](?:20)?[0-9]{2})\b"
)
_AY_RE = re.compile(r"\b(?:A\.?Y\.?|Assessment\s*Year)[.:\s]*((?:20)?[0-9]{2}\s*[\-\/]\s*(?:20)?[0-9]{2})\b", re.IGNORECASE)
_ACK_RE = re.compile(r"\b(?:Ack(?:nowledgement)?\s*No|E-Filing\s*Ack)[.:\s]*([0-9]{15})\b", re.IGNORECASE)
_CASE_NO_RE = re.compile(
    r"\b((?:WP\(C\)|W\.P\.\(C\)|CRL\.A|CRL\.M|SLP\(C\)|CS\(COMM\)|ARB\.P|CO\.APP)\s*No\.?\s*[0-9]+\s*(?:of|\/)\s*(?:20)?[0-9]{2})\b",
    re.IGNORECASE,
)
_PARTY_VERSUS_RE = re.compile(
    r"([A-Z\s\.\,\(\)]{3,60})\s+(?:VERSUS|V\/S|V\.|VS)\s+([A-Z\s\.\,\(\)]{3,60})",
    re.IGNORECASE,
)
_JUDGE_RE = re.compile(
    r"(?:HON'BLE\s+MR\.?\s+JUSTICE|HON'BLE\s+MS\.?\s+JUSTICE|HON'BLE\s+JUSTICE)\s+([A-Z\s\.]+?)(?:,|\n|$)",
    re.IGNORECASE,
)


def repair_pan_candidate(raw: str) -> tuple[str, bool]:
    """Correct positional OCR character confusions in a 10-char PAN candidate."""
    if len(raw) != 10:
        return raw, False
    chars = list(raw.upper())
    # Chars 0..4: letters
    for i in range(5):
        chars[i] = chars[i].translate(_NUM_TO_ALPHA)
    # Chars 5..8: digits
    for i in range(5, 9):
        chars[i] = chars[i].translate(_ALPHA_TO_NUM)
    # Char 9: letter
    chars[9] = chars[9].translate(_NUM_TO_ALPHA)
    repaired = "".join(chars)
    return repaired, (repaired != raw.upper())


def repair_gstin_candidate(raw: str) -> tuple[str, bool]:
    """Correct positional OCR character confusions in a 15-char GSTIN candidate."""
    if len(raw) != 15:
        return raw, False
    chars = list(raw.upper())
    # Chars 0..1: digits (state code)
    chars[0] = chars[0].translate(_ALPHA_TO_NUM)
    chars[1] = chars[1].translate(_ALPHA_TO_NUM)
    # Chars 2..6: letters (PAN prefix)
    for i in range(2, 7):
        chars[i] = chars[i].translate(_NUM_TO_ALPHA)
    # Chars 7..10: digits (PAN number)
    for i in range(7, 11):
        chars[i] = chars[i].translate(_ALPHA_TO_NUM)
    # Char 11: letter (PAN suffix)
    chars[11] = chars[11].translate(_NUM_TO_ALPHA)
    # Char 13: strictly 'Z'
    if chars[13] in ("2", "z", "Z"):
        chars[13] = "Z"
    repaired = "".join(chars)
    return repaired, (repaired != raw.upper())


def extract_statutory_entities(text: str) -> StatutoryEntities:
    """Extract and validate all statutory, tax, corporate, and legal identifiers from text."""
    if not text or not text.strip():
        return StatutoryEntities()

    raw_identifiers: dict[str, list[str]] = {
        "gstins": [],
        "pans": [],
        "tans": [],
        "cins": [],
        "cnrs": [],
        "dins": [],
        "irns": [],
    }
    ocr_corrections: list[str] = []

    words = re.findall(r"\b[A-Za-z0-9\-]{8,64}\b", text)

    # 1. Exact & OCR-Repaired Identification
    for word in words:
        clean = word.strip().upper().replace("-", "")

        # IRN Check (64 hex characters)
        if len(clean) == 64 and IRN_PATTERN.match(clean):
            if clean not in raw_identifiers["irns"]:
                raw_identifiers["irns"].append(clean)
            continue

        # CIN Check (21 chars)
        if len(clean) == 21:
            if verify_cin(clean) and clean not in raw_identifiers["cins"]:
                raw_identifiers["cins"].append(clean)
                continue

        # CNR Check (16 chars)
        if len(clean) == 16:
            if verify_cnr(clean) and clean not in raw_identifiers["cnrs"]:
                raw_identifiers["cnrs"].append(clean)
                continue

        # GSTIN Check (15 chars)
        if len(clean) == 15:
            if verify_gstin(clean):
                if clean not in raw_identifiers["gstins"]:
                    raw_identifiers["gstins"].append(clean)
                continue
            # Try OCR error repair
            repaired, modified = repair_gstin_candidate(clean)
            if modified and verify_gstin(repaired):
                if repaired not in raw_identifiers["gstins"]:
                    raw_identifiers["gstins"].append(repaired)
                    ocr_corrections.append(f"GSTIN '{clean}' corrected to '{repaired}'")
                continue

        # PAN Check (10 chars)
        if len(clean) == 10:
            if verify_pan(clean):
                if clean not in raw_identifiers["pans"]:
                    raw_identifiers["pans"].append(clean)
                continue
            if verify_tan(clean):
                if clean not in raw_identifiers["tans"]:
                    raw_identifiers["tans"].append(clean)
                continue
            # Try OCR error repair for PAN
            repaired, modified = repair_pan_candidate(clean)
            if modified and verify_pan(repaired):
                if repaired not in raw_identifiers["pans"]:
                    raw_identifiers["pans"].append(repaired)
                    ocr_corrections.append(f"PAN '{clean}' corrected to '{repaired}'")
                continue

        # DIN Check (8 digits)
        if len(clean) == 8 and verify_din(clean):
            # To reduce false positives on generic numbers, DIN is only accepted
            # if context contains 'DIN' or 'DIRECTOR'
            if re.search(r"\b(?:DIN|Director)\b", text, re.IGNORECASE):
                if clean not in raw_identifiers["dins"]:
                    raw_identifiers["dins"].append(clean)

    # 2. Build Structured Sub-models
    gst_meta: GSTMetadata | None = None
    if raw_identifiers["gstins"]:
        sup_gst = raw_identifiers["gstins"][0]
        buy_gst = raw_identifiers["gstins"][1] if len(raw_identifiers["gstins"]) > 1 else None
        inv_match = _INVOICE_NUM_RE.search(text)
        date_match = _DATE_RE.search(text)
        irn_val = raw_identifiers["irns"][0] if raw_identifiers["irns"] else None

        gst_meta = GSTMetadata(
            supplier_gstin=sup_gst,
            buyer_gstin=buy_gst,
            invoice_number=inv_match.group(1) if inv_match else None,
            invoice_date=date_match.group(1) if date_match else None,
            irn=irn_val,
            state_code=sup_gst[:2] if sup_gst else None,
            supplier_pan=sup_gst[2:12] if sup_gst else None,
            is_valid_checksum=True,
        )

    it_meta: IncomeTaxMetadata | None = None
    if raw_identifiers["pans"] or raw_identifiers["tans"] or "INCOME TAX" in text.upper():
        ay_match = _AY_RE.search(text)
        ack_match = _ACK_RE.search(text)
        pan_val = raw_identifiers["pans"][0] if raw_identifiers["pans"] else None
        tan_val = raw_identifiers["tans"][0] if raw_identifiers["tans"] else None

        it_meta = IncomeTaxMetadata(
            pan=pan_val,
            tan=tan_val,
            assessment_year=ay_match.group(1) if ay_match else None,
            ack_number=ack_match.group(1) if ack_match else None,
            is_valid_checksum=bool(pan_val and verify_pan(pan_val)),
        )

    mca_meta: MCAMetadata | None = None
    if raw_identifiers["cins"] or "MINISTRY OF CORPORATE AFFAIRS" in text.upper() or "REGISTRAR OF COMPANIES" in text.upper():
        cin_val = raw_identifiers["cins"][0] if raw_identifiers["cins"] else None
        mca_meta = MCAMetadata(
            cin=cin_val,
            dins=tuple(raw_identifiers["dins"]),
            roc_code=cin_val[6:8] if cin_val else None,
            is_valid_checksum=bool(cin_val and verify_cin(cin_val)),
        )

    court_meta: ECourtsMetadata | None = None
    if raw_identifiers["cnrs"] or _CASE_NO_RE.search(text) or "HIGH COURT" in text.upper() or "SUPREME COURT" in text.upper() or "DISTRICT COURT" in text.upper():
        cnr_val = raw_identifiers["cnrs"][0] if raw_identifiers["cnrs"] else None
        case_match = _CASE_NO_RE.search(text)
        judge_match = _JUDGE_RE.search(text)
        party_match = _PARTY_VERSUS_RE.search(text)

        petitioners = (party_match.group(1).strip(),) if party_match else ()
        respondents = (party_match.group(2).strip(),) if party_match else ()
        judges = (judge_match.group(1).strip(),) if judge_match else ()

        court_name = None
        for c_cand in ("Supreme Court of India", "High Court of Delhi", "High Court of Bombay", "High Court"):
            if c_cand.lower() in text.lower():
                court_name = c_cand
                break

        court_meta = ECourtsMetadata(
            cnr_number=cnr_val,
            court_name=court_name,
            case_number=case_match.group(1) if case_match else None,
            petitioners=petitioners,
            respondents=respondents,
            judges=judges,
            is_valid_checksum=bool(cnr_val and verify_cnr(cnr_val)),
        )

    # 3. Document Type Classification
    doc_type = StatutoryDocumentType.UNKNOWN
    confidence = 0.5
    if gst_meta and gst_meta.supplier_gstin:
        doc_type = StatutoryDocumentType.GST_INVOICE
        confidence = 0.95
    elif it_meta and (it_meta.pan or it_meta.ack_number):
        doc_type = StatutoryDocumentType.INCOME_TAX_ACK
        confidence = 0.92
    elif mca_meta and mca_meta.cin:
        doc_type = StatutoryDocumentType.MCA_COI if "CERTIFICATE OF INCORPORATION" in text.upper() else StatutoryDocumentType.MCA_FILING
        confidence = 0.94
    elif court_meta and (court_meta.cnr_number or court_meta.case_number):
        doc_type = StatutoryDocumentType.ECOURTS_ORDER
        confidence = 0.90

    return StatutoryEntities(
        doc_type=doc_type,
        confidence=confidence,
        gst=gst_meta,
        income_tax=it_meta,
        mca=mca_meta,
        ecourts=court_meta,
        raw_identifiers={k: tuple(v) for k, v in raw_identifiers.items()},
        ocr_corrections=tuple(ocr_corrections),
    )
