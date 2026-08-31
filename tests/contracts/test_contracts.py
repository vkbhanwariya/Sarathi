"""Comprehensive unit tests for Sankalpa — Canonical Contracts."""

import math
from pathlib import Path
import pytest

from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactRef,
    CanonicalDocument,
    CapabilityDeclaration,
    ConfidenceValue,
    CustomProfileOptions,
    DeviceRequirement,
    DeviceType,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    PluginInfo,
    ProvenanceRecord,
    Request,
    Result,
    SecurityDeclaration,
    TableData,
    TextSpan,
    WarningRecord,
)
import sarathi.sankalpa as sankalpa_module


class TestExecutionProfile:
    def test_canonical_profiles(self) -> None:
        assert ExecutionProfile.INSTANT == "instant"
        assert ExecutionProfile.ACCURATE == "accurate"
        assert ExecutionProfile.LAYOUT_PRESERVING == "layout_preserving"
        assert ExecutionProfile.CUSTOM == "custom"
        assert len(ExecutionProfile) == 4

    def test_from_string_parsing(self) -> None:
        assert ExecutionProfile.from_string("instant") == ExecutionProfile.INSTANT
        assert ExecutionProfile.from_string("Instant") == ExecutionProfile.INSTANT
        assert ExecutionProfile.from_string("ACCURATE") == ExecutionProfile.ACCURATE
        assert ExecutionProfile.from_string("layout-preserving") == ExecutionProfile.LAYOUT_PRESERVING
        assert ExecutionProfile.from_string("layout_preserving") == ExecutionProfile.LAYOUT_PRESERVING
        assert ExecutionProfile.from_string("Custom") == ExecutionProfile.CUSTOM

    def test_invalid_profile_parsing(self) -> None:
        with pytest.raises(ValueError, match="Invalid execution profile"):
            ExecutionProfile.from_string("auto")

    def test_custom_profile_options_immutability(self) -> None:
        opts = CustomProfileOptions(
            engine="rapidocr",
            options={"det_limit_side_len": 960},
            fallback_enabled=True,
        )
        assert opts.engine == "rapidocr"
        assert opts.options["det_limit_side_len"] == 960
        assert opts.fallback_enabled is True
        assert opts.validation_enabled is True

        # Verify options dictionary cannot be mutated
        with pytest.raises(TypeError):
            opts.options["det_limit_side_len"] = 1200  # type: ignore


class TestArtifactContracts:
    def test_input_ref_valid_and_immutable(self) -> None:
        inp = InputRef(
            input_id="inp-001",
            source_path=Path("Input/doc.pdf"),
            display_name="doc.pdf",
            size_bytes=1024,
            media_type="application/pdf",
            metadata={"source": "user_upload"},
        )
        assert inp.input_id == "inp-001"
        assert inp.source_path == Path("Input/doc.pdf")
        assert inp.size_bytes == 1024
        assert inp.media_type == "application/pdf"

        # Verify metadata cannot be mutated
        with pytest.raises(TypeError):
            inp.metadata["source"] = "tampered"  # type: ignore

    def test_input_ref_validation_failures(self) -> None:
        with pytest.raises(ValueError, match="input_id must be a non-empty string"):
            InputRef(
                input_id="",
                source_path=Path("Input/doc.pdf"),
                display_name="doc.pdf",
                size_bytes=10,
            )

        with pytest.raises(ValueError, match="display_name must be a non-empty string"):
            InputRef(
                input_id="inp-1",
                source_path=Path("Input/doc.pdf"),
                display_name="  ",
                size_bytes=10,
            )

        with pytest.raises(ValueError, match="size_bytes cannot be negative"):
            InputRef(
                input_id="inp-1",
                source_path=Path("Input/doc.pdf"),
                display_name="doc.pdf",
                size_bytes=-5,
            )

    def test_artifact_intent_and_ref(self) -> None:
        intent = ArtifactIntent(
            name="consolidated.parquet",
            role="primary_dataset",
            media_type="application/vnd.apache.parquet",
        )
        assert intent.name == "consolidated.parquet"
        assert intent.role == "primary_dataset"

        ref = ArtifactRef(
            artifact_id="art-001",
            role="primary_dataset",
            media_type="application/vnd.apache.parquet",
            path=Path("Output/Run-1/consolidated.parquet"),
            size_bytes=4096,
            checksum_sha256="abc123hash",
        )
        assert ref.artifact_id == "art-001"
        assert ref.size_bytes == 4096
        assert ref.checksum_sha256 == "abc123hash"

        with pytest.raises(TypeError):
            ref.metadata["new_key"] = "val"  # type: ignore


class TestPluginAndSecurityContracts:
    def test_security_declaration_defaults(self) -> None:
        sec = SecurityDeclaration()
        assert sec.pii_access is False
        assert sec.local_processing_only is True
        assert sec.network_access is False
        assert sec.external_processing is False
        assert sec.required_secrets == ()

    def test_security_declaration_secrets_cleaning(self) -> None:
        sec = SecurityDeclaration(
            pii_access=True,
            network_access=True,
            external_processing=True,
            local_processing_only=False,
            required_secrets=("OPENAI_API_KEY", "OPENAI_API_KEY", " AWS_SECRET ", ""),
        )
        assert sec.required_secrets == ("AWS_SECRET", "OPENAI_API_KEY")

    def test_plugin_info_valid_and_immutable(self) -> None:
        sec = SecurityDeclaration()
        info = PluginInfo(
            plugin_id="shakti.ocr",
            name="OCR Capability",
            version="2.0.0",
            description="Optical Character Recognition",
            security=sec,
            capabilities=("ocr",),
            metadata={"vendor": "internal"},
        )
        assert info.plugin_id == "shakti.ocr"
        assert info.name == "OCR Capability"
        assert info.capabilities == ("ocr",)

        with pytest.raises(TypeError):
            info.metadata["vendor"] = "other"  # type: ignore

    def test_plugin_info_validation_failures(self) -> None:
        with pytest.raises(ValueError, match="plugin_id must be a non-empty string"):
            PluginInfo(plugin_id="", name="test", version="1.0")


class TestCapabilityContracts:
    def test_device_type(self) -> None:
        assert DeviceType.CPU == "cpu"
        assert DeviceType.GPU == "gpu"
        assert DeviceType.NPU == "npu"
        assert DeviceType.from_string("GPU") == DeviceType.GPU

        with pytest.raises(ValueError, match="Invalid device type"):
            DeviceType.from_string("tpu")

    def test_device_requirement(self) -> None:
        req = DeviceRequirement(
            preferred_devices=(DeviceType.GPU, DeviceType.NPU),
            supported_devices=(DeviceType.GPU, DeviceType.NPU, DeviceType.CPU),
            parallelizable=True,
            estimated_memory_bytes=512 * 1024 * 1024,
            priority=10,
        )
        assert req.preferred_devices == (DeviceType.GPU, DeviceType.NPU)
        assert req.estimated_memory_bytes == 512 * 1024 * 1024

    def test_capability_declaration_valid(self) -> None:
        decl = CapabilityDeclaration(
            capability_id="ocr",
            plugin_id="shakti.ocr",
            version="2.0.0",
            supported_profiles=(ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE),
            supported_input_types=("image/png", "image/jpeg", "application/pdf"),
            produces_artifacts=True,
        )
        assert decl.capability_id == "ocr"
        assert decl.supported_profiles == (ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE)
        assert "image/png" in decl.supported_input_types


class TestRequestContracts:
    def test_request_valid_and_immutable(self) -> None:
        inp = InputRef(
            input_id="inp-1",
            source_path=Path("Input/stmt.pdf"),
            display_name="stmt.pdf",
            size_bytes=100,
        )
        req = Request(
            request_id="req-123",
            requirement="bank_statements",
            inputs=(inp,),
            profile=ExecutionProfile.ACCURATE,
            custom_options={"engine": "polars"},
            metadata={"origin": "cli"},
        )
        assert req.request_id == "req-123"
        assert req.requirement == "bank_statements"
        assert req.inputs == (inp,)
        assert req.profile == ExecutionProfile.ACCURATE

        with pytest.raises(TypeError):
            req.custom_options["engine"] = "pandas"  # type: ignore
        with pytest.raises(TypeError):
            req.metadata["origin"] = "gui"  # type: ignore

    def test_request_validation_failures(self) -> None:
        with pytest.raises(ValueError, match="inputs cannot be empty"):
            Request(
                request_id="req-1",
                requirement="bank_statements",
                inputs=(),
            )

        with pytest.raises(ValueError, match="request_id must be a non-empty string"):
            inp = InputRef(
                input_id="inp-1",
                source_path=Path("Input/stmt.pdf"),
                display_name="stmt.pdf",
                size_bytes=100,
            )
            Request(
                request_id="",
                requirement="bank_statements",
                inputs=(inp,),
            )


class TestContextContracts:
    def test_execution_context_immutability_and_child_span(self) -> None:
        ctx = ExecutionContext(
            run_id="run-100",
            request_id="req-100",
            trace_id="trace-100",
            span_id="span-root",
            profile=ExecutionProfile.INSTANT,
            metadata={"env": "prod"},
        )
        assert ctx.run_id == "run-100"
        assert ctx.parent_span_id is None

        # Verify metadata cannot be mutated
        with pytest.raises(TypeError):
            ctx.metadata["env"] = "dev"  # type: ignore

        child_ctx = ctx.child_span("span-child-1", extra_metadata={"step": "1"})
        assert child_ctx.run_id == "run-100"
        assert child_ctx.trace_id == "trace-100"
        assert child_ctx.span_id == "span-child-1"
        assert child_ctx.parent_span_id == "span-root"
        assert child_ctx.metadata["step"] == "1"
        assert child_ctx.metadata["env"] == "prod"

        retry_ctx = ctx.with_retry(quarantine_attempt=2)
        assert retry_ctx.is_retry is True
        assert retry_ctx.quarantine_attempt == 2


class TestDocumentContracts:
    def test_canonical_document_structure_and_immutability(self) -> None:
        span = TextSpan(
            text="Account Statement",
            confidence=0.98,
            bounding_box=(10.0, 20.0, 100.0, 40.0),
            language="en",
            metadata={"font": "Arial"},
        )
        table = TableData(
            name="transactions",
            headers=("Date", "Description", "Amount"),
            rows=(("2026-01-01", "Opening", "100.00"),),
            metadata={"sheet": "Sheet1"},
        )
        page = PageData(
            page_number=1,
            text="Account Statement",
            spans=(span,),
            tables=(table,),
        )
        doc = CanonicalDocument(
            document_id="doc-1",
            source_input_id="inp-1",
            pages=(page,),
            tables=(table,),
            text="Account Statement",
        )

        assert doc.document_id == "doc-1"
        assert len(doc.pages) == 1
        assert doc.pages[0].page_number == 1
        assert len(doc.tables) == 1
        assert doc.tables[0].headers == ("Date", "Description", "Amount")

        with pytest.raises(TypeError):
            span.metadata["font"] = "Helvetica"  # type: ignore
        with pytest.raises(TypeError):
            table.metadata["sheet"] = "Sheet2"  # type: ignore
        with pytest.raises(TypeError):
            doc.metadata["type"] = "pdf"  # type: ignore

    def test_document_validation(self) -> None:
        with pytest.raises(ValueError, match="document_id must be a non-empty string"):
            CanonicalDocument(document_id="")

        with pytest.raises(ValueError, match="page_number must be >= 1"):
            PageData(page_number=0)

        with pytest.raises(ValueError, match="bounding_box must be a 4-tuple"):
            TextSpan(text="test", bounding_box=(0.0, 0.0, 1.0))  # type: ignore

        with pytest.raises(ValueError, match="confidence cannot be NaN or Inf"):
            TextSpan(text="test", confidence=float("nan"))


class TestResultContracts:
    def test_confidence_unavailable_by_default(self) -> None:
        res = Result(data={"key": "val"})
        assert res.confidence is None
        assert res.data == {"key": "val"}
        assert res.artifacts == ()
        assert res.warnings == ()
        assert res.provenance == ()

    def test_confidence_value_with_evidence_and_immutability(self) -> None:
        conf = ConfidenceValue(
            score=0.95,
            method="ocr_char_probabilities_mean",
            evidence={"min_prob": 0.88, "word_count": 42},
        )
        assert conf.score == 0.95
        assert conf.as_ratio == 0.95
        assert conf.as_percent == 95.0
        assert conf.method == "ocr_char_probabilities_mean"
        assert conf.evidence["word_count"] == 42

        with pytest.raises(TypeError):
            conf.evidence["word_count"] = 50  # type: ignore

        # Scale 0..100
        conf100 = ConfidenceValue(score=95.0, method="model_confidence")
        assert conf100.as_ratio == 0.95
        assert conf100.as_percent == 95.0

    def test_confidence_validation_failures(self) -> None:
        with pytest.raises(ValueError, match="Confidence score must be in range"):
            ConfidenceValue(score=150.0, method="invalid")

        with pytest.raises(ValueError, match="Confidence score must be in range"):
            ConfidenceValue(score=-0.1, method="invalid")

        with pytest.raises(ValueError, match="Confidence score cannot be NaN or Inf"):
            ConfidenceValue(score=float("nan"), method="invalid")

        with pytest.raises(ValueError, match="Confidence score cannot be NaN or Inf"):
            ConfidenceValue(score=float("inf"), method="invalid")

        with pytest.raises(ValueError, match="Confidence method must be a non-empty string"):
            ConfidenceValue(score=0.9, method="")

        with pytest.raises(ValueError, match="Confidence method must be a non-empty string"):
            ConfidenceValue(score=0.9, method="   ")

    def test_provenance_and_warning_records(self) -> None:
        prov = ProvenanceRecord(
            source_input_id="inp-1",
            source_file="stmt.pdf",
            stage="read",
            plugin_id="shakti.native_extraction",
            capability_id="read.native_extraction",
            page_number=1,
            evidence={"reader": "calamine"},
        )
        warn = WarningRecord(
            code="UNRESOLVED_HEADER",
            message="Column 4 header was not mapped.",
            stage="map",
        )
        res = Result(
            data={"status": "ok"},
            provenance=(prov,),
            warnings=(warn,),
        )
        assert len(res.provenance) == 1
        assert res.provenance[0].capability_id == "read.native_extraction"
        assert len(res.warnings) == 1
        assert res.warnings[0].code == "UNRESOLVED_HEADER"

        with pytest.raises(TypeError):
            prov.evidence["reader"] = "openpyxl"  # type: ignore
        with pytest.raises(TypeError):
            warn.context["extra"] = "val"  # type: ignore
        with pytest.raises(TypeError):
            res.metadata["run"] = "test"  # type: ignore


class TestDomainAgnosticContracts:
    def test_no_domain_specific_coupling_in_sankalpa(self) -> None:
        """Verify that core contracts do not contain domain-specific subclasses or hardcoded branches."""
        req = Request(
            request_id="req-generic",
            requirement="generic_task",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("data.bin"),
                    display_name="data.bin",
                    size_bytes=256,
                ),
            ),
        )
        ctx = ExecutionContext(
            run_id="run-1",
            request_id="req-generic",
            trace_id="tr-1",
            span_id="sp-1",
        )
        res = Result(data={"arbitrary": "value"})

        assert req.requirement == "generic_task"
        assert ctx.run_id == "run-1"
        assert res.data == {"arbitrary": "value"}

    def test_canonical_exports_complete_and_clean(self) -> None:
        expected_exports = {
            "ArtifactIntent",
            "ArtifactRef",
            "CanonicalDocument",
            "CapabilityDeclaration",
            "ConfidenceValue",
            "CustomProfileOptions",
            "DeviceRequirement",
            "DeviceType",
            "ExecutionContext",
            "ExecutionProfile",
            "InputRef",
            "PageData",
            "PluginInfo",
            "ProvenanceRecord",
            "Request",
            "Result",
            "SecurityDeclaration",
            "TableData",
            "TextSpan",
            "WarningRecord",
        }
        assert set(sankalpa_module.__all__) == expected_exports
        for name in expected_exports:
            assert hasattr(sankalpa_module, name)
