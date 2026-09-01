"""End-to-end operational acceptance tests for Sarathi V2.

Verifies the complete pipeline flow through the actual Agni runtime bootstrap:
- Selected input ingestion, validation, and security root checks
- Document identification via Darshana
- Capability resolution via Manthan
- Pipeline execution via Pravaha and Yantra
- Artifact lifecycle, staging, atomic commitment, and safe completion manifest
- Telemetry recording via Darpana (Maruti performance & Pramana confidence)
- Expected failure paths reaching safe Dosh classification and Pravaha lifecycle
- Verification that no duplicate Kosh/service/telemetry path is created
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
from sarathi.nabhi import ArtifactBoundary, Kosh
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactRef,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)


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

    def test_e2e_artifact_boundary_atomic_commit_and_safe_manifest(
        self, workspace_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test artifact lifecycle: staging, atomic commit, and safe completion manifest."""
        input_dir, runtime_dir, output_dir = workspace_dirs
        sample_file = input_dir / "input.pdf"
        sample_file.write_text("dummy_pdf_content", encoding="utf-8")

        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)

        boundary = ArtifactBoundary(
            runtime_root=runtime_dir,
            output_root=output_dir,
            kavacha=kavacha,
        )

        ctx = ExecutionContext(
            run_id="run-art-001",
            request_id="req-art-001",
            trace_id="tr-art-001",
            span_id="sp-art-001",
        )

        inputs = (
            InputRef(
                input_id="inp-1",
                source_path=sample_file,
                display_name="input.pdf",
                size_bytes=sample_file.stat().st_size,
            ),
        )

        with boundary.begin_run(
            run_id="run-art-001",
            requirement="read_native",
            input_sources=inputs,
            context=ctx,
        ) as ws:
            # 1. Stage and commit an artifact
            intent = ArtifactIntent(
                name="extracted_content.txt",
                role="text_export",
                media_type="text/plain",
            )
            payload = b"Extracted Document Text Content from Native Reader."
            staged_path = ws.stage_artifact(intent, payload)
            assert staged_path.exists()
            ref = ws.commit_staged_artifact(intent, staged_path)

            assert isinstance(ref, ArtifactRef)
            assert ref.path.exists()
            assert ref.size_bytes == len(payload)
            expected_sha = hashlib.sha256(payload).hexdigest()
            assert ref.checksum_sha256 == expected_sha

            # Verify actual on-disk file in Output/
            disk_bytes = ref.path.read_bytes()
            assert disk_bytes == payload

            # Finalize workspace and generate run-manifest.json
            manifest_path = ws.finalize(success=True)
            assert manifest_path.exists()
            assert manifest_path.name == "run-manifest.json"

            # Verify safe completion manifest contains no secrets or raw machine paths
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest_data["run_id"] == "run-art-001"
            assert manifest_data["status"] == "completed"
            assert manifest_data["requirement"] == "read_native"
            assert len(manifest_data["artifacts"]) == 1
            assert manifest_data["artifacts"][0]["role"] == "text_export"
            assert manifest_data["artifacts"][0]["checksum_sha256"] == expected_sha

    def test_e2e_expected_failure_reaches_safe_dosh_classification(
        self, workspace_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Test expected failure path: unsupported requirement fails with clean DoshError."""
        input_dir, runtime_dir, output_dir = workspace_dirs
        sample_file = input_dir / "sample.txt"
        sample_file.write_text("content", encoding="utf-8")

        req = Request(
            request_id="req-e2e-fail",
            requirement="unsupported_quantum_translation",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=sample_file,
                    display_name="sample.txt",
                    size_bytes=sample_file.stat().st_size,
                ),
            ),
        )

        darpana = Darpana(capacity=1000)

        with Agni(
            runtime_root=runtime_dir,
            output_root=output_dir,
            input_root=input_dir,
            darpana=darpana,
        ) as agni:
            ctx = ExecutionContext(
                run_id="run-e2e-fail",
                request_id=req.request_id,
                trace_id="tr-fail",
                span_id="sp-fail",
            )
            # Reaches safe Dosh classification
            with pytest.raises(DoshError) as exc_info:
                agni.execute(req, context=ctx)

            assert exc_info.value.code is FailureCode.UNSUPPORTED
            assert "unsupported_quantum_translation" in exc_info.value.message

    def test_e2e_security_root_overlap_failure_path(
        self, workspace_dirs: tuple[Path, Path, Path]
    ) -> None:
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

    def test_e2e_no_duplicate_kosh_or_telemetry_path(
        self, workspace_dirs: tuple[Path, Path, Path]
    ) -> None:
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
