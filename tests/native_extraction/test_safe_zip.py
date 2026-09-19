"""Tests for S3: Safe ZIP and XML parsing with strict resource limits."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.mukha.intake import intake_from_paths
from sarathi.shakti.native_extraction.safe_zip import (
    open_zip_safely,
    safe_fromstring,
)


def _create_zip_bytes(files: dict[str, bytes], compress: bool = True) -> bytes:
    buf = io.BytesIO()
    comp_type = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buf, "w", compression=comp_type) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_bug_S3_zip_bomb_uncompressed_limit() -> None:
    """S3: An in-memory zip bomb with large uncompressed content is rejected with DoshError(VALIDATION_FAILED)."""
    # 2 MB of zeros compresses to ~2 KB
    payload = b"\x00" * (2 * 1024 * 1024)
    bomb_data = _create_zip_bytes({"bomb.txt": payload})

    # Setting max_uncompressed to 1 MB should fail
    with pytest.raises(DoshError) as exc_info:
        with open_zip_safely(bomb_data, max_uncompressed=1024 * 1024) as zf:
            zf.read("bomb.txt")
    assert exc_info.value.code is FailureCode.VALIDATION_FAILED


def test_bug_S3_zip_bomb_compression_ratio_limit() -> None:
    """S3: High compression ratio is rejected with DoshError(VALIDATION_FAILED)."""
    payload = b"A" * (500 * 1024)
    bomb_data = _create_zip_bytes({"ratio.txt": payload})

    with pytest.raises(DoshError) as exc_info:
        with open_zip_safely(bomb_data, max_ratio=5.0) as zf:
            zf.read("ratio.txt")
    assert exc_info.value.code is FailureCode.VALIDATION_FAILED


def test_bug_S3_zip_too_many_members() -> None:
    """S3: Archive with more members than max_members is rejected with DoshError(VALIDATION_FAILED)."""
    files = {f"file_{i}.txt": b"content" for i in range(15)}
    zip_data = _create_zip_bytes(files)

    with pytest.raises(DoshError) as exc_info:
        with open_zip_safely(zip_data, max_members=10) as zf:
            zf.read("file_0.txt")
    assert exc_info.value.code is FailureCode.VALIDATION_FAILED


def test_bug_S3_xml_doctype_entity_rejected() -> None:
    """S3: XML containing DOCTYPE or entity expansion is rejected with DoshError(VALIDATION_FAILED)."""
    xml_bomb = (
        '<?xml version="1.0"?>\n'
        "<!DOCTYPE lolz [\n"
        ' <!ENTITY lol "lol">\n'
        " <!ELEMENT lolz (#PCDATA)>\n"
        ' <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
        "]>\n"
        "<lolz>&lol1;</lolz>"
    )
    with pytest.raises(DoshError) as exc_info:
        safe_fromstring(xml_bomb)
    assert exc_info.value.code is FailureCode.VALIDATION_FAILED


def test_bug_S3_normal_xml_and_zip_parses() -> None:
    """S3: Normal benign XML and ZIP archives parse cleanly."""
    valid_xml = "<root><child id='1'>Safe Content</child></root>"
    elem = safe_fromstring(valid_xml)
    assert elem.tag == "root"
    child = elem.find("child")
    assert child is not None
    assert child.text == "Safe Content"

    valid_zip = _create_zip_bytes({"doc.txt": b"Hello World"})
    with open_zip_safely(valid_zip) as zf:
        assert zf.read("doc.txt") == b"Hello World"


def test_bug_S3_intake_oversized_input_rejected(tmp_path: Path) -> None:
    """S3: Input larger than max_input_bytes is rejected at intake."""
    oversized_file = tmp_path / "oversized.bin"
    oversized_file.write_bytes(b"X" * 2048)

    normal_file = tmp_path / "normal.bin"
    normal_file.write_bytes(b"Y" * 100)

    refs, selection, preflight = intake_from_paths(
        [oversized_file, normal_file],
        max_input_bytes=1024,
    )

    # Oversized file must NOT be in valid refs
    ref_paths = [r.source_path.resolve() for r in refs]
    assert normal_file.resolve() in ref_paths
    assert oversized_file.resolve() not in ref_paths

    # Preflight issues must report the oversized file
    assert any("exceeds limit" in reason for _, reason in preflight.issues)

    # Selection view must mark oversized file as ineligible
    oversized_item = next(item for item in selection.items if item.source_path == str(oversized_file))
    assert oversized_item.is_eligible is False
    assert "exceeds limit" in oversized_item.issue_reason
