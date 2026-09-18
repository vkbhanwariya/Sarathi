"""Unit tests for LegalContextBuilder and LegalDocumentContext."""

from __future__ import annotations

from sarathi.shakti.translation.legal_context import LegalContextBuilder, LegalDocumentContext
from sarathi.shakti.translation.models import TranslationDirection


class TestLegalContextBuilder:
    """Verify court detection, statutory reference extraction, dynamic glossary matching, and prompt synthesis."""

    def test_detect_court_name_english_and_hindi(self) -> None:
        builder = LegalContextBuilder()

        sc_text = "IN THE SUPREME COURT OF INDIA AT NEW DELHI\nCIVIL APPELLATE JURISDICTION"
        assert builder.detect_court_name(sc_text) == "Supreme Court of India"

        dhc_text = "IN THE HIGH COURT OF DELHI AT NEW DELHI\nBEFORE HON'BLE MR. JUSTICE MANMOHAN"
        assert builder.detect_court_name(dhc_text) == "High Court of Delhi"

        ald_text = "उच्च न्यायालय इलाहाबाद\nमाननीय न्यायमूर्ति द्वारा पारित आदेश"
        assert builder.detect_court_name(ald_text) == "High Court of Judicature at Allahabad"

        nclat_text = "BEFORE THE NATIONAL COMPANY LAW APPELLATE TRIBUNAL, PRINCIPAL BENCH, NEW DELHI"
        assert builder.detect_court_name(nclat_text) == "National Company Law Appellate Tribunal (NCLAT)"

        drt_text = "BEFORE THE DEBTS RECOVERY TRIBUNAL-I, DELHI"
        assert builder.detect_court_name(drt_text) == "Debts Recovery Tribunal (DRT)"

        dist_text = "जिला एवं सत्र न्यायालय, लखनऊ\nफौजदारी वाद संख्या 456/2023"
        assert builder.detect_court_name(dist_text) == "District & Sessions Court"

    def test_detect_statutory_references(self) -> None:
        builder = LegalContextBuilder()
        text = (
            "The petitioner filed this application under Section 482 of the CrPC for quashing the FIR No. 123/2024 "
            "registered under Section 420 and Section 468 of the IPC. The respondent also initiated proceedings under "
            "Section 138 of the Negotiable Instruments Act and invoked Article 226 of the Constitution of India. "
            "Reliance was placed on AIR 1980 SC 1789 and (2021) 4 SCC 123."
        )
        refs = builder.detect_statutory_references(text)
        assert any("Section 482" in r for r in refs)
        assert any("Section 420" in r for r in refs)
        assert any("Section 138" in r for r in refs)
        assert any("Article 226" in r for r in refs)
        assert any("FIR No. 123/2024" in r for r in refs)

    def test_detect_statutory_references_hindi(self) -> None:
        builder = LegalContextBuilder()
        text = (
            "याचिकाकर्ता के विरुद्ध भारतीय दण्ड संहिता की धारा 420 एवं धारा 468 के तहत अपराध दर्ज है। "
            "दंड प्रक्रिया संहिता की धारा 482 के अंतर्गत आवेदन किया गया। धारा 138 परक्राम्य लिखत अधिनियम के तहत चेक अनादरण।"
        )
        refs = builder.detect_statutory_references(text)
        assert any("धारा 420" in r for r in refs)
        assert any("धारा 482" in r for r in refs)
        assert any("धारा 138" in r for r in refs)

    def test_dynamic_glossary_matching_hi_to_en(self) -> None:
        builder = LegalContextBuilder()
        hindi_order = (
            "माननीय उच्च न्यायालय ने याचिकाकर्ता की याचिका पर सुनवाई करते हुए आक्षेपित आदेश को निस्तारित किया। "
            "प्रतिवादी को निर्देश दिया गया कि वह साक्ष्य प्रस्तुत करे और संज्ञान ले।"
        )
        matched = builder.match_domain_glossary(hindi_order, direction=TranslationDirection.HI_TO_EN)
        assert isinstance(matched, dict)
        assert len(matched) >= 2
        # Verify specific legal terms are matched
        matched_keys = set(matched.keys())
        assert any("याचिकाकर्ता" in k or "आक्षेपित आदेश" in k or "निस्तारित" in k for k in matched_keys)

    def test_extract_context_english_high_court(self) -> None:
        builder = LegalContextBuilder()
        text = """
        IN THE HIGH COURT OF DELHI AT NEW DELHI
        W.P.(C) 4567/2023 & CM APPL. 1234/2023
        CNR No. DLHC010045672023

        RAMESH CHANDRA ... PETITIONER
        VERSUS
        UNION OF INDIA & ORS. ... RESPONDENTS

        CORAM:
        HON'BLE MR. JUSTICE PRATEEK JALAN

        JUDGMENT
        1. The petitioner has approached this Hon'ble Court under Article 226 of the Constitution of India challenging the impugned order.
        """
        ctx = builder.extract_context(text, direction=TranslationDirection.EN_TO_HI)
        assert ctx.is_legal_document is True
        assert ctx.court_name == "High Court of Delhi"
        assert ctx.cnr_number == "DLHC010045672023"
        assert "RAMESH CHANDRA" in ctx.petitioners
        assert any("UNION OF INDIA" in r for r in ctx.respondents)
        assert "PRATEEK JALAN" in ctx.judges
        assert any("Article 226" in r for r in ctx.statutory_references)
        assert ctx.to_dict()["is_legal_document"] is True

    def test_extract_context_non_legal_document_fallback(self) -> None:
        builder = LegalContextBuilder()
        plain_text = "The weather in New Delhi is pleasant today with mild breeze and clear sky."
        ctx = builder.extract_context(plain_text, direction=TranslationDirection.EN_TO_HI)
        assert ctx.is_legal_document is False
        assert ctx.court_name is None
        assert ctx.case_number is None
        assert ctx.cnr_number is None

    def test_format_system_prompt_structure(self) -> None:
        builder = LegalContextBuilder()
        ctx = LegalDocumentContext(
            court_name="High Court of Judicature at Allahabad",
            case_number="W.P.(C) 102/2024",
            cnr_number="UPHC01001022024",
            petitioners=("Sunil Sharma",),
            respondents=("State of Uttar Pradesh",),
            judges=("Rajesh Singh",),
            statutory_references=("Section 482 CrPC", "Section 420 IPC"),
            matched_glossary_terms={"याचिकाकर्ता": "petitioner", "निस्तारित": "disposed of"},
            is_legal_document=True,
        )

        prompt = builder.format_system_prompt(ctx, source_lang="Hindi", target_lang="English")
        assert "Senior Bilingual Judicial and Legal Translator" in prompt
        assert "High Court of Judicature at Allahabad" in prompt
        assert "W.P.(C) 102/2024" in prompt
        assert "UPHC01001022024" in prompt
        assert "Sunil Sharma" in prompt
        assert "State of Uttar Pradesh" in prompt
        assert "Section 482 CrPC" in prompt
        assert '"याचिकाकर्ता" -> "petitioner"' in prompt
        assert '"निस्तारित" -> "disposed of"' in prompt
        assert "Strictly preserve without alteration any structural placeholders" in prompt
        assert "Output ONLY the translated text" in prompt
