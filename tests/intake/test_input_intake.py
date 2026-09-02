"""Tests for Canonical Input Intake, Discovery, Exclusion, and CLI Parity."""

from pathlib import Path

import pytest

from sarathi.__main__ import main
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha, SecurityPolicy
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.sankalpa import InputRef


def test_intake_arbitrary_files_and_pasted_paths(tmp_path: Path) -> None:
    """Test intake of single files and pasted multi-line quoted paths."""
    file1 = tmp_path / "doc1.pdf"
    file2 = tmp_path / "doc2.pdf"
    file1.write_bytes(b"%PDF-1.4 sample 1")
    file2.write_bytes(b"%PDF-1.4 sample 2")

    pasted_string = f'"{file1}"\n"{file2}"'

    refs, selection, preflight = MukhaPresenter.intake_from_paths([pasted_string])

    assert len(refs) == 2
    assert preflight.eligible_count == 2
    assert preflight.issue_count == 0
    assert {r.display_name for r in refs} == {"doc1.pdf", "doc2.pdf"}
    assert all(isinstance(r, InputRef) for r in refs)
    assert refs[0].size_bytes == file1.stat().st_size
    assert refs[1].size_bytes == file2.stat().st_size


def test_intake_folder_selection_non_recursive_vs_recursive(tmp_path: Path) -> None:
    """Test folder intake with default non-recursive vs explicit recursive scanning."""
    folder = tmp_path / "inbox"
    subfolder = folder / "nested"
    subfolder.mkdir(parents=True)

    root_file = folder / "root.pdf"
    root_file.write_bytes(b"root doc")

    nested_file = subfolder / "nested.pdf"
    nested_file.write_bytes(b"nested doc")

    # 1. Non-recursive (default)
    refs_flat, _, preflight_flat = MukhaPresenter.intake_from_paths([folder], recursive=False)
    assert len(refs_flat) == 1
    assert refs_flat[0].display_name == "root.pdf"
    assert preflight_flat.eligible_count == 1

    # 2. Recursive (explicit)
    refs_rec, _, preflight_rec = MukhaPresenter.intake_from_paths([folder], recursive=True)
    assert len(refs_rec) == 2
    assert {r.display_name for r in refs_rec} == {"root.pdf", "nested.pdf"}
    assert preflight_rec.eligible_count == 2


def test_intake_excludes_active_runtime_and_output_roots(tmp_path: Path) -> None:
    """Test discovery excludes active Runtime and Output root directories to prevent self-ingestion."""
    runtime_root = tmp_path / "Runtime"
    output_root = tmp_path / "Output"
    runtime_root.mkdir()
    output_root.mkdir()

    # Create dummy files inside runtime and output
    (runtime_root / "staging.tmp").write_bytes(b"staging")
    (output_root / "output.pdf").write_bytes(b"output")

    valid_file = tmp_path / "valid.pdf"
    valid_file.write_bytes(b"valid doc")

    refs, _, preflight = MukhaPresenter.intake_from_paths(
        [tmp_path],
        runtime_root=runtime_root,
        output_root=output_root,
        recursive=True,
    )

    # Only valid_file must be selected; runtime and output must be completely excluded
    assert len(refs) == 1
    assert refs[0].display_name == "valid.pdf"


def test_intake_ignores_hidden_and_temporary_files(tmp_path: Path) -> None:
    """Test filtering of hidden dotfiles, Office temporary files, and partial download artifacts."""
    folder = tmp_path / "docs"
    folder.mkdir()

    (folder / "valid_doc.pdf").write_bytes(b"valid")
    (folder / ".DS_Store").write_bytes(b"mac metadata")
    (folder / ".hidden.pdf").write_bytes(b"hidden")
    (folder / "~$document.docx").write_bytes(b"office lock")
    (folder / "download.tmp").write_bytes(b"temp")
    (folder / "stream.crdownload").write_bytes(b"chrome partial")
    (folder / "upload.part").write_bytes(b"firefox partial")

    refs, _, preflight = MukhaPresenter.intake_from_paths([folder], recursive=False)

    assert len(refs) == 1
    assert refs[0].display_name == "valid_doc.pdf"


def test_intake_deduplication_by_canonical_resolved_path(tmp_path: Path) -> None:
    """Test that duplicate paths (e.g. relative vs absolute, or repeated) are deduplicated."""
    file1 = tmp_path / "unique.pdf"
    file1.write_bytes(b"unique")

    # Submit the exact same file twice
    refs, selection, preflight = MukhaPresenter.intake_from_paths([file1, str(file1.resolve())])

    assert len(refs) == 1
    assert preflight.eligible_count == 1
    assert preflight.issue_count == 1
    assert preflight.issues[0][1] == "duplicate input path"


def test_intake_kavacha_destination_overlap_enforcement(tmp_path: Path) -> None:
    """Test Kavacha security policy prevents selecting files inside destination directory."""
    kavacha = Kavacha(
        policy=SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
    )
    output_root = tmp_path / "Output"
    output_root.mkdir()

    file_in_output = output_root / "test.pdf"
    file_in_output.write_bytes(b"test")

    # Ingesting file directly inside output_root must be rejected with DoshError by Kavacha
    with pytest.raises(DoshError) as exc_info:
        MukhaPresenter.intake_from_paths(
            [file_in_output],
            kavacha=kavacha,
            output_root=output_root,
        )

    assert exc_info.value.code is FailureCode.SECURITY_DENIED


def test_cli_intake_folder_and_recursive_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test CLI execution with folder input and --recursive flag."""
    folder = tmp_path / "cli_inbox"
    sub = folder / "sub"
    sub.mkdir(parents=True)

    f1 = folder / "doc1.txt"
    f2 = sub / "doc2.txt"
    f1.write_text("hello world from doc1", encoding="utf-8")
    f2.write_text("hello world from doc2", encoding="utf-8")

    runtime_root = tmp_path / "Runtime"
    output_root = tmp_path / "Output"

    # 1. Without --recursive -> finds only doc1.txt
    exit_code = main(
        [
            "--input",
            str(folder),
            "--runtime-root",
            str(runtime_root),
            "--output-root",
            str(output_root),
            "--requirement",
            "read_native",
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Status: Success" in captured.out

    # 2. With --recursive -> processes doc1 and doc2
    exit_code_rec = main(
        [
            "--input",
            str(folder),
            "--recursive",
            "--runtime-root",
            str(runtime_root),
            "--output-root",
            str(output_root),
            "--requirement",
            "read_native",
        ]
    )
    assert exit_code_rec == 0
    captured_rec = capsys.readouterr()
    assert "Status: Success" in captured_rec.out
