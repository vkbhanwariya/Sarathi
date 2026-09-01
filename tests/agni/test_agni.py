from unittest.mock import patch
"""Comprehensive unit tests for Agni - Runtime Bootstrap and Composition Root."""

from pathlib import Path
from typing import Any
import pytest

from sarathi.__main__ import main as cli_main
from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha
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

        # c1 was started, so it must be closed during rollback; c3 was never started
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

        # Custom controlled capability implementing the registered read_native declaration
        mock_cap = MockControlledCapability(NATIVE_CAPABILITY)

        # Create Agni instance with injected test capability
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

        # Verify Maruti Telemetry collected across all phases
        maruti_records = agni.darpana.maruti_records()
        phase_names = [r.phase_name for r in maruti_records]

        # Must record bootstrap, identification, resolution, and pipeline execution
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

        # Verify identification recorded shakti.darshana component
        id_rec = next(r for r in maruti_records if r.phase_name == "identification")
        assert id_rec.component == "shakti.darshana"
        assert id_rec.attributes["input_count"] == 1

        # Verify resolution recorded nabhi.manthan component
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

    def test_agni_init_type_validations(self) -> None:
        with pytest.raises(TypeError, match="context must be an ExecutionContext instance or None"):
            Agni(context="invalid_context")  # type: ignore

        with pytest.raises(TypeError, match="darpana must be a Darpana instance or None"):
            Agni(darpana="invalid_darpana")  # type: ignore

        with pytest.raises(TypeError, match="kavacha must be a Kavacha instance or None"):
            Agni(kavacha="invalid_kavacha")  # type: ignore

        with pytest.raises(TypeError, match="inventory must be a DeviceInventory instance or None"):
            Agni(inventory="invalid_inventory")  # type: ignore

        with pytest.raises(TypeError, match="capabilities must be a Mapping or None"):
            Agni(capabilities=["invalid_list"])  # type: ignore

        with pytest.raises(TypeError, match="settings must be Settings, Path, str, or None"):
            Agni(settings=12345)  # type: ignore

    def test_agni_execute_invalid_arguments_raises_type_error(self, tmp_path: Path) -> None:
        agni = Agni(runtime_root=tmp_path / "Runtime", output_root=tmp_path / "Output")

        with pytest.raises(TypeError, match="request must be a Request instance"):
            agni.execute("invalid_request")  # type: ignore

        doc_file = tmp_path / "doc.txt"
        doc_file.write_text("content", encoding="utf-8")
        req = Request(
            request_id="req-1",
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
        with pytest.raises(TypeError, match="context must be an ExecutionContext instance or None"):
            agni.execute(req, context="invalid_context")  # type: ignore

    def test_cli_main_entry_point_dosh_error_returns_code_1_and_safe_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        doc_file = tmp_path / "test.txt"
        doc_file.write_text("CLI test text", encoding="utf-8")

        # Non-existent requirement produces resolution FailureCode.VALIDATION_FAILED
        argv = [
            "--input",
            str(doc_file),
            "--requirement",
            "non_existent_unregistered_requirement",
            "--runtime-root",
            str(tmp_path / "Runtime"),
            "--output-root",
            str(tmp_path / "Output"),
        ]

        exit_code = cli_main(argv)
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "Error: UNSUPPORTED" in captured.err
        assert "CLI test text" not in captured.err

    def test_cli_main_entry_point_generic_exception_returns_code_1_without_raw_trace(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        doc_file = tmp_path / "test.txt"
        doc_file.write_text("CLI test text", encoding="utf-8")

        with patch("sarathi.agni.bootstrap.Agni.execute", side_effect=RuntimeError("Secret internal error")):
            argv = [
                "--input",
                str(doc_file),
                "--runtime-root",
                str(tmp_path / "Runtime"),
                "--output-root",
                str(tmp_path / "Output"),
            ]
            exit_code = cli_main(argv)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error: Internal execution error - RuntimeError" in captured.err
        assert "Secret internal error" not in captured.err
        assert "CLI test text" not in captured.err
