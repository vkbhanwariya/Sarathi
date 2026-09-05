"""Architectural boundary, import hygiene, and display name isolation tests."""

from __future__ import annotations

import ast
from pathlib import Path

from sarathi.nabhi.kosh import Kosh
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


class TestCrossPluginIsolation:
    """Verify Shakti plugins do not import implementation internals of sibling plugins."""

    def test_translation_has_no_font_conversion_imports(self) -> None:
        """Translation capability must not import from sarathi.shakti.font_conversion."""
        translation_dir = Path(__file__).resolve().parents[2] / "src" / "sarathi" / "shakti" / "translation"
        assert translation_dir.exists(), f"Translation directory {translation_dir} not found."

        violations: list[str] = []
        for py_file in translation_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "font_conversion" in alias.name:
                            violations.append(f"{py_file.name}:{node.lineno} imports '{alias.name}'")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if "font_conversion" in module:
                        violations.append(f"{py_file.name}:{node.lineno} imports from '{module}'")

        assert not violations, f"Cross-plugin import violations found in translation:\n" + "\n".join(violations)

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


class TestMukhaGenericPresentation:
    """Verify Mukha utilizes Kosh declarations dynamically."""

    def test_presenter_audit_uses_kosh_capabilities(self) -> None:
        """MukhaPresenter.audit_capability_status iterates kosh.capabilities() dynamically."""
        from sarathi.mukha.presenter import MukhaPresenter

        kosh = Kosh()
        from sarathi.shakti.ocr.plugin import PLUGIN_INFO as OCR_PLUGIN
        kosh.register_plugin(OCR_PLUGIN)
        kosh.register_capability(OCR_DECL)


        statuses = MukhaPresenter.audit_capability_status(kosh=kosh)
        assert "ocr" in statuses
        assert statuses["ocr"][0] is True
        assert "shakti.ocr" in statuses["ocr"][1]
        assert statuses["read_native"][0] is False
        assert "Not registered" in statuses["read_native"][1]

