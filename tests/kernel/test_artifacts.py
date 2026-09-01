"""Comprehensive unit tests for Nabhi — Canonical Artifact Boundary (ArtifactBoundary & RunWorkspace)."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import ArtifactBoundary
import sarathi.nabhi as nabhi_module
from sarathi.sankalpa import ArtifactIntent, ArtifactRef, InputRef, ProvenanceRecord, WarningRecord


@pytest.fixture
def workspace_roots(tmp_path: Path) -> tuple[Path, Path]:
    runtime_root = tmp_path / "Runtime"
    output_root = tmp_path / "Output"
    return runtime_root, output_root


@pytest.fixture
def boundary(workspace_roots: tuple[Path, Path]) -> ArtifactBoundary:
    runtime_root, output_root = workspace_roots
    return ArtifactBoundary(runtime_root=runtime_root, output_root=output_root)


class TestArtifactBoundaryInitialization:
    def test_explicit_boundary_initialization_and_properties(
        self, workspace_roots: tuple[Path, Path]
    ) -> None:
        runtime_root, output_root = workspace_roots
        boundary = ArtifactBoundary(runtime_root=runtime_root, output_root=output_root)
        assert boundary.runtime_root == runtime_root.resolve()
        assert boundary.output_root == output_root.resolve()
        assert boundary.runtime_root.is_dir()
        assert boundary.output_root.is_dir()

    def test_same_root_rejection(self, tmp_path: Path) -> None:
        same_dir = tmp_path / "SharedRoot"
        with pytest.raises(DoshError) as exc_info:
            ArtifactBoundary(runtime_root=same_dir, output_root=same_dir)
        err = exc_info.value
        assert err.code is FailureCode.INVALID_CONFIGURATION
        assert "cannot be the same directory" in err.message

    def test_nested_roots_rejection(self, tmp_path: Path) -> None:
        parent_root = tmp_path / "Base"
        child_root = parent_root / "NestedOutput"

        # Output inside Runtime
        with pytest.raises(DoshError) as exc_info:
            ArtifactBoundary(runtime_root=parent_root, output_root=child_root)
        assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
        assert "cannot be nested within each other" in exc_info.value.message

        # Runtime inside Output
        with pytest.raises(DoshError) as exc_info:
            ArtifactBoundary(runtime_root=child_root, output_root=parent_root)
        assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
        assert "cannot be nested within each other" in exc_info.value.message

    def test_file_as_root_rejection(self, tmp_path: Path) -> None:
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("content", encoding="utf-8")
        valid_dir = tmp_path / "ValidDir"

        with pytest.raises(DoshError) as exc_info:
            ArtifactBoundary(runtime_root=file_path, output_root=valid_dir)
        assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
        assert "is not a directory" in exc_info.value.message

        with pytest.raises(DoshError) as exc_info:
            ArtifactBoundary(runtime_root=valid_dir, output_root=file_path)
        assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
        assert "is not a directory" in exc_info.value.message

    def test_invalid_types_and_empty_paths_rejection(self, tmp_path: Path) -> None:
        valid_dir = tmp_path / "ValidDir"

        with pytest.raises(TypeError, match="must be a Path or str"):
            ArtifactBoundary(runtime_root=123, output_root=valid_dir)  # type: ignore

        with pytest.raises(TypeError, match="must be a Path or str"):
            ArtifactBoundary(runtime_root=valid_dir, output_root=None)  # type: ignore

        with pytest.raises(TypeError, match="must be a Path or str"):
            ArtifactBoundary(runtime_root=True, output_root=valid_dir)  # type: ignore

        with pytest.raises(DoshError) as exc_info:
            ArtifactBoundary(runtime_root="", output_root=valid_dir)
        assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION

        with pytest.raises(DoshError) as exc_info:
            ArtifactBoundary(runtime_root=valid_dir, output_root="   ")
        assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION


class TestRunWorkspaceLifecycle:
    def test_begin_run_with_safe_identifiers(self, boundary: ArtifactBoundary) -> None:
        ws = boundary.begin_run(run_id="run-101", requirement="ocr")
        assert ws.run_id == "run-101"
        assert ws.requirement == "ocr"
        assert ws.staging_dir.name == "run-101"
        assert ws.staging_dir.parent.name == "Work"
        assert ws.output_dir.parent.name == "ocr"
        assert ws.output_dir.name.startswith("Run-")
        assert ws.staging_dir.is_dir()
        assert ws.output_dir.is_dir()
        assert ws.is_finalized is False

    def test_begin_run_rejects_unsafe_identifiers(self, boundary: ArtifactBoundary) -> None:
        # Invalid requirement names
        for invalid_req in ("OCR", "bank statements", "bank/statement", "../escape", ""):
            with pytest.raises(DoshError) as exc_info:
                boundary.begin_run(run_id="run-1", requirement=invalid_req)
            assert exc_info.value.code is FailureCode.VALIDATION_FAILED

        # Invalid run_id
        for invalid_run_id in ("", "run 1", "run/1", "../run-1", "run@id"):
            with pytest.raises(DoshError) as exc_info:
                boundary.begin_run(run_id=invalid_run_id, requirement="ocr")
            assert exc_info.value.code is FailureCode.VALIDATION_FAILED

    def test_custom_output_root_in_begin_run(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        custom_out = tmp_path / "CustomOutput"
        ws = boundary.begin_run(run_id="run-custom", requirement="bank_statements", output_root=custom_out)
        assert ws.output_dir.is_relative_to(custom_out.resolve())
        assert ws.staging_dir.is_relative_to(boundary.runtime_root)

        # Custom output root nested in runtime root must be rejected
        nested_in_runtime = boundary.runtime_root / "nested"
        with pytest.raises(DoshError) as exc_info:
            boundary.begin_run(run_id="run-bad", requirement="ocr", output_root=nested_in_runtime)
        assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION

    def test_unique_run_directory_creation_on_same_timestamp(
        self, boundary: ArtifactBoundary
    ) -> None:
        fixed_time = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        ws1 = boundary.begin_run(run_id="run-a", requirement="ocr", timestamp=fixed_time)
        ws2 = boundary.begin_run(run_id="run-b", requirement="ocr", timestamp=fixed_time)

        assert ws1.output_dir != ws2.output_dir
        assert ws1.output_dir.name.startswith("Run-20260901-120000-")
        assert ws2.output_dir.name.startswith("Run-20260901-120000-")
        assert ws1.output_dir.exists()
        assert ws2.output_dir.exists()


class TestStagingAndCommit:
    def test_staging_then_commit_lifecycle(self, boundary: ArtifactBoundary) -> None:
        ws = boundary.begin_run(run_id="run-staged", requirement="ocr")
        intent = ArtifactIntent(
            name="extracted.json",
            role="document_text",
            media_type="application/json",
            relative_path=Path("pages/extracted.json"),
            metadata={"pages": 3},
        )
        content = b'{"text": "Sample OCR Output"}'

        # 1. Stage artifact
        staged_path = ws.stage_artifact(intent, content)
        assert staged_path.exists()
        assert staged_path.is_relative_to(ws.staging_dir)
        assert staged_path.read_bytes() == content

        # 2. Atomically commit staged artifact
        ref = ws.commit_staged_artifact(intent, staged_path)
        assert isinstance(ref, ArtifactRef)
        assert ref.role == "document_text"
        assert ref.media_type == "application/json"
        assert ref.path == ws.output_dir / "pages" / "extracted.json"
        assert ref.path.exists()
        assert ref.checksum_sha256 == hashlib.sha256(content).hexdigest()
        assert ref.metadata["pages"] == 3

        # Staging file is cleaned up after commit
        assert not staged_path.exists()

        # 3. Finalize run and verify manifest is written last
        manifest_path = ws.finalize(success=True)
        assert manifest_path == ws.output_dir / "run-manifest.json"
        assert manifest_path.exists()

        # Manifest contains committed artifact facts
        manifest_dict = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest_dict["run_id"] == "run-staged"
        assert manifest_dict["requirement"] == "ocr"
        assert manifest_dict["status"] == "completed"
        assert len(manifest_dict["artifacts"]) == 1
        art_entry = manifest_dict["artifacts"][0]
        assert art_entry["artifact_id"] == ref.artifact_id
        assert art_entry["relative_path"] == "pages/extracted.json"
        assert art_entry["size_bytes"] == len(content)
        assert art_entry["checksum_sha256"] == ref.checksum_sha256

        # Staging directory is completely removed on finalization
        assert not ws.staging_dir.exists()

    def test_direct_atomic_commit(self, boundary: ArtifactBoundary) -> None:
        ws = boundary.begin_run(run_id="run-direct", requirement="bank_statements")
        intent = ArtifactIntent(
            name="transactions.parquet",
            role="transactions",
            media_type="application/vnd.apache.parquet",
            relative_path="data/transactions.parquet",
        )
        content = b"PAR1_MOCK_PARQUET_CONTENT"

        ref = ws.commit_artifact(intent, content)
        assert ref.path == ws.output_dir / "data" / "transactions.parquet"
        assert ref.path.exists()
        assert ref.size_bytes == len(content)
        assert len(ws.committed_artifacts) == 1

        ws.finalize(success=True)
        assert not ws.staging_dir.exists()

    def test_duplicate_artifact_destination_rejection(self, boundary: ArtifactBoundary) -> None:
        ws = boundary.begin_run(run_id="run-dup", requirement="ocr")
        intent1 = ArtifactIntent(name="out.txt", role="text", media_type="text/plain", relative_path="out.txt")
        intent2 = ArtifactIntent(name="out2.txt", role="text", media_type="text/plain", relative_path="out.txt")

        ws.commit_artifact(intent1, b"first content")

        with pytest.raises(DoshError) as exc_info:
            ws.commit_artifact(intent2, b"second content")
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "Duplicate artifact destination" in exc_info.value.message


class TestSecurityAndPathEscapeValidation:
    def test_path_traversal_attempts_rejected(self, boundary: ArtifactBoundary) -> None:
        ws = boundary.begin_run(run_id="run-sec", requirement="ocr")

        for bad_rel in ("../escape.txt", "../../root.txt", "sub/../../escape.txt", "/etc/passwd", "C:\\Windows\\out.txt"):
            with pytest.raises((DoshError, ValueError)):
                intent = ArtifactIntent(name="bad", role="data", media_type="text/plain", relative_path=bad_rel)
                ws.commit_artifact(intent, b"dangerous payload")

    def test_symlink_escape_rejected(self, boundary: ArtifactBoundary, tmp_path: Path) -> None:
        ws = boundary.begin_run(run_id="run-sym", requirement="ocr")
        outside_target = tmp_path / "outside_dir"
        outside_target.mkdir(parents=True, exist_ok=True)

        symlink_in_output = ws.output_dir / "sym_link"
        try:
            symlink_in_output.symlink_to(outside_target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not supported/permitted in this test environment.")

        # Attempt to write inside the symlinked outside dir
        with pytest.raises(DoshError) as exc_info:
            intent = ArtifactIntent(
                name="escape.bin",
                role="data",
                media_type="application/octet-stream",
                relative_path="sym_link/escape.bin",
            )
            ws.commit_artifact(intent, b"payload")
        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "Symlink escape detected" in exc_info.value.message


class TestManifestSafetyAndOrdering:
    def test_manifest_contains_safe_provenance_and_no_raw_secrets_or_payloads(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        ws = boundary.begin_run(run_id="run-manifest-safe", requirement="ocr")
        intent = ArtifactIntent(name="page1.txt", role="text", media_type="text/plain")
        ws.commit_artifact(intent, b"Confidential invoice data 12345")

        prov = ProvenanceRecord(
            source_input_id="inp-001",
            source_file=str(tmp_path / "sensitive_folder" / "input_doc.pdf"),
            stage="ocr",
            plugin_id="shakti.ocr",
            capability_id="ocr.engine",
            page_number=1,
            evidence={"model": "rapidocr_v2", "confidence": 0.98},
            timestamp_utc="2026-09-01T12:00:00Z",
        )
        warn = WarningRecord(
            code="LOW_DPI",
            message="Image resolution is lower than 300 DPI.",
            stage="ocr",
            context={"dpi": 150},
        )

        manifest_path = ws.finalize(
            success=True,
            metadata={"job_type": "automated_audit"},
            provenance=[prov],
            warnings=[warn],
        )

        manifest_raw = manifest_path.read_text(encoding="utf-8")
        manifest_dict = json.loads(manifest_raw)

        # 1. Document content payload is NOT dumped into manifest
        assert "Confidential invoice data 12345" not in manifest_raw

        # 2. Raw sensitive directory paths are sanitized to basename only
        assert str(tmp_path / "sensitive_folder") not in manifest_raw
        assert manifest_dict["provenance"][0]["source_file"] == "input_doc.pdf"

        # 3. Safe facts are recorded accurately
        assert manifest_dict["metadata"]["job_type"] == "automated_audit"
        assert manifest_dict["warnings"][0]["code"] == "LOW_DPI"
        assert manifest_dict["provenance"][0]["evidence"]["confidence"] == 0.98

    def test_cannot_finalize_twice(self, boundary: ArtifactBoundary) -> None:
        ws = boundary.begin_run(run_id="run-double-fin", requirement="ocr")
        ws.finalize(success=True)

        with pytest.raises(DoshError) as exc_info:
            ws.finalize(success=True)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "already finalized" in exc_info.value.message


class TestCleanupAndPartialPreservation:
    def test_default_cleanup_removes_uncommitted_staging(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-fail-clean", requirement="ocr", preserve_partial=False)
        intent = ArtifactIntent(name="temp.txt", role="temp", media_type="text/plain")
        staged = ws.stage_artifact(intent, b"temporary staging bytes")
        assert staged.exists()

        # Run fails and cleanup is invoked
        ws.cleanup()
        assert not ws.staging_dir.exists()
        assert not (ws.output_dir / "partial").exists()

    def test_explicit_partial_preservation_retains_under_partial(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-preserve", requirement="ocr", preserve_partial=True)
        intent = ArtifactIntent(name="partial_data.json", role="partial_result", media_type="application/json")
        staged = ws.stage_artifact(intent, b'{"partial": "data"}')

        # Explicit partial preservation
        preserved_path = ws.preserve_partial_artifact(intent, staged)
        assert preserved_path is not None
        assert preserved_path == ws.output_dir / "partial" / "partial_data.json"
        assert preserved_path.exists()
        assert preserved_path.read_bytes() == b'{"partial": "data"}'

        # Finalize as failed run
        manifest_path = ws.finalize(success=False)
        manifest_dict = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest_dict["status"] == "failed"
        assert len(manifest_dict["partial_artifacts"]) == 1
        assert manifest_dict["partial_artifacts"][0]["relative_path"] == "partial/partial_data.json"

        # Staging is cleaned up
        assert not ws.staging_dir.exists()

    def test_context_manager_cleans_staging_on_exception(
        self, boundary: ArtifactBoundary
    ) -> None:
        try:
            with boundary.begin_run(run_id="run-ctx-fail", requirement="ocr") as ws:
                ws.stage_artifact(
                    ArtifactIntent(name="t.bin", role="temp", media_type="application/octet-stream"),
                    b"temp data",
                )
                assert ws.staging_dir.exists()
                raise RuntimeError("Simulated unhandled processing failure")
        except RuntimeError:
            pass

        assert not ws.staging_dir.exists()


class TestInputSourceImmutability:
    def test_input_files_are_strictly_unmodified_and_unmoved(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        input_file = tmp_path / "original_input.pdf"
        original_content = b"%PDF-1.4 Mock input file bytes"
        input_file.write_bytes(original_content)
        input_stat_before = input_file.stat()

        input_ref = InputRef(
            input_id="inp-001",
            source_path=input_file,
            display_name="original_input.pdf",
            size_bytes=len(original_content),
        )

        ws = boundary.begin_run(run_id="run-input-guard", requirement="ocr")
        intent = ArtifactIntent(name="out.txt", role="text", media_type="text/plain")
        ws.commit_artifact(intent, b"processed text")
        ws.finalize(success=True)

        # Assert input file is completely untouched
        assert input_file.exists()
        assert input_file.read_bytes() == original_content
        input_stat_after = input_file.stat()
        assert input_stat_before.st_size == input_stat_after.st_size
        assert input_stat_before.st_mtime == input_stat_after.st_mtime


class TestPublicExport:
    def test_single_public_artifact_boundary_export(self) -> None:
        expected = {
            "ArtifactBoundary",
            "CapabilityPlan",
            "Kosh",
            "Manthan",
            "Prana",
            "Pravaha",
        }
        assert set(nabhi_module.__all__) == expected
        assert hasattr(nabhi_module, "ArtifactBoundary")
