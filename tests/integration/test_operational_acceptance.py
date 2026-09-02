"""End-to-end operational acceptance tests for Sarathi V2.

Verifies the complete pipeline flow through the actual Agni runtime bootstrap:
- Selected input ingestion, validation, and security root checks
- Document identification via Darshana
- Capability resolution via Manthan
- Pipeline execution via Pravaha and Yantra
- Real artifact commitment via Agni and RunWorkspace into Output/
- Final run-manifest.json written last
- Telemetry recording via Darpana (Maruti performance & Pramana confidence)
- Real execution failure path reaching Pravaha quarantine and lifecycle
- Verification that no duplicate Kosh/service/telemetry/boundary path is created
- CLI non-interactive execution and safe error reporting
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sarathi.__main__ import main as cli_main
from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha, SecurityPolicy
from sarathi.nabhi import Kosh
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    ArtifactRef,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.shakti.darshana import DarshanaCapability
from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION as NATIVE_DECLARATION


@pytest.fixture
def workspace_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create isolated deterministic input, runtime, and output directory roots."""
    input_dir = tmp_path / "Input"
    runtime_dir = tmp_path / "Runtime"
    output_dir = tmp_path / "Output"
    input_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return input_dir, runtime_dir, output_dir


class MockArtifactProducerCapability:
    """Mock capability that returns a typed ArtifactPayload to test Agni artifact commitment."""

    def __init__(self) -> None:
        self.declaration = NATIVE_DECLARATION

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        intent = ArtifactIntent(
            name="extracted_export.txt",
            role="text_export",
            media_type="text/plain",
        )
        payload_bytes = b"E2E Real Agni Committed Artifact Payload Content."
        return Result(
            data="Native Extraction Success Data",
            artifact_payloads=(
                ArtifactPayload(
                    intent=intent,
                    content=payload_bytes,
                ),
            ),
        )


class MockFailingCapability:
    """Mock capability that raises DoshError during execution to test Pravaha failure lifecycle."""

    def __init__(self) -> None:
        self.declaration = NATIVE_DECLARATION

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        raise DoshError(
            code=FailureCode.EXECUTION_FAILED,
            message="Simulated capability runtime crash during processing",
        )


class TestOperationalAcceptanceE2E:
    """End-to-end operational acceptance test suite."""

    def test_e2e_successful_identification_resolution_execution_and_telemetry(
        self, workspace_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test full happy-path execution through real Agni bootstrap."""
        input_dir, runtime_dir, output_dir = workspace_dirs
        sample_file = input_dir / "sample_doc.txt"
        sample_text = "Sarathi Local Document Intelligence Engine Phase 1 Test Content."
        sample_file.write_text(sample_text, encoding="utf-8")

        req = Request(
            request_id="req-e2e-001",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=sample_file,
                    display_name="sample_doc.txt",
                    size_bytes=sample_file.stat().st_size,
                ),
            ),
            profile=ExecutionProfile.INSTANT,
            output_root=output_dir,
        )

        darpana = Darpana(capacity=1000)
        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)

        # 1. Bootstrap runtime through real Agni context manager
        with Agni(
            runtime_root=runtime_dir,
            output_root=output_dir,
            input_root=input_dir,
            darpana=darpana,
            kavacha=kavacha,
        ) as agni:
            # 2. Execute request through actual Agni pipeline
            ctx = ExecutionContext(
                run_id="run-e2e-001",
                request_id=req.request_id,
                trace_id="tr-e2e-001",
                span_id="sp-e2e-001",
                profile=req.profile,
            )
            result = agni.execute(req, context=ctx)

            # 3. Validate Result structure
            assert isinstance(result, Result)
            assert result.data is not None
            assert sample_text in str(result.data)

            # 4. Validate Provenance records
            assert len(result.provenance) > 0
            prov = result.provenance[0]
            assert prov.source_input_id == "inp-1"
            assert prov.capability_id == "read_native"
            assert prov.stage == "read_native"

            # 5. Validate Telemetry recorded in Darpana for active run
            maruti_recs = tuple(r for r in darpana.maruti_records() if r.run_id == ctx.run_id)
            assert len(maruti_recs) >= 3
            phases = {r.phase_name for r in maruti_recs}
            assert "identification" in phases
            assert "resolution" in phases
            assert "capability_execution" in phases

            for r in maruti_recs:
                assert r.outcome == "success"
                assert r.duration_ns >= 0

    def test_e2e_real_artifact_commitment_through_agni_execute(self, workspace_dirs: tuple[Path, Path, Path]) -> None:
        """Test full artifact lifecycle executed exclusively through Agni.execute()."""
        input_dir, runtime_dir, output_dir = workspace_dirs
        sample_file = input_dir / "input.txt"
        sample_file.write_text("dummy_content", encoding="utf-8")

        req = Request(
            request_id="req-art-e2e",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=sample_file,
                    display_name="input.txt",
                    size_bytes=sample_file.stat().st_size,
                ),
            ),
            output_root=output_dir,
        )

        darpana = Darpana(capacity=1000)
        custom_caps = {
            "identify": DarshanaCapability(),
            "read_native": MockArtifactProducerCapability(),
        }

        # 1. Execute ONLY through Agni.execute
        with Agni(
            runtime_root=runtime_dir,
            output_root=output_dir,
            input_root=input_dir,
            capabilities=custom_caps,
            darpana=darpana,
        ) as agni:
            ctx = ExecutionContext(
                run_id="run-art-e2e",
                request_id=req.request_id,
                trace_id="tr-art-e2e",
                span_id="sp-art-e2e",
            )
            result = agni.execute(req, context=ctx)

            # 2. Receive confirmed ArtifactRef in Result.artifacts, with artifact_payloads empty
            assert isinstance(result, Result)
            assert len(result.artifact_payloads) == 0
            assert len(result.artifacts) == 1
            art_ref = result.artifacts[0]
            assert isinstance(art_ref, ArtifactRef)
            assert art_ref.role == "text_export"

            # 3. Verify committed artifact exists on disk under output_root
            assert art_ref.path.exists()
            assert output_dir.resolve() in art_ref.path.resolve().parents
            payload = b"E2E Real Agni Committed Artifact Payload Content."
            assert art_ref.size_bytes == len(payload)
            expected_sha = hashlib.sha256(payload).hexdigest()
            assert art_ref.checksum_sha256 == expected_sha
            assert art_ref.path.read_bytes() == payload

            # 4. Locate and verify the real run-manifest.json written last
            manifest_path = art_ref.path.parent / "run-manifest.json"
            assert manifest_path.exists()

            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest_data["run_id"] == "run-art-e2e"
            assert manifest_data["status"] == "completed"
            assert manifest_data["requirement"] == "read_native"
            assert len(manifest_data["artifacts"]) == 1
            assert manifest_data["artifacts"][0]["role"] == "text_export"
            assert manifest_data["artifacts"][0]["checksum_sha256"] == expected_sha

            # 5. Staging directory is cleaned up
            staging_dir = runtime_dir / "Work" / "run-art-e2e"
            assert not staging_dir.exists()

            # 6. Source input file remains unmodified
            assert sample_file.read_text(encoding="utf-8") == "dummy_content"

    def test_e2e_real_execution_failure_reaches_pravaha_and_quarantine(
        self, workspace_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test real execution failure flowing through Darshana -> Manthan -> Pravaha -> Quarantine."""
        input_dir, runtime_dir, output_dir = workspace_dirs
        sample_file = input_dir / "failing_input.txt"
        sample_file.write_text("corrupted_content", encoding="utf-8")

        req = Request(
            request_id="req-fail-e2e",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=sample_file,
                    display_name="failing_input.txt",
                    size_bytes=sample_file.stat().st_size,
                ),
            ),
            output_root=output_dir,
        )

        darpana = Darpana(capacity=1000)
        custom_caps = {
            "identify": DarshanaCapability(),
            "read_native": MockFailingCapability(),
        }

        with Agni(
            runtime_root=runtime_dir,
            output_root=output_dir,
            input_root=input_dir,
            capabilities=custom_caps,
            darpana=darpana,
        ) as agni:
            ctx = ExecutionContext(
                run_id="run-fail-e2e",
                request_id=req.request_id,
                trace_id="tr-fail-e2e",
                span_id="sp-fail-e2e",
            )

            # 1. Execution fails in Pravaha and preserves original classified DoshError
            with pytest.raises(DoshError) as exc_info:
                agni.execute(req, context=ctx)

            assert exc_info.value.code is FailureCode.EXECUTION_FAILED
            assert "Simulated capability runtime crash" in exc_info.value.message

            # 2. Pravaha recorded factual quarantine entry in QuarantineStore
            manifest_files = list(agni.quarantine_store.root.glob("*/manifest.json"))
            assert len(manifest_files) == 1
            q_data = json.loads(manifest_files[0].read_text(encoding="utf-8"))
            assert q_data["failure_code"] == FailureCode.EXECUTION_FAILED.value
            assert q_data["status"] == "terminal"
            assert q_data["run_id"] == ctx.run_id

            q_record = agni.quarantine_store.get_record(q_data["quarantine_id"])
            assert q_record is not None
            assert q_record.failure_code is FailureCode.EXECUTION_FAILED

            # 3. Lifecycle telemetry exists for the same run_id (both execution failure and quarantine transition)
            maruti_recs = tuple(r for r in darpana.maruti_records() if r.run_id == ctx.run_id)
            assert any(r.phase_name == "capability_execution" and r.outcome == "failure" for r in maruti_recs)
            assert any(r.phase_name == "quarantine_lifecycle" and r.run_id == ctx.run_id for r in maruti_recs)

    def test_e2e_security_root_overlap_failure_path(self, workspace_dirs: tuple[Path, Path, Path]) -> None:
        """Test security failure path: input inside runtime staging root is rejected."""
        input_dir, runtime_dir, output_dir = workspace_dirs
        staged_file = runtime_dir / "Work" / "staged.txt"
        staged_file.parent.mkdir(parents=True, exist_ok=True)
        staged_file.write_text("internal", encoding="utf-8")

        req = Request(
            request_id="req-e2e-sec",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=staged_file,
                    display_name="staged.txt",
                    size_bytes=staged_file.stat().st_size,
                ),
            ),
        )

        with Agni(
            runtime_root=runtime_dir,
            output_root=output_dir,
            input_root=input_dir,
        ) as agni:
            with pytest.raises(DoshError) as exc_info:
                agni.execute(req)

            assert exc_info.value.code is FailureCode.SECURITY_DENIED

    def test_e2e_cli_non_interactive_success(
        self, workspace_dirs: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test CLI main entrypoint executes successfully and outputs factual status."""
        input_dir, runtime_dir, output_dir = workspace_dirs
        doc = input_dir / "cli_doc.txt"
        doc.write_text("CLI Operational Acceptance Document Content.", encoding="utf-8")

        exit_code = cli_main(
            [
                "--input",
                str(doc),
                "--requirement",
                "read_native",
                "--output-root",
                str(output_dir),
                "--runtime-root",
                str(runtime_dir),
            ]
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Status: Success (Requirement: read_native)" in captured.out

    def test_e2e_cli_non_interactive_error_sanitization(
        self, workspace_dirs: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test CLI error output sanitizes errors and returns non-zero exit code."""
        input_dir, runtime_dir, output_dir = workspace_dirs
        doc = input_dir / "cli_doc.txt"
        doc.write_text("Content", encoding="utf-8")

        exit_code = cli_main(
            [
                "--input",
                str(doc),
                "--requirement",
                "nonexistent_req",
                "--output-root",
                str(output_dir),
                "--runtime-root",
                str(runtime_dir),
            ]
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error: UNSUPPORTED" in captured.err

    def test_e2e_no_duplicate_kosh_or_telemetry_path(self, workspace_dirs: tuple[Path, Path, Path]) -> None:
        """Verify no duplicate Kosh, service, or telemetry path is created during runtime lifecycle."""
        input_dir, runtime_dir, output_dir = workspace_dirs
        darpana = Darpana(capacity=500)

        with Agni(
            runtime_root=runtime_dir,
            output_root=output_dir,
            input_root=input_dir,
            darpana=darpana,
        ) as agni:
            # 1. Single Kosh registry instance
            kosh = agni.kosh
            assert isinstance(kosh, Kosh)
            assert agni.dvara.registry is kosh
            assert agni.manthan.registry is kosh

            # 2. Single Darpana telemetry instance
            assert agni.darpana is darpana
            assert agni.dvara.darpana is darpana
            assert agni.yantra.darpana is darpana
            assert agni.pravaha.darpana is darpana

            # 3. Single Kavacha security instance
            assert agni.pravaha.kavacha is agni.kavacha
            assert agni.kavacha is not None

            # 4. Single ArtifactBoundary instance
            assert agni.artifact_boundary.runtime_root == runtime_dir
            assert agni.artifact_boundary.output_root == output_dir
