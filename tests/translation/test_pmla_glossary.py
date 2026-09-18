"""Tests for curated PMLA (Prevention of Money Laundering Act, 2002) glossary integration."""

from __future__ import annotations

from sarathi.shakti.translation.glossary import GlossaryStore
from sarathi.shakti.translation.legal_context import LegalContextBuilder
from sarathi.shakti.translation.models import TranslationDirection
from sarathi.shakti.translation.protector import TranslationProtector


def test_pmla_glossary_loads_in_glossary_store() -> None:
    """Verify that pmla.json is discovered and loaded into GlossaryStore with bidirectional terms."""
    store = GlossaryStore()
    en_terms = store.get_terms(TranslationDirection.EN_TO_HI)
    hi_terms = store.get_terms(TranslationDirection.HI_TO_EN)

    # Statutory PMLA terms in English -> Hindi
    assert "Proceeds of Crime" in en_terms
    assert "अपराध के आगम" in en_terms["Proceeds of Crime"]
    assert "Reporting Entity" in en_terms
    assert "रिपोर्टकर्ता इकाई" in en_terms["Reporting Entity"]
    assert "Adjudicating Authority" in en_terms
    assert en_terms["Adjudicating Authority"] == "न्यायनिर्णायक प्राधिकारी"
    assert "Special Court" in en_terms
    assert en_terms["Special Court"] == "विशेष न्यायालय"
    assert "Attachment" in en_terms
    assert en_terms["Attachment"] == "कुर्की"
    assert "Enhanced Due Diligence" in en_terms
    assert "वर्धित सम्यक तत्परता" in en_terms["Enhanced Due Diligence"]
    assert "Scheduled Offence" in en_terms
    assert en_terms["Scheduled Offence"] == "अनुसूचित अपराध"
    assert "Beneficial Owner" in en_terms
    assert "हिताधिकारी स्वामी" in en_terms["Beneficial Owner"]

    # Bidirectional statutory Hindi -> English mappings
    assert hi_terms.get("अपराध के आगम") == "Proceeds of Crime"
    assert hi_terms.get("अपराध की आय") == "Proceeds of Crime"
    assert hi_terms.get("रिपोर्टकर्ता इकाई") == "Reporting Entity"
    assert hi_terms.get("रिपोर्टिंग इकाई") == "Reporting Entity"
    assert hi_terms.get("कुर्की") == "Attachment"
    assert hi_terms.get("विशेष न्यायालय") == "Special Court"
    assert hi_terms.get("न्यायनिर्णायक प्राधिकारी") == "Adjudicating Authority"


def test_pmla_glossary_protection_case_insensitive() -> None:
    """Verify TranslationProtector protects PMLA terms regardless of casing in source document."""
    protector = TranslationProtector()
    glossary = {
        "Proceeds of Crime": "अपराध के आगम",
        "Adjudicating Authority": "न्यायनिर्णायक प्राधिकारी",
        "Reporting Entity": "रिपोर्टकर्ता इकाई",
    }

    # Document contains lowercase and mixed casing
    text = (
        "The accused laundered proceeds of crime through foreign entities. "
        "The ADJUDICATING AUTHORITY confirmed the provisional order against the reporting entity."
    )

    protected_text, spans = protector.protect(text, glossary_mappings=glossary)

    # Verify English terms were protected
    assert "proceeds of crime" not in protected_text
    assert "ADJUDICATING AUTHORITY" not in protected_text
    assert "reporting entity" not in protected_text

    # Verify restoration substitutes statutory Hindi terms
    restored, issues = protector.restore_with_validation(protected_text, spans)
    assert issues == []
    assert "अपराध के आगम" in restored
    assert "न्यायनिर्णायक प्राधिकारी" in restored
    assert "रिपोर्टकर्ता इकाई" in restored


def test_pmla_legal_context_extraction() -> None:
    """Verify LegalContextBuilder extracts PMLA terms and builds grounded judicial context."""
    builder = LegalContextBuilder()

    complaint_text = """
    IN THE SPECIAL COURT FOR PMLA (SESSIONS COURT), NEW DELHI
    In the matter of:
    DIRECTORATE OF ENFORCEMENT ... Complainant
    VERSUS
    ABC INFRASTRUCTURE LTD ... Accused

    PROSECUTION COMPLAINT UNDER SECTION 44 READ WITH SECTION 45 OF THE PREVENTION OF MONEY LAUNDERING ACT, 2002.
    The accused persons knowingly assisted in the concealment, possession, acquisition or use of proceeds of crime.
    The provisional attachment of property was confirmed by the Adjudicating Authority under Section 8 of the PMLA.
    The reporting entity failed to conduct enhanced due diligence as required under Section 12AA.
    """

    context = builder.extract_context(complaint_text, direction=TranslationDirection.EN_TO_HI)

    assert context.is_legal_document is True
    assert context.court_name is not None
    assert "Special Court" in context.court_name or "Sessions Court" in context.court_name

    # Check matched glossary terms
    matched = context.matched_glossary_terms
    assert "Proceeds of Crime" in matched or "proceeds of crime" in [k.lower() for k in matched]
    assert "Adjudicating Authority" in matched
    assert "Reporting Entity" in matched or "reporting entity" in [k.lower() for k in matched]

    # Verify prompt synthesis includes PMLA glossary instructions
    prompt = builder.format_system_prompt(context, source_lang="English", target_lang="Hindi")
    assert "MANDATORY JUDICIAL TERMINOLOGY DIRECTIVES" in prompt.upper()
    assert "न्यायनिर्णायक प्राधिकारी" in prompt
