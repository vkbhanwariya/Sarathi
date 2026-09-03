from sarathi.shakti.translation.engine import (
    _CANONICAL_TRANSLATION_DATA_DIR,
    _load_translation_anubhava,
)
from sarathi.shakti.translation.glossary import GlossaryStore
from sarathi.shakti.translation.models import TranslationDirection


def test_glossary_terminology_applied_correctly() -> None:
    glossary = GlossaryStore()
    terms_hi_en = glossary.get_terms(TranslationDirection.HI_TO_EN)
    terms_en_hi = glossary.get_terms(TranslationDirection.EN_TO_HI)

    assert "भारत सरकार" in terms_hi_en
    assert terms_hi_en["भारत सरकार"] == "Government of India"
    assert "Government of India" in terms_en_hi
    assert terms_en_hi["Government of India"] == "भारत सरकार"


def test_anubhava_approved_corrections_loaded() -> None:
    corrs = _load_translation_anubhava(_CANONICAL_TRANSLATION_DATA_DIR)
    corrs_hi_en = corrs.get("hi-en", {})
    corrs_en_hi = corrs.get("en-hi", {})

    assert "उच्च न्यायालय" in corrs_hi_en
    assert corrs_hi_en["उच्च न्यायालय"] == "High Court"
    assert "High Court" in corrs_en_hi
    assert corrs_en_hi["High Court"] == "उच्च न्यायालय"


def test_domain_glossaries_loaded_from_directory() -> None:
    """Verify terms from all 10 domain glossaries in data/translation/glossaries are loaded."""
    glossary = GlossaryStore()
    terms_hi_en = glossary.get_terms(TranslationDirection.HI_TO_EN)
    terms_en_hi = glossary.get_terms(TranslationDirection.EN_TO_HI)

    # Check PMLA/IBC terms
    assert "Corporate Insolvency Resolution Process" in terms_en_hi
    assert terms_en_hi["Corporate Insolvency Resolution Process"] == "कॉर्पोरेट दिवाला समाधान प्रक्रिया"
    assert "कॉर्पोरेट दिवाला समाधान प्रक्रिया" in terms_hi_en
    assert terms_hi_en["कॉर्पोरेट दिवाला समाधान प्रक्रिया"] == "Corporate Insolvency Resolution Process"

    # Check Criminal Law (BNS/CrPC) terms
    assert "Anticipatory Bail" in terms_en_hi
    assert terms_en_hi["Anticipatory Bail"] == "अग्रिम जमानत"
    assert "अग्रिम जमानत" in terms_hi_en
    assert terms_hi_en["अग्रिम जमानत"] == "Anticipatory Bail"
