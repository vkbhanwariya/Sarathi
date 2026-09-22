"""Legal context extraction and judicial translation prompt synthesis for Sarathi.

Provides authoritative document-level judicial grounding for Indian legal documents
(Supreme Court, High Courts, District Courts, Tribunals, Statutory Returns, FIRs).
Dynamically matches domain terminology from curated legal glossaries, detects statutory
citations, and enforces strict structural and citation preservation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sarathi.shakti.statutory.extractor import extract_statutory_entities
from sarathi.shakti.translation.glossary import GlossaryStore
from sarathi.shakti.translation.models import TranslationDirection

# Recognized Indian Courts & Tribunals
_INDIAN_COURTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Supreme Court of India",
        (
            "supreme court of india",
            "supreme court",
            "hon'ble supreme court",
            "सर्वोच्च न्यायालय",
            "उच्चतम न्यायालय",
            "माननीय सर्वोच्च न्यायालय",
            "माननीय उच्चतम न्यायालय",
        ),
    ),
    (
        "High Court of Judicature at Allahabad",
        (
            "high court of judicature at allahabad",
            "allahabad high court",
            "high court at allahabad",
            "उच्च न्यायालय इलाहाबाद",
            "इलाहाबाद उच्च न्यायालय",
        ),
    ),
    (
        "High Court of Delhi",
        (
            "high court of delhi",
            "delhi high court",
            "दिल्ली उच्च न्यायालय",
            "उच्च न्यायालय दिल्ली",
        ),
    ),
    (
        "High Court of Bombay",
        (
            "high court of bombay",
            "bombay high court",
            "high court of judicature at bombay",
            "बॉम्बे उच्च न्यायालय",
            "मुंबई उच्च न्यायालय",
        ),
    ),
    (
        "High Court of Calcutta",
        (
            "high court of calcutta",
            "calcutta high court",
            "कलकत्ता उच्च न्यायालय",
        ),
    ),
    (
        "High Court of Madras",
        (
            "high court of madras",
            "madras high court",
            "मद्रास उच्च न्यायालय",
        ),
    ),
    (
        "High Court of Punjab and Haryana",
        (
            "high court of punjab and haryana",
            "punjab and haryana high court",
            "पंजाब एवं हरियाणा उच्च न्यायालय",
        ),
    ),
    (
        "High Court of Rajasthan",
        (
            "high court of rajasthan",
            "rajasthan high court",
            "high court of judicature for rajasthan",
            "राजस्थान उच्च न्यायालय",
        ),
    ),
    (
        "High Court of Madhya Pradesh",
        (
            "high court of madhya pradesh",
            "madhya pradesh high court",
            "मध्य प्रदेश उच्च न्यायालय",
        ),
    ),
    (
        "High Court of Gujarat",
        (
            "high court of gujarat",
            "gujarat high court",
            "गुजरात उच्च न्यायालय",
        ),
    ),
    (
        "High Court of Karnataka",
        (
            "high court of karnataka",
            "karnataka high court",
            "कर्नाटक उच्च न्यायालय",
        ),
    ),
    (
        "High Court of Kerala",
        (
            "high court of kerala",
            "kerala high court",
            "केरल उच्च न्यायालय",
        ),
    ),
    (
        "High Court of Patna",
        (
            "high court of patna",
            "patna high court",
            "high court of judicature at patna",
            "पटना उच्च न्यायालय",
        ),
    ),
    (
        "National Company Law Appellate Tribunal (NCLAT)",
        (
            "national company law appellate tribunal",
            "nclat",
            "कंपनी विधि अपीलीय न्यायाधिकरण",
        ),
    ),
    (
        "National Company Law Tribunal (NCLT)",
        (
            "national company law tribunal",
            "nclt",
            "कंपनी विधि न्यायाधिकरण",
        ),
    ),
    (
        "Debts Recovery Tribunal (DRT)",
        (
            "debts recovery appellate tribunal",
            "debts recovery tribunal",
            "drat",
            "drt",
            "ऋण वसूली न्यायाधिकरण",
        ),
    ),
    (
        "Central Administrative Tribunal (CAT)",
        (
            "central administrative tribunal",
            "केंद्रीय प्रशासनिक अधिकरण",
        ),
    ),
    (
        "Income Tax Appellate Tribunal (ITAT)",
        (
            "income tax appellate tribunal",
            "itat",
            "आयकर अपीलीय अधिकरण",
        ),
    ),
    (
        "District & Sessions Court",
        (
            "district and sessions judge",
            "district and sessions court",
            "district court",
            "sessions court",
            "जिला एवं सत्र न्यायालय",
            "जिला न्यायालय",
            "सत्र न्यायालय",
            "मुख्य न्यायिक मजिस्ट्रेट",
            "chief judicial magistrate",
        ),
    ),
)

# Common statutory section and Act citation patterns (English & Hindi)
_STATUTORY_CITATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # English Section + Act (e.g. Section 420 IPC, Section 420 and 468 of the IPC)
    re.compile(
        r"\b(?:Section|Sec\.?|u/s|u/ss)\s*[0-9A-Z]+(?:\s*(?:and|,|&)\s*(?:Section\s*)?[0-9A-Z]+)*"
        r"(?:\s*(?:of\s*(?:the\s*)?)?(?:IPC|Indian Penal Code|BNS|Bharatiya Nyaya Sanhita|"
        r"CrPC|Cr\.P\.C\.?|Code of Criminal Procedure|BNSS|Bharatiya Nagarik Suraksha Sanhita|"
        r"CPC|C\.P\.C\.?|Code of Civil Procedure|Indian Evidence Act|Evidence Act|BSA|Bharatiya Sakshya Adhiniyam|"
        r"NI Act|Negotiable Instruments Act|PMLA|Prevention of Money Laundering Act|IBC|Insolvency and Bankruptcy Code|"
        r"Companies Act|Income Tax Act|Arbitration and Conciliation Act|POCSO Act|Consumer Protection Act|Motor Vehicles Act|"
        r"Constitution of India|Constitution))?\b",
        re.IGNORECASE,
    ),
    # Hindi Section + Act (supporting both Act-first and Section-first)
    re.compile(
        r"(?:(?:भारतीय\s*दण्ड\s*संहिता|भा\.?दं\.?सं\.?|दंड\s*प्रक्रिया\s*संहिता|दं\.?प्र\.?सं\.?|"
        r"भारतीय\s*न्याय\s*संहिता|भा\.?न्या\.?सं\.?|भारतीय\s*नागरिक\s*सुरक्षा\s*संहिता|भा\.?ना\.?सु\.?सं\.?|"
        r"भारतीय\s*साक्ष्य\s*अधिनियम|साक्ष्य\s*अधिनियम|भा\.?सा\.?अ\.?|परक्राम्य\s*लिखत\s*अधिनियम|"
        r"धन\s*शोधन\s*निवारण\s*अधिनियम|आयकर\s*अधिनियम|कंपनी\s*अधिनियम)\s*(?:की\s*)?)?"
        r"(?:धारा|कलम)\s*[0-9A-Z]+(?:\s*(?:एवं|और|,)\s*(?:धारा\s*)?[0-9A-Z]+)*"
        r"(?:\s*(?:भा\.?दं\.?सं\.?|भारतीय\s*दण्ड\s*संहिता|भा\.?न्या\.?सं\.?|भारतीय\s*न्याय\s*संहिता|"
        r"दं\.?प्र\.?सं\.?|दंड\s*प्रक्रिया\s*संहिता|भा\.?ना\.?सु\.?सं\.?|भारतीय\s*नागरिक\s*सुरक्षा\s*संहिता|"
        r"परक्राम्य\s*लिखत\s*अधिनियम))?",
        re.IGNORECASE,
    ),
    # CPC Order & Rule
    re.compile(
        r"\b(?:Order\s*[0-9A-Z]+\s*Rule\s*[0-9A-Z]+)\s*(?:of\s*(?:the\s*)?)?(?:CPC|C\.P\.C\.?|Code of Civil Procedure)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:आदेश\s*[0-9A-Z]+\s*नियम\s*[0-9A-Z]+)\s*(?:सी\.?पी\.?सी\.?|सिविल\s*प्रक्रिया\s*संहिता)?", re.IGNORECASE),
    # Constitutional Articles
    re.compile(
        r"\b(?:Article|Art\.?)\s*[0-9A-Z]+\s*(?:of\s*(?:the\s*)?)?(?:Constitution of India|Constitution)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:अनुच्छेद)\s*[0-9A-Z]+\s*(?:भारत\s*का\s*संविधान|संविधान)?", re.IGNORECASE),
    # FIR numbers
    re.compile(r"\b(?:FIR\s*No\.?|Crime\s*No\.?)\s*([A-Za-z0-9\/\-]+(?:\s*of\s*(?:20)?[0-9]{2})?)\b", re.IGNORECASE),
    re.compile(r"(?:मु\.?अ\.?सं\.?|प्र\.?सू\.?रि\.?|अपराध\s*संख्या)\s*([A-Za-z0-9\/\-]+)", re.IGNORECASE),
    # Case law citations (SCC, AIR, INSC, ILR)
    re.compile(
        r"\b(?:\([0-9]{4}\)\s*[0-9]+\s*SCC\s*[0-9]+|AIR\s*[0-9]{4}\s*SC\s*[0-9]+|[0-9]{4}\s*INSC\s*[0-9]+)\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class LegalDocumentContext:
    """Document-level legal metadata grounding translation."""

    court_name: str | None = None
    case_number: str | None = None
    cnr_number: str | None = None
    petitioners: tuple[str, ...] = ()
    respondents: tuple[str, ...] = ()
    judges: tuple[str, ...] = ()
    statutory_references: tuple[str, ...] = ()
    matched_glossary_terms: Mapping[str, str] = field(default_factory=dict)
    is_legal_document: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize legal context for document metadata and telemetry provenance."""
        return {
            "is_legal_document": self.is_legal_document,
            "court_name": self.court_name,
            "case_number": self.case_number,
            "cnr_number": self.cnr_number,
            "petitioners": list(self.petitioners),
            "respondents": list(self.respondents),
            "judges": list(self.judges),
            "statutory_references": list(self.statutory_references),
            "glossary_terms_count": len(self.matched_glossary_terms),
            "sample_glossary_terms": dict(list(self.matched_glossary_terms.items())[:10]),
        }


class LegalContextBuilder:
    """Extracts judicial context and builds authoritative legal system prompts."""

    def __init__(self, glossary_store: GlossaryStore | None = None) -> None:
        self._glossary_store = glossary_store or GlossaryStore()

    def detect_court_name(self, text: str) -> str | None:
        """Identify specific Indian Court, Tribunal, or Forum in text."""
        lower_text = text[:4000].lower()
        for court_title, patterns in _INDIAN_COURTS:
            for pat in patterns:
                if pat in lower_text:
                    return court_title
        if "high court" in lower_text:
            return "High Court"
        if "tribunal" in lower_text:
            return "Tribunal"
        return None

    def detect_statutory_references(self, text: str, max_refs: int = 15) -> tuple[str, ...]:
        """Extract explicit statutory acts, sections, and case citations from text."""
        refs: list[str] = []
        for pat in _STATUTORY_CITATION_PATTERNS:
            for match in pat.finditer(text):
                matched_str = match.group(0).strip()
                if matched_str and matched_str not in refs:
                    refs.append(matched_str)
                    if len(refs) >= max_refs:
                        break
            if len(refs) >= max_refs:
                break
        return tuple(refs)

    def match_domain_glossary(
        self,
        text: str,
        direction: TranslationDirection = TranslationDirection.HI_TO_EN,
        max_terms: int = 40,
    ) -> dict[str, str]:
        """Match high-relevance domain glossary terms appearing in document text."""
        available_terms = self._glossary_store.get_terms(direction)
        if not available_terms or not text.strip():
            return {}

        # Search for domain terms present in text (length >= 2)
        if direction == TranslationDirection.EN_TO_HI:
            lower_doc = text.lower()
            candidates = []
            for t in available_terms.keys():
                if len(t) < 2 or t.lower() not in lower_doc:
                    continue
                prefix = r"(?<!\w)" if t[0].isalnum() else ""
                suffix = r"(?!\w)" if t[-1].isalnum() else ""
                if re.search(f"{prefix}{re.escape(t)}{suffix}", text, re.IGNORECASE):
                    candidates.append(t)
        else:
            candidates = [t for t in available_terms.keys() if len(t) >= 2 and t in text]

        if not candidates:
            return {}

        # Prioritize longer, more specialized multi-word legal phrases
        candidates.sort(key=len, reverse=True)

        matched: dict[str, str] = {}
        for term in candidates:
            matched[term] = available_terms[term]
            if len(matched) >= max_terms:
                break

        return matched

    def extract_context(
        self,
        text: str,
        direction: TranslationDirection = TranslationDirection.HI_TO_EN,
        custom_options: Mapping[str, Any] | None = None,
        max_glossary_terms: int = 40,
    ) -> LegalDocumentContext:
        """Synthesize comprehensive legal document context for translation."""
        if not text or not text.strip():
            return LegalDocumentContext()

        # 1. Base statutory entity extraction (CNR, Case No, Parties, Judges, Courts)
        entities = extract_statutory_entities(text)
        court_meta = entities.ecourts

        # 2. Refined Court / Forum detection
        court_name = self.detect_court_name(text) or (court_meta.court_name if court_meta else None)

        case_number = court_meta.case_number if court_meta else None
        cnr_number = court_meta.cnr_number if court_meta else None

        def _clean_party(name: str) -> str:
            cleaned = re.sub(
                r"(?:\.\.\.|\s*[-–—]|\s*\(|\s*\b)(?:PETITIONERS?|RESPONDENTS?|APPELLANTS?|DEFENDANTS?|PLAINTIFFS?|ACCUSED|APPLICANTS?|NON-APPLICANTS?|OPPOSITE\s*PARTY).*$",
                "",
                name,
                flags=re.IGNORECASE,
            ).strip(". \t\n-–—()")
            return cleaned if cleaned else name

        petitioners = tuple(_clean_party(p) for p in court_meta.petitioners) if court_meta else ()
        respondents = tuple(_clean_party(r) for r in court_meta.respondents) if court_meta else ()
        judges = court_meta.judges if court_meta else ()

        # 3. Statutory citations & enactments
        statutory_refs = self.detect_statutory_references(text)

        # 4. User-supplied overrides in custom_options
        if custom_options:
            if custom_options.get("court_name"):
                court_name = str(custom_options["court_name"])
            if custom_options.get("case_number"):
                case_number = str(custom_options["case_number"])
            if custom_options.get("cnr_number"):
                cnr_number = str(custom_options["cnr_number"])

        # 5. Dynamic domain legal glossary matching
        matched_terms = self.match_domain_glossary(
            text=text,
            direction=direction,
            max_terms=max_glossary_terms,
        )

        # Add custom glossary terms if provided
        if custom_options and "custom_glossary" in custom_options:
            custom_g = custom_options["custom_glossary"]
            if isinstance(custom_g, dict):
                matched_terms.update({str(k): str(v) for k, v in custom_g.items()})

        # 6. Classification: Is this document a legal / statutory document?
        is_legal = bool(
            court_name
            or case_number
            or cnr_number
            or petitioners
            or respondents
            or judges
            or statutory_refs
            or len(matched_terms) >= 2
            or (custom_options and custom_options.get("legal_context") is True)
        )

        return LegalDocumentContext(
            court_name=court_name,
            case_number=case_number,
            cnr_number=cnr_number,
            petitioners=petitioners,
            respondents=respondents,
            judges=judges,
            statutory_references=statutory_refs,
            matched_glossary_terms=matched_terms,
            is_legal_document=is_legal,
        )

    def format_system_prompt(
        self,
        context: LegalDocumentContext,
        source_lang: str,
        target_lang: str,
        custom_guidelines: Sequence[str] = (),
        max_glossary_terms: int = 5,
    ) -> str:
        """Synthesize authoritative judicial system instruction for cloud LLMs with lean glossary seeding."""
        lines: list[str] = [
            "You are an authoritative Senior Bilingual Judicial and Legal Translator specializing in "
            "the Supreme Court of India, High Courts, and Central Tribunals.",
            f"Translate the provided text faithfully from {source_lang} into {target_lang}.",
        ]

        # Case Context Grounding Banner
        lines.append("\n### Document Context Grounding:")
        lines.append(f"- Forum/Court: {context.court_name or 'Indian Judicial / Quasi-Judicial Forum'}")
        if context.case_number:
            lines.append(f"- Case Number: {context.case_number}")
        if context.cnr_number:
            lines.append(f"- CNR Number: {context.cnr_number}")
        if context.petitioners or context.respondents:
            pet_str = ", ".join(context.petitioners) if context.petitioners else "Petitioner(s)"
            res_str = ", ".join(context.respondents) if context.respondents else "Respondent(s)"
            lines.append(f"- Cause Title: {pet_str} vs. {res_str}")
        if context.judges:
            lines.append(f"- Coram/Bench: Hon'ble {', '.join(context.judges)}")
        if context.statutory_references:
            lines.append(f"- Key Statutory Enactments & Sections: {', '.join(context.statutory_references[:6])}")

        # Mandatory Domain Terminology Directives (Lean Seeding)
        if context.matched_glossary_terms:
            lines.append("\n### Mandatory Judicial Terminology Directives:")
            lines.append("Strictly translate the following legal terms according to authoritative statutory standards:")
            for src_t, tgt_t in list(context.matched_glossary_terms.items())[:max_glossary_terms]:
                lines.append(f'- "{src_t}" -> "{tgt_t}"')

        # Mandatory Preservation & Drafting Invariants
        lines.append("\n### Strict Drafting & Preservation Invariants:")
        lines.append(
            "1. Strictly adhere to standard Indian judicial drafting conventions (e.g. 'Hon'ble Court', 'impugned order', 'inter alia', 'prima facie', 'status quo')."
        )
        lines.append(
            "2. Preserve all legal citations (AIR, SCC, SCR, ILR, INSC), section numbers ('Section 302 IPC', 'धारा 420'), FIR numbers, dates, monetary amounts, and alphanumeric codes exactly as they appear."
        )
        lines.append(
            "3. Strictly preserve without alteration any structural placeholders (e.g. {{TABLE:...}}, {{PAGE:...}}, __PROTECTED_SPAN_...__, or numeric tokens 999...)."
        )
        lines.append("4. Preserve all Markdown headings, indentation, bullet points, and paragraph structures.")
        for g in custom_guidelines:
            lines.append(f"- {g}")
        lines.append(
            "5. Output ONLY the translated text without conversational preamble, pleasantries, explanations, or footnotes."
        )

        return "\n".join(lines)
