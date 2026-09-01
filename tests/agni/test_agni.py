"""Comprehensive unit tests for Agni - Runtime Bootstrap and Composition Root."""

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch
import pytest

from sarathi.__main__ import main as cli_main
from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha, SecurityPolicy
from sarathi.nabhi import ArtifactBoundary, Dvara, Kosh, Manthan, Pravaha, Prana, QuarantineStore, RetryPolicy
from sarathi.sankalpa import (
    Capability,
    CapabilityDeclaration,
    ConfidenceValue,
    DeviceRequirement,
    DeviceType,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PluginInfo,
    ProvenanceRecord,
    Request,
    Result,
    SecurityDeclaration,
)
from sarathi.shakti.native_extraction.plugin import (
    CAPABILITY_DECLARATION as NATIVE_CAPABILITY,
    PLUGIN_INFO as NATIVE_PLUGIN,
)
from sarathi.sutra import Settings
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class MockControlledCapability:
    """Mock capability for testing Agni execution flow."""

    def __init__(self, declaration: CapabilityDeclaration, *, fail_error: BaseException | None = None) -> None:
        self.declaration = declaration
        self.fail_error = fail_error
        self.call_count = 0
        self.last_request: Request | None = None
        self.last_context: ExecutionContext | None = None

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        self.call_count += 1
        self.last_request = request
        self.last_context = context
        if self.fail_error is not None:
            raise self.fail_error
        return Result(
            data="controlled_test_output",
            confidence=ConfidenceValue(score=0.99, method="mock_test", evidence={"mock": True}),
            provenance=(
                ProvenanceRecord(
                    stage=self.declaration.capability_id,
                    evidence={"test": True},
                ),
            ),
        )


class MockLifecycleComponent:
    """Mock component implementing start/close protocol for Prana."""

    def __init__(self, name: str, *, fail_on_start: bool = False, fail_on_close: bool = False) -> None:
        self.name = name
        self.fail_on_start = fail_on_start
        self.fail_on_close = fail_on_close
        self.started = False
        self.closed = False

    def start(self) -> None:
        if self.fail_on_start:
            raise RuntimeError(f"Failed to start component {self.name}")
        self.started = True

    def close(self) -> None:
        if self.fail_on_close:
            raise RuntimeError(f"Failed to close component {self.name}")
        self.closed = True


class TestAgniBootstrap:
    """Acceptance tests for Agni runtime composition and service wiring."""

    def test_single_canonical_instance_and_dependency_order_wiring(self, tmp_path: Path) -> None:
        runtime_dir = tmp_path / "CustomRuntime"
        output_dir = tmp_path / "CustomOutput"
        input_dir = tmp_path / "CustomInput"

        agni = Agni(
            runtime_root=runtime_dir,
            output_root=output_dir,
            input_root=input_dir,
        )

        # 1. Services constructed and injected in dependency order
        assert isinstance(agni.darpana, Darpana)
        assert isinstance(agni.kavacha, Kavacha)
        assert isinstance(agni.artifact_boundary, ArtifactBoundary)
        assert isinstance(agni.kosh, Kosh)
        assert isinstance(agni.dvara, Dvara)
        assert isinstance(agni.yantra, Yantra)
        assert isinstance(agni.manthan, Manthan)
        assert isinstance(agni.prana, Prana)
        assert isinstance(agni.quarantine_store, QuarantineStore)
        assert isinstance(agni.retry_policy, RetryPolicy)
        assert isinstance(agni.pravaha, Pravaha)

        # 2. Builtins registered
        assert agni.kosh.get_capability("identify") is not None
        assert agni.kosh.get_capability("read_native") is not None
        assert agni.kosh.get_capability("ocr") is not None

        # 3. Storage roots resolved
        assert agni.artifact_boundary.runtime_root == runtime_dir.resolve()
        assert agni.artifact_boundary.output_root == output_dir.resolve()

    def test_yantra_default_inventory_is_factual_cpu_capacity(self) -> None:
        inv = DeviceInventory.default_inventory()
        assert len(inv) == 1
        cpu_dev = inv.get_device("cpu-0")
        assert cpu_dev is not None
        assert cpu_dev.device_type == DeviceType.CPU
        count_fn = getattr(os, "process_cpu_count", None)
        expected_cpu = count_fn() if callable(count_fn) else os.cpu_count()
        assert cpu_dev.capacity == max(1, expected_cpu or 1)

        yantra_inv = Yantra.default_inventory()
        assert len(yantra_inv) == 1
        assert yantra_inv.get_device("cpu-0") is not None

    def test_kavacha_denial_before_execution_raises_security_denied(self, tmp_path: Path) -> None:
        runtime_dir = tmp_path / "Runtime"
        output_dir = tmp_path / "Output"
        doc_file = tmp_path / "document.txt"
        doc_file.write_text("Secret content", encoding="utf-8")

        # Create restrictive policy denying PII
        restrictive_policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(restrictive_policy)

        # Create plugin requiring PII
        pii_plugin = PluginInfo(
            plugin_id="shakti.native_extraction",
            name="Native Extraction",
            version="1.0.0",
            security=SecurityDeclaration(pii_access=True),
            capabilities=("read_native",),
        )
        mock_cap = MockControlledCapability(NATIVE_CAPABILITY)

        kosh = Kosh()
        kosh.register_plugin(pii_plugin)
        kosh.register_capability(NATIVE_CAPABILITY)

        manthan = Manthan(kosh)
        yantra = Yantra(DeviceInventory.default_inventory())
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"read_native": mock_cap},
            kavacha=kavacha,
        )

        req = Request(
            request_id="req-sec-01",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=doc_file,
                    display_name="document.txt",
                    size_bytes=doc_file.stat().st_size,
                ),
            ),
        )
        plan = manthan.resolve(req)

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, req, ExecutionContext(run_id="run-1", request_id="req-sec-01", trace_id="tr-1", span_id="sp-1"))

        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert mock_cap.call_count == 0  # Proves capability was never executed

    def test_agni_constructor_preflight_fails_before_storage_mutation(self, tmp_path: Path) -> None:
        runtime_dir = tmp_path / "PreflightRuntime"
        output_dir = tmp_path / "PreflightOutput"

        # Invalid capabilities mapping should raise TypeError before runtime/output directories are created
        with pytest.raises(TypeError, match="capabilities must be a Mapping or None"):
            Agni(
                runtime_root=runtime_dir,
                output_root=output_dir,
                capabilities="invalid_capabilities_string",  # type: ignore
            )

        assert not runtime_dir.exists()
        assert not output_dir.exists()

    def test_same_request_executed_twice_generates_different_run_and_trace_ids(self, tmp_path: Path) -> None:
        runtime_dir = tmp_path / "Runtime"
        output_dir = tmp_path / "Output"
        doc_file = tmp_path / "doc.txt"
        doc_file.write_text("Hello", encoding="utf-8")

        mock_cap = MockControlledCapability(NATIVE_CAPABILITY)
        agni = Agni(
            runtime_root=runtime_dir,
            output_root=output_dir,
            capabilities={"read_native": mock_cap},
        )

        req = Request(
            request_id="req-multi-01",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=doc_file,
                    display_name="doc.txt",
                    size_bytes=doc_file.stat().st_size,
                ),
            ),
        )

        agni.execute(req)
        first_ctx = mock_cap.last_context
        assert first_ctx is not None

        agni.execute(req)
        second_ctx = mock_cap.last_context
        assert second_ctx is not None

        # Same request_id, but unique run_id, trace_id, span_id
        assert first_ctx.request_id == second_ctx.request_id == "req-multi-01"
        assert first_ctx.run_id != second_ctx.run_id
        assert first_ctx.trace_id != second_ctx.trace_id
        assert first_ctx.span_id != second_ctx.span_id

    def test_agni_loads_sutra_settings_file_and_overrides(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "settings.toml"
        cfg_file.write_text(
            "[storage]\n"
            'runtime_root = "ConfiguredRuntime"\n'
            'output_root = "ConfiguredOutput"\n\n'
            "[pipeline]\n"
            "max_retries = 2\n",
            encoding="utf-8",
        )

        agni = Agni(settings=cfg_file, runtime_root=tmp_path / "OverrideRuntime", output_root=tmp_path / "OverrideOutput")
        assert agni.retry_policy.max_retries == 2
        assert agni.artifact_boundary.runtime_root == (tmp_path / "OverrideRuntime").resolve()
        assert agni.artifact_boundary.output_root == (tmp_path / "OverrideOutput").resolve()

    def test_agni_lifecycle_start_and_close_in_dependency_order(self, tmp_path: Path) -> None:
        agni = Agni(runtime_root=tmp_path / "Runtime", output_root=tmp_path / "Output")

        c1 = MockLifecycleComponent("c1")
        c2 = MockLifecycleComponent("c2")
        agni.register_component("comp_1", c1)
        agni.register_component("comp_2", c2)

        with agni:
            assert c1.started is True
            assert c2.started is True
            assert c1.closed is False
            assert c2.closed is False

        assert c1.closed is True
        assert c2.closed is True

    def test_agni_startup_failure_rolls_back_started_components_in_reverse(self, tmp_path: Path) -> None:
        agni = Agni(runtime_root=tmp_path / "Runtime", output_root=tmp_path / "Output")

        c1 = MockLifecycleComponent("c1")
        c2 = MockLifecycleComponent("c2", fail_on_start=True)
        c3 = MockLifecycleComponent("c3")

        agni.register_component("comp_1", c1)
        agni.register_component("comp_2", c2)
        agni.register_component("comp_3", c3)

        with pytest.raises(RuntimeError, match="Failed to start component c2"):
            agni.start()

        assert c1.started is True
        assert c1.closed is True
        assert c2.started is False
        assert c3.started is False
        assert c3.closed is False

    def test_agni_execute_request_end_to_end_with_telemetry(self, tmp_path: Path) -> None:
        runtime_dir = tmp_path / "Runtime"
        output_dir = tmp_path / "Output"
        doc_file = tmp_path / "document.txt"
        doc_file.write_text("Sample plain text content for test", encoding="utf-8")

        mock_cap = MockControlledCapability(NATIVE_CAPABILITY)

        agni = Agni(
            runtime_root=runtime_dir,
            output_root=output_dir,
            capabilities={"read_native": mock_cap},
        )

        req = Request(
            request_id="req-test-agni-01",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=doc_file,
                    display_name="document.txt",
                    size_bytes=doc_file.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
        )

        with agni:
            res = agni.execute(req)

        assert res.data == "controlled_test_output"
        assert res.confidence is not None
        assert res.confidence.score == 0.99
        assert mock_cap.call_count == 1

        maruti_records = agni.darpana.maruti_records()
        phase_names = [r.phase_name for r in maruti_records]

        assert "bootstrap" in phase_names
        assert "identification" in phase_names
        assert "resolution" in phase_names
        assert "pipeline_stage" in phase_names
        assert "allocation" in phase_names
        assert "capability_execution" in phase_names
        assert "release" in phase_names

        for r in maruti_records:
            assert r.duration_ns >= 0
            assert r.outcome == "success"

        id_rec = next(r for r in maruti_records if r.phase_name == "identification")
        assert id_rec.component == "shakti.darshana"
        assert id_rec.attributes["input_count"] == 1

        res_rec = next(r for r in maruti_records if r.phase_name == "resolution")
        assert res_rec.component == "nabhi.manthan"
        assert res_rec.attributes["requirement"] == "read_native"

    def test_cli_main_entry_point_success(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        doc_file = tmp_path / "test.txt"
        doc_file.write_text("CLI test text", encoding="utf-8")
        runtime_dir = tmp_path / "Runtime"
        output_dir = tmp_path / "Output"

        argv = [
            "--input",
            str(doc_file),
            "--requirement",
            "read_native",
            "--runtime-root",
            str(runtime_dir),
            "--output-root",
            str(output_dir),
        ]

        exit_code = cli_main(argv)
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "Status: Success (Requirement: read_native)" in captured.out

    def test_cli_main_entry_point_no_inputs_returns_code_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = cli_main([])
        assert exit_code == 2

    def test_cli_main_entry_point_invalid_profile_returns_code_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        doc_file = tmp_path / "test.txt"
        doc_file.write_text("CLI test text", encoding="utf-8")

        argv = [
            "--input",
            str(doc_file),
            "--profile",
            "invalid_profile_name",
        ]
        exit_code = cli_main(argv)
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Validation error: Invalid profile" in captured.err

    def test_cli_main_entry_point_missing_input_file_returns_code_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing_file = tmp_path / "non_existent.txt"
        argv = ["--input", str(missing_file)]
        exit_code = cli_main(argv)
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Validation error: Input path does not exist" in captured.err

    def test_cli_main_entry_point_directory_input_rejected_with_code_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        dir_path = tmp_path / "some_dir"
        dir_path.mkdir()
        argv = ["--input", str(dir_path)]
        exit_code = cli_main(argv)
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Validation error: Input path is not a regular file" in captured.err

    def test_cli_main_entry_point_duplicate_input_rejected_with_code_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        doc_file = tmp_path / "test.txt"
        doc_file.write_text("content", encoding="utf-8")
        argv = ["--input", str(doc_file), "--input", str(doc_file)]
        exit_code = cli_main(argv)
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Validation error: Duplicate input file selected" in captured.err
