"""Comprehensive unit tests for Nabhi — Canonical Artifact Boundary (ArtifactBoundary & RunWorkspace)."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
from typing import Any
from unittest.mock import patch
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import ArtifactBoundary
from sarathi.nabhi.artifacts import RunWorkspace
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

    def test_staged_commit_uses_streaming_not_whole_file_reads(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-stream", requirement="ocr")
        intent = ArtifactIntent(name="big.bin", role="data", media_type="application/octet-stream")
        content = b"X" * 200000

        staged_path = ws.stage_artifact(intent, content)

        # Assert Path.read_bytes() is NOT invoked during commit_staged_artifact
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Whole-file read_bytes was called!")):
            ref = ws.commit_staged_artifact(intent, staged_path)

        assert ref.size_bytes == len(content)
        assert ref.checksum_sha256 == hashlib.sha256(content).hexdigest()
        assert ref.path.exists()

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
        assert "Duplicate artifact destination path." in exc_info.value.message

    def test_duplicate_staging_and_existing_destination_rejected_preserving_bytes(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-dup-stage", requirement="ocr")
        intent1 = ArtifactIntent(name="staged.txt", role="temp", media_type="text/plain", relative_path="sub/staged.txt")
        intent2 = ArtifactIntent(name="staged2.txt", role="temp", media_type="text/plain", relative_path="sub/staged.txt")

        # 1. Stage original file
        path1 = ws.stage_artifact(intent1, b"original staging payload")
        assert path1.exists()
        assert path1.read_bytes() == b"original staging payload"

        # 2. Duplicate staging attempt within session is rejected
        with pytest.raises(DoshError) as exc_info:
            ws.stage_artifact(intent2, b"tampered duplicate payload")
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "Duplicate staged artifact destination path." in exc_info.value.message
        # Original bytes remain intact
        assert path1.read_bytes() == b"original staging payload"

        # 3. Existing file on disk at staging destination is rejected
        existing_file = ws.staging_dir / "already_on_disk.bin"
        existing_file.write_bytes(b"existing staged bytes on disk")
        intent3 = ArtifactIntent(name="already_on_disk.bin", role="temp", media_type="application/octet-stream")
        with pytest.raises(DoshError) as exc_info2:
            ws.stage_artifact(intent3, b"attempt overwrite")
        assert exc_info2.value.code is FailureCode.VALIDATION_FAILED
        assert "Staged artifact destination already exists on disk." in exc_info2.value.message
        assert existing_file.read_bytes() == b"existing staged bytes on disk"

    def test_duplicate_partial_and_existing_destination_rejected_preserving_bytes(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-dup-part", requirement="ocr", preserve_partial=True)
        intent1 = ArtifactIntent(name="p1.json", role="partial", media_type="application/json", relative_path="p1.json")
        intent2 = ArtifactIntent(name="p2.json", role="partial", media_type="application/json", relative_path="p1.json")

        # 1. Preserve partial artifact
        p1 = ws.preserve_partial_artifact(intent1, b'{"partial": 1}')
        assert p1 is not None and p1.exists()
        assert p1.read_bytes() == b'{"partial": 1}'

        # 2. Duplicate partial attempt within session is rejected
        with pytest.raises(DoshError) as exc_info:
            ws.preserve_partial_artifact(intent2, b'{"partial": 2}')
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "Duplicate partial artifact destination path." in exc_info.value.message
        assert p1.read_bytes() == b'{"partial": 1}'

        # 3. Existing file on disk at partial destination is rejected
        existing_partial = ws.output_dir / "partial" / "on_disk.json"
        existing_partial.write_bytes(b'{"on_disk": true}')
        intent3 = ArtifactIntent(name="on_disk.json", role="partial", media_type="application/json")
        with pytest.raises(DoshError) as exc_info2:
            ws.preserve_partial_artifact(intent3, b'{"attempt": "overwrite"}')
        assert exc_info2.value.code is FailureCode.VALIDATION_FAILED
        assert "Partial artifact destination already exists on disk." in exc_info2.value.message
        assert existing_partial.read_bytes() == b'{"on_disk": true}'


class TestSecurityAndPathEscapeValidation:
    def test_path_traversal_attempts_rejected(self, boundary: ArtifactBoundary) -> None:
        for bad_rel in ("../escape.txt", "../../root.txt", "sub/../../escape.txt", "/etc/passwd", "C:\\Windows\\out.txt"):
            with pytest.raises((DoshError, ValueError)):
                ArtifactIntent(name="bad", role="data", media_type="text/plain", relative_path=bad_rel)

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
            stage="ocr",
            plugin_id="shakti.ocr",
            capability_id="ocr.engine",
            page_number=1,
            evidence={"model": "rapidocr_v2", "confidence": 0.98, "secret_key": "raw_secret"},
            timestamp_utc="2026-09-01T12:00:00Z",
        )
        warn = WarningRecord(
            code="LOW_DPI",
            message="Image resolution is lower than 300 DPI.",
            stage="ocr",
            context={"dpi": 150, "token": "secret_token"},
        )

        manifest_path = ws.finalize(
            success=True,
            metadata={"job_type": "automated_audit", "admin_secret": "forbidden"},
            provenance=[prov],
            warnings=[warn],
        )

        manifest_raw = manifest_path.read_text(encoding="utf-8")
        manifest_dict = json.loads(manifest_raw)

        # 1. Document content payload and secrets are NOT dumped into manifest
        assert "Confidential invoice data 12345" not in manifest_raw
        assert "raw_secret" not in manifest_raw
        assert "secret_token" not in manifest_raw
        assert "admin_secret" not in manifest_raw

        # 2. Arbitrary metadata and evidence dictionaries are strictly omitted from Phase 1 manifest
        assert "metadata" not in manifest_dict
        assert "evidence" not in manifest_dict["provenance"][0]
        assert "context" not in manifest_dict["warnings"][0]
        assert "message" not in manifest_dict["warnings"][0]

        # 3. Safe facts are recorded accurately
        assert manifest_dict["warnings"][0]["code"] == "LOW_DPI"
        assert manifest_dict["warnings"][0]["stage"] == "ocr"
        assert manifest_dict["provenance"][0]["stage"] == "ocr"
        assert manifest_dict["provenance"][0]["plugin_id"] == "shakti.ocr"

    def test_cannot_finalize_twice(self, boundary: ArtifactBoundary) -> None:
        ws = boundary.begin_run(run_id="run-double-fin", requirement="ocr")
        ws.finalize(success=True)

        with pytest.raises(DoshError) as exc_info:
            ws.finalize(success=True)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "already finalized" in exc_info.value.message

    def test_malformed_warning_entry_is_rejected_in_finalize(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-warn-bad", requirement="ocr")
        with pytest.raises(TypeError, match="must be a WarningRecord"):
            ws.finalize(success=True, warnings=[{"code": "BAD_TYPE"}])  # type: ignore


class TestCleanupAndPartialPreservation:
    def test_failed_run_cleans_committed_artifacts_and_preserves_partial_only_when_requested(
        self, boundary: ArtifactBoundary
    ) -> None:
        # Case 1: preserve_partial is False -> ordinary committed artifacts removed, staging cleaned, partial not preserved
        ws1 = boundary.begin_run(run_id="run-fail-clean", requirement="ocr", preserve_partial=False)
        intent = ArtifactIntent(name="committed.txt", role="data", media_type="text/plain")
        ref1 = ws1.commit_artifact(intent, b"committed content")
        assert ref1.path.exists()

        manifest_path1 = ws1.finalize(success=False)
        assert manifest_path1.exists()
        # Ordinary committed artifact is removed on failure
        assert not ref1.path.exists()
        manifest_dict1 = json.loads(manifest_path1.read_text(encoding="utf-8"))
        assert manifest_dict1["status"] == "failed"
        assert len(manifest_dict1["artifacts"]) == 0
        assert not (ws1.output_dir / "partial").exists()
        assert not ws1.staging_dir.exists()

        # Case 2: preserve_partial is True -> ordinary committed artifacts removed, but partial/ is preserved
        ws2 = boundary.begin_run(run_id="run-fail-partial", requirement="ocr", preserve_partial=True)
        intent_c = ArtifactIntent(name="doc.txt", role="text", media_type="text/plain")
        ref2 = ws2.commit_artifact(intent_c, b"confirmed doc")
        intent_p = ArtifactIntent(name="partial_doc.json", role="partial", media_type="application/json")
        staged_p = ws2.stage_artifact(intent_p, b'{"partial": true}')
        preserved_path = ws2.preserve_partial_artifact(intent_p, staged_p)
        assert preserved_path is not None and preserved_path.exists()

        manifest_path2 = ws2.finalize(success=False)
        assert manifest_path2.exists()
        manifest_dict2 = json.loads(manifest_path2.read_text(encoding="utf-8"))
        assert manifest_dict2["status"] == "failed"
        assert len(manifest_dict2["artifacts"]) == 0
        assert len(manifest_dict2["partial_artifacts"]) == 1
        assert not ref2.path.exists()
        assert preserved_path.exists()
        assert not ws2.staging_dir.exists()

    def test_manifest_write_failure_cleans_unfinalized_run(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-manifest-err", requirement="ocr")
        ws.stage_artifact(ArtifactIntent(name="tmp.bin", role="temp", media_type="text/plain"), b"staging data")
        intent = ArtifactIntent(name="test.txt", role="text", media_type="text/plain")
        ref = ws.commit_artifact(intent, b"some content")

        with patch.object(RunWorkspace, "_write_bytes_atomically", side_effect=DoshError(FailureCode.EXECUTION_FAILED, "Disk write error")):
            with pytest.raises(DoshError) as exc_info:
                ws.finalize(success=True)

        assert exc_info.value.code is FailureCode.EXECUTION_FAILED
        # Staging directory and committed files are cleaned up on failure
        committed_file = ws.output_dir / "test.txt"
        assert not committed_file.exists()
        assert not ws.staging_dir.exists()

    def test_cleanup_failure_during_manifest_serialization_is_observable_and_safe(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        ws = boundary.begin_run(run_id="run-ser-err", requirement="ocr")
        ws.commit_artifact(ArtifactIntent(name="test.txt", role="text", media_type="text/plain"), b"data")

        secret_path = tmp_path / "secret_serialization_dir"
        with patch("json.dumps", side_effect=TypeError("Non-serializable object")):
            with patch("shutil.rmtree", side_effect=PermissionError(f"Locked {secret_path}")):
                with pytest.raises(DoshError) as exc_info:
                    ws.finalize(success=True)

        err = exc_info.value
        assert err.code is FailureCode.EXECUTION_FAILED
        assert "Failed to clean up" in err.message
        assert str(secret_path) not in err.message
        assert "Locked" not in err.message
        assert err.__cause__ is not None
        assert isinstance(err.__cause__, PermissionError)

    def test_cleanup_failure_during_manifest_write_is_observable_and_safe(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        ws = boundary.begin_run(run_id="run-write-err", requirement="ocr")
        ws.commit_artifact(ArtifactIntent(name="test.txt", role="text", media_type="text/plain"), b"data")

        secret_path = tmp_path / "secret_write_dir"
        with patch.object(RunWorkspace, "_write_bytes_atomically", side_effect=DoshError(FailureCode.EXECUTION_FAILED, "Disk write error")):
            with patch("shutil.rmtree", side_effect=PermissionError(f"Locked {secret_path}")):
                with pytest.raises(DoshError) as exc_info:
                    ws.finalize(success=True)

        err = exc_info.value
        assert err.code is FailureCode.EXECUTION_FAILED
        assert "Failed to clean up" in err.message
        assert str(secret_path) not in err.message
        assert "Locked" not in err.message
        assert err.__cause__ is not None
        assert isinstance(err.__cause__, PermissionError)

    def test_normal_context_exit_without_finalize_cleans_unfinalized_workspace(
        self, boundary: ArtifactBoundary
    ) -> None:
        staging_dir = None
        output_dir = None
        with boundary.begin_run(run_id="run-no-fin-clean", requirement="ocr", preserve_partial=False) as ws:
            staging_dir = ws.staging_dir
            output_dir = ws.output_dir
            ws.stage_artifact(
                ArtifactIntent(name="t.bin", role="temp", media_type="application/octet-stream"),
                b"temp data",
            )
            ref = ws.commit_artifact(
                ArtifactIntent(name="out.txt", role="text", media_type="text/plain"),
                b"committed output",
            )
            assert staging_dir.exists()
            assert (output_dir / "out.txt").exists()

        # Unfinalized exit: staging and ordinary committed artifacts are removed
        assert staging_dir is not None and not staging_dir.exists()
        assert not (output_dir / "out.txt").exists()

    def test_normal_context_exit_without_finalize_with_preserve_partial_retains_partial(
        self, boundary: ArtifactBoundary
    ) -> None:
        staging_dir = None
        output_dir = None
        partial_file = None
        with boundary.begin_run(run_id="run-no-fin-part", requirement="ocr", preserve_partial=True) as ws:
            staging_dir = ws.staging_dir
            output_dir = ws.output_dir
            ws.stage_artifact(
                ArtifactIntent(name="t.bin", role="temp", media_type="application/octet-stream"),
                b"temp data",
            )
            ref = ws.commit_artifact(
                ArtifactIntent(name="out.txt", role="text", media_type="text/plain"),
                b"normal output",
            )
            partial_file = ws.preserve_partial_artifact(
                ArtifactIntent(name="part.json", role="partial", media_type="application/json"),
                b'{"preserved": true}',
            )
            assert staging_dir.exists()
            assert (output_dir / "out.txt").exists()
            assert partial_file is not None and partial_file.exists()

        # Staging is removed, committed artifact removed, partial/ preserved
        assert staging_dir is not None and not staging_dir.exists()
        assert output_dir is not None and output_dir.exists()
        assert not (output_dir / "out.txt").exists()
        assert partial_file is not None and partial_file.exists()
        assert (output_dir / "partial" / "part.json").exists()

    def test_normal_context_exit_cleanup_failure_is_observable_and_safe(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        secret_path = tmp_path / "secret_exit_dir"
        with patch("shutil.rmtree", side_effect=PermissionError(f"Locked {secret_path}")):
            with pytest.raises(DoshError) as exc_info:
                with boundary.begin_run(run_id="run-exit-clean-err", requirement="ocr") as ws:
                    ws.stage_artifact(ArtifactIntent(name="t.bin", role="temp", media_type="application/octet-stream"), b"temp")

        err = exc_info.value
        assert err.code is FailureCode.EXECUTION_FAILED
        assert "Failed to clean up unfinalized run workspace." in err.message
        assert str(secret_path) not in err.message
        assert "Locked" not in err.message
        assert err.__cause__ is not None
        assert isinstance(err.__cause__, PermissionError)

    def test_context_manager_cleans_staging_and_committed_output_on_exception(
        self, boundary: ArtifactBoundary
    ) -> None:
        staging_dir = None
        output_dir = None
        try:
            with boundary.begin_run(run_id="run-ctx-fail-1", requirement="ocr", preserve_partial=False) as ws:
                staging_dir = ws.staging_dir
                output_dir = ws.output_dir
                ws.stage_artifact(
                    ArtifactIntent(name="t.bin", role="temp", media_type="application/octet-stream"),
                    b"temp data",
                )
                ref = ws.commit_artifact(
                    ArtifactIntent(name="out.txt", role="text", media_type="text/plain"),
                    b"some committed output",
                )
                assert staging_dir.exists()
                assert (output_dir / "out.txt").exists()
                raise RuntimeError("Simulated unhandled processing failure")
        except RuntimeError:
            pass

        # Staging and committed output are removed
        assert staging_dir is not None and not staging_dir.exists()
        assert not (output_dir / "out.txt").exists()

    def test_preserve_partial_true_retains_partial_artifacts_only_on_exception(
        self, boundary: ArtifactBoundary
    ) -> None:
        staging_dir = None
        output_dir = None
        partial_file = None
        try:
            with boundary.begin_run(run_id="run-ctx-fail-2", requirement="ocr", preserve_partial=True) as ws:
                staging_dir = ws.staging_dir
                output_dir = ws.output_dir
                intent_normal = ArtifactIntent(name="normal.txt", role="text", media_type="text/plain")
                ref = ws.commit_artifact(intent_normal, b"normal output")

                intent_partial = ArtifactIntent(name="part.json", role="partial", media_type="application/json")
                partial_file = ws.preserve_partial_artifact(intent_partial, b'{"part": 1}')

                assert (output_dir / "normal.txt").exists()
                assert partial_file is not None and partial_file.exists()
                raise RuntimeError("Simulated crash during execution")
        except RuntimeError:
            pass

        assert staging_dir is not None and not staging_dir.exists()
        assert output_dir is not None and output_dir.exists()
        # Normal committed artifact is removed
        assert not (output_dir / "normal.txt").exists()
        # Explicit partial artifact is preserved under partial/
        assert partial_file is not None and partial_file.exists()
        assert (output_dir / "partial" / "part.json").exists()

    def test_cleanup_failure_during_active_exception_preserves_original_exception_and_is_observable(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        secret_leak_str = str(tmp_path / "secret_dir_xyz")
        with patch("shutil.rmtree", side_effect=PermissionError(f"Staging dir locked in {secret_leak_str}")):
            with pytest.raises(RuntimeError) as exc_info:
                with boundary.begin_run(run_id="run-ctx-clean-err", requirement="ocr") as ws:
                    ws.stage_artifact(ArtifactIntent(name="t.bin", role="temp", media_type="application/octet-stream"), b"temp")
                    raise RuntimeError("Primary algorithm failure")

            primary_err = exc_info.value
            assert str(primary_err) == "Primary algorithm failure"
            if hasattr(primary_err, "__notes__"):
                for note in primary_err.__notes__:
                    assert secret_leak_str not in note
                    assert "Staging dir locked" not in note

    def test_cleanup_failure_is_observable_on_direct_call(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-clean-err", requirement="ocr")
        ws.stage_artifact(ArtifactIntent(name="t.bin", role="temp", media_type="application/octet-stream"), b"temp")

        with patch("shutil.rmtree", side_effect=PermissionError("Staging dir locked")):
            with pytest.raises(DoshError) as exc_info:
                ws.cleanup()

        assert exc_info.value.code is FailureCode.EXECUTION_FAILED
        assert "Failed to clean up run staging directory." in exc_info.value.message


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


class TestPrivacyAndErrorSafety:
    def test_filesystem_failure_paths_do_not_leak_raw_paths(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        secret_folder = tmp_path / "secret_folder_abc"
        secret_folder.mkdir()
        ws = boundary.begin_run(run_id="run-priv-err", requirement="ocr")

        with patch.object(Path, "open", side_effect=OSError(f"Access denied to {secret_folder}")):
            with pytest.raises(DoshError) as exc_info:
                ws.commit_artifact(ArtifactIntent(name="x.bin", role="data", media_type="application/octet-stream"), b"data")

        err_msg = exc_info.value.message
        assert str(secret_folder) not in err_msg
        assert "Access denied" not in err_msg


class TestPublicExport:
    def test_single_public_artifact_boundary_export(self) -> None:
        expected = {
            "ArtifactBoundary",
            "CapabilityPlan",
            "Dvara",
            "Kosh",
            "LifecycleAction",
            "LifecycleActionType",
            "Manthan",
            "Prana",
            "Pravaha",
            "QuarantineRecord",
            "QuarantineStatus",
            "QuarantineStore",
            "RetryPolicy",
        }
        assert set(nabhi_module.__all__) == expected
        assert hasattr(nabhi_module, "ArtifactBoundary")


class TestNestedArtifactsAndManifestLastBoundary:
    def test_deeply_nested_safe_artifact_lifecycle(self, boundary: ArtifactBoundary) -> None:
        ws = boundary.begin_run(run_id="run-nested-deep", requirement="bank_statements", preserve_partial=True)
        deep_rel_path = Path("nested_a/nested_b/nested_c/statement_summary.json")
        intent = ArtifactIntent(
            name="statement_summary.json",
            role="summary",
            media_type="application/json",
            relative_path=deep_rel_path,
        )
        content = b'{"deep": "nested_summary_data"}'

        # 1. Staging deeply nested path
        staged_path = ws.stage_artifact(intent, content)
        assert staged_path.exists()
        assert staged_path == ws.staging_dir / "nested_a" / "nested_b" / "nested_c" / "statement_summary.json"

        # 2. Committing deeply nested staged path
        ref = ws.commit_staged_artifact(intent, staged_path)
        assert ref.path == ws.output_dir / "nested_a" / "nested_b" / "nested_c" / "statement_summary.json"
        assert ref.path.exists()
        assert not staged_path.exists()

        # 3. Preserving deeply nested partial artifact
        partial_rel_path = Path("partial_a/partial_b/partial_c/checkpoint.bin")
        partial_intent = ArtifactIntent(
            name="checkpoint.bin",
            role="partial",
            media_type="application/octet-stream",
            relative_path=partial_rel_path,
        )
        preserved_path = ws.preserve_partial_artifact(partial_intent, b"PARTIAL_CHECKPOINT_BYTES")
        assert preserved_path is not None and preserved_path.exists()
        assert preserved_path == ws.output_dir / "partial" / "partial_a" / "partial_b" / "partial_c" / "checkpoint.bin"

        # 4. Finalize and check manifest formatting
        manifest_path = ws.finalize(success=True)
        manifest_dict = json.loads(manifest_path.read_text(encoding="utf-8"))

        art_rel_paths = [a["relative_path"] for a in manifest_dict["artifacts"]]
        assert "nested_a/nested_b/nested_c/statement_summary.json" in art_rel_paths

        part_rel_paths = [p["relative_path"] for p in manifest_dict["partial_artifacts"]]
        assert "partial/partial_a/partial_b/partial_c/checkpoint.bin" in part_rel_paths

    def test_manifest_last_and_workspace_locked_after_finalize(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-manifest-last-lock", requirement="ocr")
        intent = ArtifactIntent(name="text.txt", role="text", media_type="text/plain")

        # Before finalize: manifest does NOT exist
        manifest_path = ws.output_dir / "run-manifest.json"
        assert not manifest_path.exists()

        ws.commit_artifact(intent, b"final text content")
        assert not manifest_path.exists()

        # Finalize writes manifest last
        fin_manifest = ws.finalize(success=True)
        assert fin_manifest == manifest_path
        assert manifest_path.exists()
        assert ws.is_finalized is True

        # Any subsequent mutations are rejected
        post_intent = ArtifactIntent(name="late.txt", role="text", media_type="text/plain")
        with pytest.raises(DoshError) as exc_stage:
            ws.stage_artifact(post_intent, b"late staging")
        assert exc_stage.value.code is FailureCode.VALIDATION_FAILED
        assert "finalized run workspace" in exc_stage.value.message

        with pytest.raises(DoshError) as exc_commit:
            ws.commit_artifact(post_intent, b"late commit")
        assert exc_commit.value.code is FailureCode.VALIDATION_FAILED
        assert "finalized run workspace" in exc_commit.value.message

        with pytest.raises(DoshError) as exc_part:
            ws.preserve_partial_artifact(post_intent, b"late partial")
        assert exc_part.value.code is FailureCode.VALIDATION_FAILED
        assert "finalized run workspace" in exc_part.value.message

    def test_commit_staged_artifact_rejects_external_input_path(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        input_file = tmp_path / "external_input.pdf"
        input_file.write_bytes(b"INPUT_BYTES_DO_NOT_DELETE")

        ws = boundary.begin_run(run_id="run-input-guard-commit", requirement="ocr")
        intent = ArtifactIntent(name="input_as_staged.pdf", role="data", media_type="application/pdf")

        with pytest.raises(DoshError) as exc_info:
            ws.commit_staged_artifact(intent, input_file)

        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "is not within the active staging directory" in exc_info.value.message
        # Input file remains completely untouched and undeleted
        assert input_file.exists()
        assert input_file.read_bytes() == b"INPUT_BYTES_DO_NOT_DELETE"

    def test_commit_staged_artifact_rollback_on_staging_unlink_failure(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-rollback-test", requirement="ocr")
        intent = ArtifactIntent(name="output.txt", role="text", media_type="text/plain")
        staged_path = ws.stage_artifact(intent, b"output data")

        dest_path = ws.output_dir / "output.txt"

        orig_unlink = Path.unlink

        def mock_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
            if self.resolve() == staged_path.resolve():
                raise OSError("Cannot unlink staged file")
            orig_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", new=mock_unlink):
            with pytest.raises(DoshError) as exc_info:
                ws.commit_staged_artifact(intent, staged_path)

        assert exc_info.value.code is FailureCode.EXECUTION_FAILED
        assert "promoted artifact rolled back" in exc_info.value.message
        # Destination file must NOT exist (rolled back atomically)
        assert not dest_path.exists()
        assert len(ws.committed_artifacts) == 0

    def test_commit_staged_artifact_dual_failure_registers_surviving_artifact(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-dual-fail-test", requirement="ocr")
        intent = ArtifactIntent(name="output.txt", role="text", media_type="text/plain")
        staged_path = ws.stage_artifact(intent, b"output data")

        dest_path = ws.output_dir / "output.txt"

        # Mock Path.unlink to fail on both staged_path and dest_path
        def mock_unlink_all(self: Path, *args: Any, **kwargs: Any) -> None:
            raise OSError("Unlink completely failed")

        with patch.object(Path, "unlink", new=mock_unlink_all):
            with pytest.raises(DoshError) as exc_info:
                ws.commit_staged_artifact(intent, staged_path)

        assert exc_info.value.code is FailureCode.EXECUTION_FAILED
        assert "failed to roll back promoted artifact" in exc_info.value.message
        # Destination file survived on disk and is deterministically tracked via public property
        assert dest_path.exists()
        assert len(ws.committed_artifacts) == 1
        assert ws.committed_artifacts[0].path == dest_path

    @pytest.mark.parametrize(
        ("bad_prov", "err_substr"),
        [
            (ProvenanceRecord(stage="stage/slash", plugin_id="p1", capability_id="c1"), "invalid stage identifier"),
            (ProvenanceRecord(stage="s1", plugin_id="plugin..double", capability_id="c1"), "invalid plugin_id identifier"),
            (ProvenanceRecord(stage="s1", plugin_id="p1", capability_id="cap/slash"), "invalid capability_id identifier"),
            (ProvenanceRecord(stage="s1", plugin_id="p1", capability_id="c1", region="region:colon"), "invalid region identifier"),
            (ProvenanceRecord(stage="s1", plugin_id="p1", capability_id="c1", source_input_id="path/to/file"), "invalid source_input_id identifier"),
            (ProvenanceRecord(stage="s1", plugin_id="p1", capability_id="c1", timestamp_utc="not-a-timestamp"), "invalid timestamp_utc format"),
            (ProvenanceRecord(stage="s1", plugin_id="p1", capability_id="c1", page_number=-1), "invalid page_number"),
        ],
    )
    def test_provenance_safe_identifier_validation_in_finalize(
        self, boundary: ArtifactBoundary, bad_prov: ProvenanceRecord, err_substr: str
    ) -> None:
        ws = boundary.begin_run(run_id="run-prov-val", requirement="ocr")
        with pytest.raises(DoshError) as exc_info:
            ws.finalize(success=True, provenance=[bad_prov])
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert err_substr in exc_info.value.message

    def test_finalize_invalid_provenance_leaves_staging_and_partial_state_intact(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-pre-mutation", requirement="ocr", preserve_partial=True)
        staged_file = ws.stage_artifact(
            ArtifactIntent(name="temp.txt", role="temp", media_type="text/plain"),
            b"STAGING_MUST_SURVIVE_ON_VALIDATION_ERROR",
        )
        partial_file = ws.preserve_partial_artifact(
            ArtifactIntent(name="part.json", role="partial", media_type="application/json"),
            b'{"partial": "must_survive"}',
        )

        assert staged_file.exists()
        assert partial_file is not None and partial_file.exists()

        bad_prov = ProvenanceRecord(stage="invalid/stage", plugin_id="p1", capability_id="c1")

        with pytest.raises(DoshError) as exc_info:
            ws.finalize(success=False, provenance=[bad_prov])

        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        # Staging and partial files MUST remain untouched because validation happened before mutation
        assert staged_file.exists()
        assert staged_file.read_bytes() == b"STAGING_MUST_SURVIVE_ON_VALIDATION_ERROR"
        assert partial_file.exists()
        assert partial_file.read_bytes() == b'{"partial": "must_survive"}'

    def test_provenance_and_warnings_with_none_optional_fields_serialize_safely(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-prov-opt", requirement="ocr")
        prov = ProvenanceRecord(
            source_input_id=None,
            source_file=None,
            stage="ocr_stage",
            plugin_id=None,
            capability_id=None,
            page_number=None,
            region=None,
            timestamp_utc=None,
        )
        warn = WarningRecord(
            code="SAFE_WARN_CODE",
            message="safe warning message",
            stage=None,
        )

        manifest_path = ws.finalize(success=True, provenance=[prov], warnings=[warn])
        assert manifest_path.exists()
        manifest_dict = json.loads(manifest_path.read_text(encoding="utf-8"))

        prov_out = manifest_dict["provenance"][0]
        assert prov_out == {"stage": "ocr_stage"}
        assert "plugin_id" not in prov_out
        assert "capability_id" not in prov_out
        assert "page_number" not in prov_out

        warn_out = manifest_dict["warnings"][0]
        assert warn_out == {"code": "SAFE_WARN_CODE"}
        assert "stage" not in warn_out

    def test_input_sources_overlap_with_output_or_staging_rejected(
        self, tmp_path: Path
    ) -> None:
        from sarathi.kavacha import Kavacha, SecurityPolicy
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        runtime_root = tmp_path / "Runtime"
        output_root = tmp_path / "Output"
        boundary = ArtifactBoundary(runtime_root=runtime_root, output_root=output_root, kavacha=kavacha)

        # Input source residing inside output root
        bad_input = boundary.output_root / "nested_input.txt"
        bad_input.parent.mkdir(parents=True, exist_ok=True)
        bad_input.write_text("input")

        with pytest.raises(DoshError) as exc_info:
            boundary.begin_run(
                run_id="run-overlap-fail",
                requirement="ocr",
                input_sources=[bad_input],
            )
        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "Unsafe source and destination overlap" in exc_info.value.message
        assert str(bad_input) not in exc_info.value.message

    def test_artifact_boundary_init_validates_kavacha_before_creating_directories(
        self, tmp_path: Path
    ) -> None:
        runtime_root = tmp_path / "nonexistent_runtime"
        output_root = tmp_path / "nonexistent_output"

        with pytest.raises(TypeError, match="kavacha must be a Kavacha instance"):
            ArtifactBoundary(runtime_root=runtime_root, output_root=output_root, kavacha="not_a_kavacha")  # type: ignore

        assert not runtime_root.exists()
        assert not output_root.exists()

    def test_input_sources_none_or_missing_kavacha_fails_before_custom_output_root_creation(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        with pytest.raises(TypeError, match="input_sources cannot be None"):
            boundary.begin_run(
                run_id="run-none-input",
                requirement="ocr",
                input_sources=None,  # type: ignore
            )

        custom_output = tmp_path / "custom_output_not_created"
        input_file = tmp_path / "input.txt"
        input_file.write_text("data")

        # boundary fixture has no injected kavacha
        with pytest.raises(DoshError) as exc_info:
            boundary.begin_run(
                run_id="run-no-kavacha",
                requirement="ocr",
                output_root=custom_output,
                input_sources=[input_file],
            )
        assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
        assert "Kavacha security service must be injected" in exc_info.value.message
        assert not custom_output.exists()

    def test_begin_run_error_messages_do_not_echo_raw_values(
        self, boundary: ArtifactBoundary
    ) -> None:
        malicious_run_id = "../../../etc/passwd"
        with pytest.raises(DoshError) as exc_run:
            boundary.begin_run(run_id=malicious_run_id, requirement="ocr")
        assert exc_run.value.code is FailureCode.VALIDATION_FAILED
        assert malicious_run_id not in exc_run.value.message
        assert "run_id must be a safe non-empty identifier" in exc_run.value.message

        malicious_req = "ocr/../malicious"
        with pytest.raises(DoshError) as exc_req:
            boundary.begin_run(run_id="valid-run", requirement=malicious_req)
        assert exc_req.value.code is FailureCode.VALIDATION_FAILED
        assert malicious_req not in exc_req.value.message
        assert "requirement must be a safe stable identifier" in exc_req.value.message

    def test_begin_run_invalid_input_sources_element_with_kavacha_does_not_create_custom_output_root(
        self, tmp_path: Path
    ) -> None:
        from sarathi.kavacha import Kavacha, SecurityPolicy

        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        runtime_root = tmp_path / "Runtime"
        output_root = tmp_path / "Output"
        boundary = ArtifactBoundary(runtime_root=runtime_root, output_root=output_root, kavacha=kavacha)

        custom_output = tmp_path / "custom_output_never_created"
        assert not custom_output.exists()

        # Injected Kavacha present, but input_sources contains an invalid element (int)
        with pytest.raises(TypeError, match="must be a Path, str, or InputRef"):
            boundary.begin_run(
                run_id="run-invalid-elem",
                requirement="ocr",
                output_root=custom_output,
                input_sources=[12345],  # type: ignore
            )

        assert not custom_output.exists()

    def test_begin_run_overlap_with_custom_output_root_leaves_root_absent(
        self, tmp_path: Path
    ) -> None:
        from sarathi.kavacha import Kavacha, SecurityPolicy

        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        runtime_root = tmp_path / "Runtime"
        output_root = tmp_path / "Output"
        boundary = ArtifactBoundary(runtime_root=runtime_root, output_root=output_root, kavacha=kavacha)

        custom_output = tmp_path / "candidate_custom_output"
        assert not custom_output.exists()

        # Input source path is nested inside the candidate custom output root
        nested_input = custom_output / "nested" / "input.pdf"

        with pytest.raises(DoshError) as exc_info:
            boundary.begin_run(
                run_id="run-overlap-custom",
                requirement="ocr",
                output_root=custom_output,
                input_sources=[nested_input],
            )

        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "Unsafe source and destination overlap" in exc_info.value.message
        # Candidate custom output root MUST NOT have been created
        assert not custom_output.exists()

    def test_stage_and_commit_artifact_reject_non_bytes_content_before_filesystem_mutation(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-type-validation", requirement="ocr")
        intent = ArtifactIntent(name="test.txt", role="text", media_type="text/plain")

        # Non-bytes content in stage_artifact
        with pytest.raises(TypeError, match="content must be bytes or bytearray"):
            ws.stage_artifact(intent, 12345)  # type: ignore

        # Staging directory must remain empty
        assert not (ws.staging_dir / "test.txt").exists()

        # Non-bytes content in commit_artifact
        with pytest.raises(TypeError, match="content must be bytes or bytearray"):
            ws.commit_artifact(intent, "invalid_string_payload")  # type: ignore

        # Output directory must remain empty
        assert not (ws.output_dir / "test.txt").exists()
        assert len(ws.committed_artifacts) == 0

    def test_finalize_rejects_non_bool_success_before_mutation(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-finalize-type", requirement="ocr")
        staged_file = ws.stage_artifact(
            ArtifactIntent(name="temp.txt", role="temp", media_type="text/plain"),
            b"data",
        )

        with pytest.raises(TypeError, match="success must be a bool"):
            ws.finalize(success=1)  # type: ignore

        with pytest.raises(TypeError, match="success must be a bool"):
            ws.finalize(success="true")  # type: ignore

        # Staging file remains intact because validation happened before mutation
        assert staged_file.exists()
        assert not ws.is_finalized

    def test_write_failure_and_temp_unlink_failure_attaches_causes_safely(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        ws = boundary.begin_run(run_id="run-dual-fail", requirement="ocr")
        intent = ArtifactIntent(name="test.txt", role="text", media_type="text/plain")
        secret_path = tmp_path / "secret_locked_file"

        with patch.object(Path, "replace", side_effect=OSError("Replace disk error")):
            with patch.object(Path, "unlink", side_effect=PermissionError(f"Locked {secret_path}")):
                with pytest.raises(DoshError) as exc_info:
                    ws.commit_artifact(intent, b"payload")

        err = exc_info.value
        assert err.code is FailureCode.EXECUTION_FAILED
        assert "Failed to atomically write artifact file and failed to clean up temporary file." in err.message
        assert str(secret_path) not in err.message
        assert "Locked" not in err.message
        assert err.__cause__ is not None
        assert hasattr(err, "__cleanup_cause__")

    def test_preserve_partial_foreign_path_rejected(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        ws = boundary.begin_run(run_id="run-foreign-part", requirement="ocr", preserve_partial=True)
        foreign_file = tmp_path / "foreign_data.txt"
        foreign_file.write_text("outside data")

        intent = ArtifactIntent(name="part.json", role="partial", media_type="application/json")

        with pytest.raises(DoshError) as exc_info:
            ws.preserve_partial_artifact(intent, foreign_file)

        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "Partial artifact source path must reside strictly within this run's staging directory." in exc_info.value.message
        assert not (ws.output_dir / "partial" / "part.json").exists()

    def test_begin_run_timestamp_validation(self, boundary: ArtifactBoundary) -> None:
        with pytest.raises(TypeError, match="timestamp must be a datetime instance or None"):
            boundary.begin_run(run_id="run-ts-1", requirement="ocr", timestamp="2026-09-01")  # type: ignore

        from datetime import datetime as dt
        naive_dt = dt(2026, 9, 1, 12, 0, 0)
        with pytest.raises(DoshError) as exc_info:
            boundary.begin_run(run_id="run-ts-2", requirement="ocr", timestamp=naive_dt)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "timestamp must be timezone-aware" in exc_info.value.message

    def test_unexpected_non_os_error_in_writer_propagates_unchanged(
        self, boundary: ArtifactBoundary
    ) -> None:
        ws = boundary.begin_run(run_id="run-unexpected-err", requirement="ocr")
        intent = ArtifactIntent(name="test.txt", role="text", media_type="text/plain")

        # Programming defect inside write method (e.g. KeyError or RuntimeError, not OSError)
        with patch.object(Path, "open", side_effect=KeyError("Uncaught dictionary defect")):
            with pytest.raises(KeyError, match="Uncaught dictionary defect"):
                ws.commit_artifact(intent, b"content")

        # Staged write as well
        with patch.object(Path, "open", side_effect=RuntimeError("Programmer assertion failure")):
            with pytest.raises(RuntimeError, match="Programmer assertion failure"):
                ws.stage_artifact(intent, b"content")

    def test_root_and_path_resolution_os_error_becomes_safe_dosh_without_raw_path(
        self, tmp_path: Path
    ) -> None:
        secret_path = tmp_path / "secret_top_secret_root"
        with patch.object(Path, "resolve", side_effect=PermissionError(f"Locked {secret_path}")):
            with pytest.raises(DoshError) as exc_info:
                ArtifactBoundary(runtime_root="Runtime", output_root="Output")

        err = exc_info.value
        assert err.code is FailureCode.INVALID_CONFIGURATION
        assert "Failed to inspect" in err.message
        assert str(secret_path) not in err.message
        assert "Locked" not in err.message
        assert err.__cause__ is not None
        assert isinstance(err.__cause__, PermissionError)

    def test_partial_artifact_stat_failure_during_finalize_raises_safe_dosh_without_raw_path(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        ws = boundary.begin_run(run_id="run-stat-fail", requirement="ocr", preserve_partial=True)
        intent = ArtifactIntent(name="part.json", role="partial", media_type="application/json")
        ws.preserve_partial_artifact(intent, b'{"partial": true}')

        secret_path = tmp_path / "secret_partial_path"
        with patch.object(Path, "stat", side_effect=PermissionError(f"Locked {secret_path}")):
            with pytest.raises(DoshError) as exc_info:
                ws.finalize(success=False)

        err = exc_info.value
        assert err.code is FailureCode.EXECUTION_FAILED
        assert "Failed to inspect partial artifact for manifest generation." in err.message
        assert str(secret_path) not in err.message
        assert "Locked" not in err.message
        assert err.__cause__ is not None
        assert isinstance(err.__cause__, PermissionError)

    def test_artifact_boundary_invalid_darpana_causes_zero_root_creation(
        self, tmp_path: Path
    ) -> None:
        runtime_root = tmp_path / "NonExistentRuntime"
        output_root = tmp_path / "NonExistentOutput"

        with pytest.raises(TypeError, match="darpana must be a Darpana instance or None"):
            ArtifactBoundary(runtime_root=runtime_root, output_root=output_root, darpana="invalid_darpana")  # type: ignore

        assert not runtime_root.exists()
        assert not output_root.exists()

    def test_artifact_boundary_begin_run_invalid_context_causes_zero_mutation(
        self, boundary: ArtifactBoundary, tmp_path: Path
    ) -> None:
        custom_out = tmp_path / "CustomNonExistentOutput"

        with pytest.raises(TypeError, match="context must be an ExecutionContext instance or None"):
            boundary.begin_run(
                run_id="run-invalid-ctx",
                requirement="ocr",
                output_root=custom_out,
                context="invalid_ctx",  # type: ignore
            )

        assert not custom_out.exists()
