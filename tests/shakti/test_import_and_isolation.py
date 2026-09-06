"""Architectural boundary, import hygiene, and display name isolation tests."""

from __future__ import annotations

import pytest

from sarathi.sankalpa import CapabilityDeclaration, ExecutionProfile
from sarathi.shakti.bank_statements.plugin import (
    CAPABILITY_DECLARATION as BANK_DECL,
)
from sarathi.shakti.darshana.plugin import (
    CAPABILITY_DECLARATION as DARSHANA_DECL,
)
from sarathi.shakti.font_conversion.plugin import (
    CAPABILITY_DECLARATION as FONT_DECL,
)
from sarathi.shakti.native_extraction.plugin import (
    CAPABILITY_DECLARATION as NATIVE_DECL,
)
from sarathi.shakti.ocr.plugin import (
    CAPABILITY_DECLARATION as OCR_DECL,
)
from sarathi.shakti.text import (
    BaseSpanProtector,
    LegacyFontDetector,
    is_legacy_text,
)
from sarathi.shakti.translation.plugin import (
    CAPABILITY_DECLARATION as TRANSLATION_DECL,
)


class TestShaktiTextPrimitives:
    """Verify neutral shakti.text primitives operate as expected."""

    def test_shakti_text_primitives_work_correctly(self) -> None:
        """Verify neutral shakti.text primitives operate as expected."""
        assert is_legacy_text("vkids lkFk") is True
        assert is_legacy_text("Hello World English text") is False
        assert LegacyFontDetector.is_legacy_text("vkids lkFk") is True

        protector = BaseSpanProtector()
        placeholder = protector.format_placeholder(0)
        assert "\ue000" in placeholder
        assert "\ue001" in placeholder


class TestCapabilityDeclarationDisplayName:
    """Verify first-class display_name contract and built-in declarations."""

    def test_default_display_name_from_capability_id(self) -> None:
        """If display_name is omitted or blank, it defaults to title-cased capability_id."""
        decl = CapabilityDeclaration(
            capability_id="custom_extractor",
            plugin_id="custom.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        assert decl.display_name == "Custom Extractor"

    def test_explicit_display_name_preserved(self) -> None:
        """Explicit display_name is preserved as trimmed string."""
        decl = CapabilityDeclaration(
            capability_id="custom_extractor",
            plugin_id="custom.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            display_name="  My Custom Extractor Tool  ",
        )
        assert decl.display_name == "My Custom Extractor Tool"

    def test_builtin_declarations_have_descriptive_display_names(self) -> None:
        """All built-in capabilities declare human-readable display names."""
        assert DARSHANA_DECL.display_name == "Document Identification"
        assert NATIVE_DECL.display_name == "Native Document Extraction"
        assert OCR_DECL.display_name == "Optical Character Recognition (OCR)"
        assert BANK_DECL.display_name == "Bank Statement Normalization"
        assert FONT_DECL.display_name == "Legacy Font Conversion"
        assert TRANSLATION_DECL.display_name == "Machine Translation"


@pytest.mark.architecture
class TestShaktiImportHygiene:
    """Verify lazy re-exports in package roots prevent unnecessary eager loading."""

    def test_ocr_init_lazy_exports(self) -> None:
        """Importing sarathi.shakti.ocr accesses capability lazily via __getattr__."""
        import sarathi.shakti.ocr as ocr_pkg

        cap_cls = getattr(ocr_pkg, "OCRCapability")
        assert cap_cls is not None
        assert cap_cls.__name__ == "OCRCapability"

    def test_translation_init_lazy_exports(self) -> None:
        """Importing sarathi.shakti.translation accesses capability lazily via __getattr__."""
        import sarathi.shakti.translation as trans_pkg

        cap_cls = getattr(trans_pkg, "TranslationCapability")
        assert cap_cls is not None
        assert cap_cls.__name__ == "TranslationCapability"

    def test_font_conversion_init_lazy_exports(self) -> None:
        """Importing sarathi.shakti.font_conversion accesses capability lazily via __getattr__."""
        import sarathi.shakti.font_conversion as font_pkg

        cap_cls = getattr(font_pkg, "FontConversionCapability")
        assert cap_cls is not None
        assert cap_cls.__name__ == "FontConversionCapability"


class TestCapabilityTypographyAutonomy:
    """Verify each capability owns its typography locally without cross-capability coupling."""

    def test_capability_local_typography_autonomy(self) -> None:
        """Verify each capability owns its typography locally without cross-capability coupling."""
        from sarathi.shakti.font_conversion.font_size_normalizer import (
            get_font_size_adjustment,
            normalize_font_name,
            normalize_font_size,
        )
        from sarathi.shakti.ocr.typography import (
            DEVANAGARI_FONT as OCR_DEV_FONT,
        )
        from sarathi.shakti.ocr.typography import (
            ENGLISH_FONT as OCR_ENG_FONT,
        )
        from sarathi.shakti.ocr.typography import (
            normalize_size as ocr_norm_size,
        )
        from sarathi.shakti.ocr.typography import (
            output_font as ocr_output_font,
        )
        from sarathi.shakti.translation.typography import (
            DEVANAGARI_FONT as TRANS_DEV_FONT,
        )
        from sarathi.shakti.translation.typography import (
            ENGLISH_FONT as TRANS_ENG_FONT,
        )
        from sarathi.shakti.translation.typography import (
            normalize_size as trans_norm_size,
        )
        from sarathi.shakti.translation.typography import (
            output_font as trans_output_font,
        )

        # Baseline consistency across capabilities
        assert OCR_ENG_FONT == TRANS_ENG_FONT == "Times New Roman"
        assert OCR_DEV_FONT == TRANS_DEV_FONT == "Nirmala UI"

        # Autonomous helpers
        assert ocr_output_font(contains_devanagari=False) == "Times New Roman"
        assert trans_output_font(contains_devanagari=True) == "Nirmala UI"
        assert ocr_norm_size(None) == 12.0
        assert trans_norm_size(14.0) == 14.0

        # Font conversion normalizer calibrated dynamic scaling
        assert normalize_font_name("Kruti Dev 010") == "kruti dev 010"
        adj = get_font_size_adjustment(anchor_font="Kruti Dev 010", target_font="Nirmala UI")
        assert adj.scale == 0.75
        assert adj.offset_pt == 0.0
        assert normalize_font_size(16.0, anchor_font="Kruti Dev 010", target_font="Nirmala UI") == 12.0

