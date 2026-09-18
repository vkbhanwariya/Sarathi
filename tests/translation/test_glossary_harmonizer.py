"""Unit tests for on-device GlossaryHarmonizer and lean prompt seeding."""

from __future__ import annotations

from sarathi.shakti.translation.harmonizer import GlossaryHarmonizer
from sarathi.shakti.translation.legal_context import LegalContextBuilder, LegalDocumentContext
from sarathi.shakti.translation.models import TranslationDirection


class TestGlossaryHarmonizer:
    """Verify on-device statutory terminology normalization."""

    def test_harmonize_proceeds_of_crime_variants_hindi(self) -> None:
        harmonizer = GlossaryHarmonizer()

        # Colloquial variations -> Canonical statutory "अपराध के आगम"
        inputs = [
            "अभियुक्त ने अपराध की कमाई को छुपाया।",
            "यह राशि अपराध से प्राप्त आय का हिस्सा है।",
            "अपराध से अर्जित आय को जब्त किया गया।",
            "उसने जुर्म का पैसा विदेश भेजा।",
        ]
        expected = [
            "अभियुक्त ने अपराध के आगम को छुपाया।",
            "यह राशि अपराध के आगम का हिस्सा है।",
            "अपराध के आगम को जब्त किया गया।",
            "उसने अपराध के आगम विदेश भेजा।",
        ]

        for inp, exp in zip(inputs, expected):
            assert harmonizer.harmonize(inp, TranslationDirection.EN_TO_HI) == exp

    def test_harmonize_reporting_entity_variants_hindi(self) -> None:
        harmonizer = GlossaryHarmonizer()

        inp = "रिपोर्टिंग संस्था ने संदिग्ध संव्यवहार की सूचना देने वाली संस्था के रूप में दी।"
        res = harmonizer.harmonize(inp, TranslationDirection.EN_TO_HI)
        assert "रिपोर्टकर्ता इकाई ने संदिग्ध संव्यवहार की रिपोर्टकर्ता इकाई के रूप में दी।" == res

    def test_harmonize_judicial_bodies_hindi(self) -> None:
        harmonizer = GlossaryHarmonizer()

        inp = "मामला विशेष अदालत और अपीलीय न्यायाधिकरण तथा न्यायनिर्णायक प्राधिकरण के समक्ष लंबित है।"
        res = harmonizer.harmonize(inp, "en-hi")
        assert "विशेष न्यायालय" in res
        assert "अपील अधिकरण" in res
        assert "न्यायनिर्णायक प्राधिकारी" in res

    def test_harmonize_english_variants(self) -> None:
        harmonizer = GlossaryHarmonizer()

        inp = "The Enforcement Directorate seized the Crime Income under the Anti-Money Laundering Act."
        res = harmonizer.harmonize(inp, TranslationDirection.HI_TO_EN)
        assert "Proceeds of Crime" in res
        assert "Prevention of Money Laundering Act, 2002" in res

    def test_custom_variants_harmonization(self) -> None:
        custom_map = {"गैर-कानूनी फायदा": "अवैध लाभ"}
        harmonizer = GlossaryHarmonizer(custom_variants=custom_map)

        inp = "उसने गैर-कानूनी फायदा उठाया।"
        res = harmonizer.harmonize(inp, TranslationDirection.EN_TO_HI)
        assert res == "उसने अवैध लाभ उठाया।"

    def test_lean_prompt_caps_glossary_terms(self) -> None:
        builder = LegalContextBuilder()
        dummy_terms = {f"Term_{i}": f"शर्त_{i}" for i in range(25)}
        ctx = LegalDocumentContext(
            is_legal_document=True,
            court_name="High Court of Delhi",
            matched_glossary_terms=dummy_terms,
        )

        # Default cap is 5
        prompt = builder.format_system_prompt(ctx, "English", "Hindi")
        assert prompt.count('"Term_') == 5

        # Custom cap
        prompt_custom = builder.format_system_prompt(ctx, "English", "Hindi", max_glossary_terms=3)
        assert prompt_custom.count('"Term_') == 3
