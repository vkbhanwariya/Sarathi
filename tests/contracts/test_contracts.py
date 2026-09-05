"""Comprehensive unit tests for Sankalpa — Canonical Contracts."""

from pathlib import Path

import pytest

import sarathi.sankalpa as sankalpa_module
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    ArtifactRef,
    CanonicalDocument,
    Capability,
    CapabilityDeclaration,
    ConfidenceValue,
    CustomProfileOptions,
    DeviceRequirement,
    DeviceType,
    ExecutionBinding,
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

    def test_artifact_intent_valid_relative_paths(self) -> None:
        intent1 = ArtifactIntent(
            name="consolidated.parquet",
            role="primary_dataset",
            media_type="application/vnd.apache.parquet",
            relative_path=Path("nested/dir/consolidated.parquet"),
        )
        assert intent1.relative_path == Path("nested/dir/consolidated.parquet")

        intent2 = ArtifactIntent(
            name="summary.json",
            role="summary",
            media_type="application/json",
            relative_path="summary.json",
        )
        assert intent2.relative_path == Path("summary.json")

        intent3 = ArtifactIntent(
            name="output.bin",
            role="data",
            media_type="application/octet-stream",
            relative_path=r"nested\dir\output.bin",
        )
        assert intent3.relative_path == Path(r"nested\dir\output.bin")

    def test_artifact_intent_cross_platform_path_safety(self) -> None:
        # POSIX absolute paths
        with pytest.raises(ValueError, match="genuinely relative"):
            ArtifactIntent(
                name="out.bin",
                role="data",
                media_type="application/octet-stream",
                relative_path="/etc/passwd",
            )

        # Windows absolute / drive-rooted paths
        with pytest.raises(ValueError, match="genuinely relative|drive specifier"):
            ArtifactIntent(
                name="out.bin",
                role="data",
                media_type="application/octet-stream",
                relative_path=r"C:\Windows\out.bin",
            )

        with pytest.raises(ValueError, match="genuinely relative"):
            ArtifactIntent(
                name="out.bin",
                role="data",
                media_type="application/octet-stream",
                relative_path=r"\Windows\out.bin",
            )

        # Traversal '..' parts under POSIX and Windows syntax
        with pytest.raises(ValueError, match="directory traversal"):
            ArtifactIntent(
                name="out.bin",
                role="data",
                media_type="application/octet-stream",
                relative_path="../escape.bin",
            )

        with pytest.raises(ValueError, match="directory traversal"):
            ArtifactIntent(
                name="out.bin",
                role="data",
                media_type="application/octet-stream",
                relative_path=r"sub\..\escape.bin",
            )

        with pytest.raises(ValueError, match="directory traversal"):
            ArtifactIntent(
                name="out.bin",
                role="data",
                media_type="application/octet-stream",
                relative_path=Path("sub/../../escape.bin"),
            )

        # Empty / dot paths
        with pytest.raises(ValueError, match="empty or dot"):
            ArtifactIntent(
                name="out.bin",
                role="data",
                media_type="application/octet-stream",
                relative_path=".",
            )

    def test_artifact_ref(self) -> None:
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

    def test_security_declaration_consistency_rules(self) -> None:
        # Valid external declaration
        valid_external = SecurityDeclaration(
            network_access=True,
            external_processing=True,
            local_processing_only=False,
            required_secrets=("OPENAI_KEY",),
        )
        assert valid_external.external_processing is True
        assert valid_external.network_access is True
        assert valid_external.local_processing_only is False

        # External processing requires network_access=True
        with pytest.raises(ValueError, match="external_processing=True requires network_access=True"):
            SecurityDeclaration(
                external_processing=True,
                network_access=False,
                local_processing_only=False,
            )

        # External processing cannot coexist with local_processing_only=True
        with pytest.raises(ValueError, match="cannot coexist with local_processing_only=True"):
            SecurityDeclaration(
                external_processing=True,
                network_access=True,
                local_processing_only=True,
            )

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

    def test_device_requirement_ordering_and_validation(self) -> None:
        req = DeviceRequirement(
            preferred_devices=[DeviceType.GPU, DeviceType.NPU],
            supported_devices=[DeviceType.GPU, DeviceType.NPU, DeviceType.CPU],
            parallelizable=True,
            estimated_memory_bytes=512 * 1024 * 1024,
            priority=10,
        )
        assert req.preferred_devices == (DeviceType.GPU, DeviceType.NPU)
        assert req.supported_devices == (DeviceType.GPU, DeviceType.NPU, DeviceType.CPU)

        # Reject sets
        with pytest.raises(TypeError, match="ordered sequence"):
            DeviceRequirement(preferred_devices={DeviceType.CPU})  # type: ignore

        with pytest.raises(TypeError, match="ordered sequence"):
            DeviceRequirement(supported_devices={DeviceType.CPU})  # type: ignore

        # Reject empty
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceRequirement(preferred_devices=())

        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceRequirement(supported_devices=())

        # Reject duplicates
        with pytest.raises(ValueError, match="Duplicate device"):
            DeviceRequirement(
                preferred_devices=(DeviceType.CPU, DeviceType.CPU),
                supported_devices=(DeviceType.CPU,),
            )

        with pytest.raises(ValueError, match="Duplicate device"):
            DeviceRequirement(
                preferred_devices=(DeviceType.CPU,),
                supported_devices=(DeviceType.CPU, DeviceType.CPU),
            )

        # Preferred must be subset of supported
        with pytest.raises(ValueError, match="must also be in supported_devices"):
            DeviceRequirement(
                preferred_devices=(DeviceType.GPU,),
                supported_devices=(DeviceType.CPU,),
            )

    def test_capability_declaration_profiles_must_be_explicit(self) -> None:
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

        # Reject sets for supported_profiles
        with pytest.raises(TypeError, match="ordered sequence"):
            CapabilityDeclaration(
                capability_id="ocr",
                plugin_id="shakti.ocr",
                version="2.0.0",
                supported_profiles={ExecutionProfile.INSTANT},  # type: ignore
            )

        # Reject empty profiles
        with pytest.raises(ValueError, match="cannot be empty"):
            CapabilityDeclaration(
                capability_id="ocr",
                plugin_id="shakti.ocr",
                version="2.0.0",
                supported_profiles=(),
            )

        # Reject duplicate profiles
        with pytest.raises(ValueError, match="Duplicate profile"):
            CapabilityDeclaration(
                capability_id="ocr",
                plugin_id="shakti.ocr",
                version="2.0.0",
                supported_profiles=(ExecutionProfile.INSTANT, ExecutionProfile.INSTANT),
            )


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
            inputs=[inp],
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

    def test_request_safe_requirement_identifier(self) -> None:
        inp = InputRef(input_id="i1", source_path=Path("a.pdf"), display_name="a.pdf", size_bytes=10)

        # Valid requirement identifiers
        for valid_req in ("bank_statements", "ocr", "font-conversion", "extract_v2_data", "task1"):
            req = Request(request_id="r1", requirement=valid_req, inputs=(inp,))
            assert req.requirement == valid_req

        # Invalid requirement identifiers
        for invalid_req in (
            "Bank_Statements",  # uppercase
            "bank statements",  # space
            "bank/statement",  # slash
            "bank\\statement",  # backslash
            "bank.statement",  # dot
            "../bank",  # path traversal
            "",  # empty
            "   ",  # whitespace
        ):
            with pytest.raises(ValueError, match="safe stable identifier"):
                Request(request_id="r1", requirement=invalid_req, inputs=(inp,))

    def test_request_rejects_sets_and_duplicate_input_ids(self) -> None:
        inp1 = InputRef(input_id="inp-1", source_path=Path("1.pdf"), display_name="1.pdf", size_bytes=10)
        inp1_dup = InputRef(input_id="inp-1", source_path=Path("1_dup.pdf"), display_name="1_dup.pdf", size_bytes=20)

        # Reject sets
        with pytest.raises(TypeError, match="ordered sequence"):
            Request(request_id="r1", requirement="ocr", inputs={"inp1", "inp2"})  # type: ignore

        # Reject duplicate input_id
        with pytest.raises(ValueError, match="Duplicate input_id"):
            Request(request_id="r1", requirement="ocr", inputs=(inp1, inp1_dup))


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

    def test_execution_context_with_execution_binding(self) -> None:
        ctx = ExecutionContext(
            run_id="run-100",
            request_id="req-100",
            trace_id="trace-100",
            span_id="span-root",
        )
        assert ctx.execution_binding is None

        binding = ExecutionBinding(
            device_id="cpu-0",
            device_type=DeviceType.CPU,
            backend="cpu",
            backend_device_id="CPU",
            is_spillover=False,
        )
        bound = ctx.with_execution_binding(binding)
        assert bound.execution_binding == binding
        assert bound.child_span("child-1").execution_binding == binding
        assert bound.with_retry(1).execution_binding == binding


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

        # TextSpan ratio confidence validation
        with pytest.raises(ValueError, match="confidence cannot be NaN or Inf"):
            TextSpan(text="test", confidence=float("nan"))

        with pytest.raises(ValueError, match="confidence must be a ratio"):
            TextSpan(text="test", confidence=95.0)

        with pytest.raises(ValueError, match="confidence must be a ratio"):
            TextSpan(text="test", confidence=-0.05)

    def test_textspan_confidence_rejects_bool_and_non_numeric(self) -> None:
        with pytest.raises(TypeError, match="cannot be a boolean"):
            TextSpan(text="test", confidence=True)

        with pytest.raises(TypeError, match="cannot be a boolean"):
            TextSpan(text="test", confidence=False)

        with pytest.raises(TypeError, match="must be numeric"):
            TextSpan(text="test", confidence="0.95")  # type: ignore

        # Int converted to float
        span1 = TextSpan(text="test", confidence=1)
        assert span1.confidence == 1.0
        assert isinstance(span1.confidence, float)

        span0 = TextSpan(text="test", confidence=0)
        assert span0.confidence == 0.0
        assert isinstance(span0.confidence, float)


class TestResultContracts:
    def test_confidence_unavailable_by_default(self) -> None:
        res = Result(data={"key": "val"})
        assert res.confidence is None
        assert res.data == {"key": "val"}
        assert res.artifacts == ()
        assert res.warnings == ()
        assert res.provenance == ()

    def test_confidence_value_ratio_only_with_evidence(self) -> None:
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

    def test_confidence_value_rejects_bool_and_non_numeric(self) -> None:
        with pytest.raises(TypeError, match="cannot be a boolean"):
            ConfidenceValue(score=True, method="ocr", evidence={"k": 1})

        with pytest.raises(TypeError, match="cannot be a boolean"):
            ConfidenceValue(score=False, method="ocr", evidence={"k": 1})

        with pytest.raises(TypeError, match="must be numeric"):
            ConfidenceValue(score="0.95", method="ocr", evidence={"k": 1})  # type: ignore

        # Numeric int normalized to float
        conf_int = ConfidenceValue(score=1, method="exact_match", evidence={"rule": "crc"})
        assert conf_int.score == 1.0
        assert isinstance(conf_int.score, float)

    def test_confidence_validation_failures(self) -> None:
        # Rejection of percentage values
        with pytest.raises(ValueError, match="ratio in range"):
            ConfidenceValue(score=95.0, method="ocr", evidence={"cnt": 1})

        with pytest.raises(ValueError, match="ratio in range"):
            ConfidenceValue(score=1.05, method="ocr", evidence={"cnt": 1})

        with pytest.raises(ValueError, match="ratio in range"):
            ConfidenceValue(score=-0.01, method="ocr", evidence={"cnt": 1})

        with pytest.raises(ValueError, match="cannot be NaN or Inf"):
            ConfidenceValue(score=float("nan"), method="ocr", evidence={"cnt": 1})

        with pytest.raises(ValueError, match="cannot be NaN or Inf"):
            ConfidenceValue(score=float("inf"), method="ocr", evidence={"cnt": 1})

        # Rejection of empty/whitespace method
        with pytest.raises(ValueError, match="non-empty string"):
            ConfidenceValue(score=0.9, method="", evidence={"cnt": 1})

        with pytest.raises(ValueError, match="non-empty string"):
            ConfidenceValue(score=0.9, method="   ", evidence={"cnt": 1})

        # Rejection of empty evidence mapping
        with pytest.raises(ValueError, match="non-empty mapping"):
            ConfidenceValue(score=0.9, method="valid_method", evidence={})

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

    def test_artifact_payload_contract(self) -> None:
        intent = ArtifactIntent(name="report.txt", role="report", media_type="text/plain")
        payload = ArtifactPayload(intent=intent, content=b"report content bytes")
        assert payload.intent == intent
        assert payload.content == b"report content bytes"

        # Bytearray normalized to immutable bytes
        payload_ba = ArtifactPayload(intent=intent, content=bytearray(b"bytearray"))
        assert isinstance(payload_ba.content, bytes)
        assert payload_ba.content == b"bytearray"

        with pytest.raises(TypeError):
            ArtifactPayload(intent="not_an_intent", content=b"data")  # type: ignore
        with pytest.raises(TypeError):
            ArtifactPayload(intent=intent, content="not_bytes")  # type: ignore

    def test_result_artifact_payloads_validation(self) -> None:
        intent = ArtifactIntent(name="report.txt", role="report", media_type="text/plain")
        payload = ArtifactPayload(intent=intent, content=b"payload bytes")
        res = Result(data="test", artifact_payloads=(payload,))
        assert len(res.artifact_payloads) == 1
        assert res.artifact_payloads[0] == payload

        with pytest.raises(TypeError):
            Result(data="test", artifact_payloads="not_a_sequence")  # type: ignore
        with pytest.raises(TypeError):
            Result(data="test", artifact_payloads=["not_a_payload"])  # type: ignore

    def test_result_next_requirement_validation(self) -> None:
        res_default = Result(data="test")
        assert res_default.next_requirement is None

        res_ocr = Result(data="test", next_requirement="ocr")
        assert res_ocr.next_requirement == "ocr"

        res_kebab = Result(data="test", next_requirement="native-extraction_v2")
        assert res_kebab.next_requirement == "native-extraction_v2"

        # Invalid type
        with pytest.raises(TypeError, match="next_requirement must be a string or None"):
            Result(data="test", next_requirement=123)  # type: ignore

        # Invalid format / empty
        with pytest.raises(ValueError, match="safe stable identifier"):
            Result(data="test", next_requirement="")

        with pytest.raises(ValueError, match="safe stable identifier"):
            Result(data="test", next_requirement="OCR.CAPITAL")

        with pytest.raises(ValueError, match="safe stable identifier"):
            Result(data="test", next_requirement="has space")


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
            "ArtifactPayload",
            "ArtifactRef",
            "CancellationToken",
            "CanonicalDocument",
            "Capability",
            "CapabilityDeclaration",
            "CapabilityReadiness",
            "CapabilityReadinessProbe",
            "ConfidenceValue",
            "CustomProfileOptions",
            "DeviceRequirement",
            "DeviceType",
            "ExecutionBinding",
            "ExecutionContext",
            "ExecutionProfile",
            "InputRef",
            "PageData",
            "PluginInfo",
            "PluginProvider",
            "PluginServices",
            "ProvenanceRecord",
            "ReadinessStatus",
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


class TestCapabilityProtocol:
    def test_conforming_minimal_capability_satisfies_protocol(self) -> None:
        decl = CapabilityDeclaration(
            capability_id="test_cap",
            plugin_id="test.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )

        class ConformingCapability:
            def __init__(self, declaration: CapabilityDeclaration) -> None:
                self.declaration = declaration

            def execute(
                self,
                request: Request,
                context: ExecutionContext,
                prior_result: Result | None = None,
            ) -> Result:
                return Result(data={"processed": True, "had_prior": prior_result is not None})

        cap = ConformingCapability(decl)
        assert isinstance(cap, Capability)
        assert cap.declaration == decl

        req = Request(
            request_id="req-1",
            requirement="test_cap",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("sample.txt"),
                    display_name="Sample",
                    size_bytes=10,
                ),
            ),
        )
        ctx = ExecutionContext(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
        )

        # First stage: prior_result is None
        res1 = cap.execute(req, ctx, None)
        assert isinstance(res1, Result)
        assert res1.data == {"processed": True, "had_prior": False}

        # Subsequent stage: prior_result is a Result
        res2 = cap.execute(req, ctx, res1)
        assert isinstance(res2, Result)
        assert res2.data == {"processed": True, "had_prior": True}

    def test_malformed_implementations_do_not_satisfy_protocol(self) -> None:
        decl = CapabilityDeclaration(
            capability_id="test_cap",
            plugin_id="test.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )

        class MissingDeclaration:
            def execute(
                self,
                request: Request,
                context: ExecutionContext,
                prior_result: Result | None = None,
            ) -> Result:
                return Result()

        class MissingExecute:
            def __init__(self) -> None:
                self.declaration = decl

        assert not isinstance(MissingDeclaration(), Capability)
        assert not isinstance(MissingExecute(), Capability)
        assert not isinstance("not_a_capability", Capability)
        assert not isinstance(123, Capability)
        assert not isinstance(None, Capability)
