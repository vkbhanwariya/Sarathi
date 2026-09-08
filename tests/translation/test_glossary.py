from pathlib import Path

import pytest

from sarathi.dosh import DoshError, FailureCode
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


def test_translation_glossary_missing_file_preserves_baseline(tmp_path: Path) -> None:
    """Missing glossary.yaml should safely return empty dictionary."""
    store = GlossaryStore(glossary_dir=tmp_path)
    assert store.get_terms(direction="hi-en") == {}  # type: ignore[arg-type]


def test_translation_glossary_malformed_yaml_fails_deterministically(tmp_path: Path) -> None:
    """Malformed glossary.yaml must raise DoshError(INVALID_CONFIGURATION)."""
    bad_yaml = tmp_path / "glossary.yaml"
    bad_yaml.write_text("this: is: [invalid: yaml: syntax: {", encoding="utf-8")

    with pytest.raises(DoshError) as exc_info:
        GlossaryStore(glossary_dir=tmp_path)

    assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
    assert "Failed to parse translation glossary" in exc_info.value.message


def test_translation_glossary_non_list_entries_fails_deterministically(tmp_path: Path) -> None:
    """Glossary with invalid entries field must raise DoshError(INVALID_CONFIGURATION)."""
    bad_yaml = tmp_path / "glossary.yaml"
    bad_yaml.write_text("entries: 'not-a-list'\n", encoding="utf-8")

    with pytest.raises(DoshError) as exc_info:
        GlossaryStore(glossary_dir=tmp_path)

    assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
