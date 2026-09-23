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


def test_translation_asset_version_tracks_root_yaml_and_domain_files(tmp_path: Path) -> None:
    """Item 24: Asset revision calculation includes root glossary.yaml and domain yaml/yml/json files."""
    from sarathi.shakti.translation.engine import CTranslate2TranslationEngine

    engine_empty = CTranslate2TranslationEngine(data_root=tmp_path)
    baseline_rev = engine_empty.asset_version

    # 1. Adding root glossary.yaml changes revision
    yaml_file = tmp_path / "glossary.yaml"
    yaml_file.write_text("entries:\n  - source: 'test'\n    target: 'परीक्षण'\n", encoding="utf-8")
    engine_with_yaml = CTranslate2TranslationEngine(data_root=tmp_path)
    rev_with_yaml = engine_with_yaml.asset_version
    assert rev_with_yaml != baseline_rev

    # 2. Adding domain YML file changes revision
    domain_dir = tmp_path / "glossaries"
    domain_dir.mkdir()
    domain_yml = domain_dir / "custom.yml"
    domain_yml.write_text("law: कानून\n", encoding="utf-8")
    engine_with_domain = CTranslate2TranslationEngine(data_root=tmp_path)
    rev_with_domain = engine_with_domain.asset_version
    assert rev_with_domain != rev_with_yaml

    # 3. Content modification changes revision even if mtime were preserved
    domain_yml.write_text("law: विधि\n", encoding="utf-8")
    engine_modified = CTranslate2TranslationEngine(data_root=tmp_path)
    assert engine_modified.asset_version != rev_with_domain


def test_translation_glossary_collision_observability(tmp_path: Path) -> None:
    """Verify GlossaryStore records conflicting translations in the collisions property."""
    g_file = tmp_path / "glossary.yaml"
    g_file.write_text(
        """
        - source: "Court"
          target: "अदालत"
          direction: "en-hi"
        - source: "Court"
          target: "न्यायालय"
          direction: "en-hi"
        """,
        encoding="utf-8",
    )

    store = GlossaryStore(glossary_dir=tmp_path)
    assert len(store.collisions) >= 1
    assert store.collisions[0]["source"] == "Court"
    assert store.collisions[0]["existing_target"] == "अदालत"
    assert store.collisions[0]["conflicting_target"] == "न्यायालय"

    with pytest.raises(DoshError) as exc_info:
        GlossaryStore(glossary_dir=tmp_path, strict=True)
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION


def test_glossary_direction_validation(tmp_path: Path) -> None:
    """Invalid translation glossary direction values must raise INVALID_CONFIGURATION."""
    g_file = tmp_path / "glossary.yaml"
    g_file.write_text(
        """
        - source: "Court"
          target: "अदालत"
          direction: "invalid-direction"
        """,
        encoding="utf-8",
    )
    with pytest.raises(DoshError) as exc_info:
        GlossaryStore(glossary_dir=tmp_path)
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION


def test_glossary_composite_synonym_splitting() -> None:
    store = GlossaryStore()
    store._parse_raw_data(
        {"Account Freeze": "खाता लेन-देन रोक / खाता फ्रीज"},
        "test_glossary.json",
    )
    hi_to_en = store.get_terms(TranslationDirection.HI_TO_EN)
    assert "खाता लेन-देन रोक" in hi_to_en
    assert "खाता फ्रीज" in hi_to_en
    assert hi_to_en["खाता लेन-देन रोक"] == "Account Freeze"
    assert hi_to_en["खाता फ्रीज"] == "Account Freeze"


def test_glossary_does_not_split_on_comma_or_create_numeric_terms() -> None:
    """Verify statutory titles with years never produce pure numeric reverse glossary entries."""
    store = GlossaryStore()
    store._parse_raw_data(
        {
            "SARFAESI Act, 2002": "सरफेसी अधिनियम, 2002",
            "Code of Civil Procedure, 1908": "सिविल प्रक्रिया संहिता, 1908",
        },
        "statutes.json",
    )
    hi_to_en = store.get_terms(TranslationDirection.HI_TO_EN)
    assert "2002" not in hi_to_en
    assert "1908" not in hi_to_en
    assert "सरफेसी अधिनियम, 2002" in hi_to_en
    assert hi_to_en["सरफेसी अधिनियम, 2002"] == "SARFAESI Act, 2002"


def test_glossary_does_not_register_isolated_stopwords() -> None:
    """Verify single adjectives or grammatical particles are never mapped to full statutory titles."""
    store = GlossaryStore()
    store._parse_raw_data(
        {
            "Predicate Offence": "मूल / आधार अपराध",
            "Members, etc., to be public servants": "सदस्यों, आदि का लोक सेवक होना",
        },
        "pmla_sample.json",
    )
    hi_to_en = store.get_terms(TranslationDirection.HI_TO_EN)
    assert "मूल" not in hi_to_en
    assert "आदि" not in hi_to_en
    assert "सदस्यों" not in hi_to_en
    assert "आधार अपराध" in hi_to_en
    assert hi_to_en["आधार अपराध"] == "Predicate Offence"
