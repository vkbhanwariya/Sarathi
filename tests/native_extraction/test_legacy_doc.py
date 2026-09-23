"""Tests for legacy Word 97-2003 (.doc) detection and conversion."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
)
from sarathi.shakti.darshana.identifier import identify_bytes
from sarathi.shakti.native_extraction.capability import NativeExtractionCapability
from sarathi.shakti.native_extraction.detector import DetectedFormat, detect_content_format
from sarathi.shakti.native_extraction.legacy_doc import (
    convert_doc_to_docx,
    is_word_converter_available,
)

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def test_detect_content_format_legacy_doc_by_signature() -> None:
    """Validate that OLE magic with WordDocument stream bytes is detected as DOC_LEGACY."""
    mock_doc_data = _OLE_MAGIC + b"\x00" * 512 + b"WordDocument" + b"\x00" * 512
    fmt = detect_content_format(mock_doc_data)
    assert fmt is DetectedFormat.DOC_LEGACY


def test_detect_content_format_legacy_doc_by_extension() -> None:
    """Validate that OLE magic with .doc extension hint is detected as DOC_LEGACY."""
    mock_doc_data = _OLE_MAGIC + b"\x00" * 1024
    fmt = detect_content_format(mock_doc_data, file_path=Path("sample.doc"))
    assert fmt is DetectedFormat.DOC_LEGACY


def test_darshana_identify_bytes_legacy_doc() -> None:
    """Validate that Darshana identifies legacy .doc files with correct media type."""
    mock_doc_data = _OLE_MAGIC + b"\x00" * 512 + b"WordDocument" + b"\x00" * 512
    facts = identify_bytes(mock_doc_data, extension_hint="doc")
    assert facts.format_name == "doc_legacy"
    assert facts.media_type == "application/msword"
    assert facts.is_binary is True


def test_is_word_converter_available_type() -> None:
    """Validate that is_word_converter_available returns a boolean."""
    avail = is_word_converter_available()
    assert isinstance(avail, bool)
    if sys.platform == "win32":
        # On this Windows reference test machine, Word is installed
        assert avail is True


def test_convert_doc_fails_closed_when_word_unavailable(tmp_path: Path) -> None:
    """Validate that convert_doc_to_docx raises UNSUPPORTED when Word is not available."""
    dummy_doc = tmp_path / "test.doc"
    dummy_doc.write_bytes(_OLE_MAGIC + b"WordDocument")

    with patch("sarathi.shakti.native_extraction.legacy_doc.is_word_converter_available", return_value=False):
        with pytest.raises(Exception) as exc_info:
            convert_doc_to_docx(dummy_doc, output_dir=tmp_path)
        assert "Microsoft Word is required" in str(exc_info.value)


@pytest.mark.skipif(not is_word_converter_available(), reason="Microsoft Word not installed on host")
def test_e2e_word_doc_conversion_and_native_extraction(tmp_path: Path) -> None:
    """End-to-end verification: create a .doc using Word COM, convert to .docx, and run native extraction."""
    import subprocess

    doc_file = tmp_path / "hello_sarathi.doc"

    # Create a real .doc file using Word COM
    create_script = f"""
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    try {{
        $d = $word.Documents.Add()
        $d.Content.Text = "Sarathi Automated Legacy Word Test."
        # 0 = wdFormatDocument (.doc)
        $d.SaveAs2('{str(doc_file.resolve()).replace("'", "''")}', 0)
        $d.Close($false)
    }} finally {{
        $word.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    }}
    """
    res = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", create_script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert res.returncode == 0, f"Failed to create test .doc file: {res.stderr}"
    assert doc_file.is_file()

    # 1. Test direct convert_doc_to_docx
    converted_docx = convert_doc_to_docx(doc_file, output_dir=tmp_path)
    assert converted_docx.is_file()
    assert converted_docx.suffix.lower() == ".docx"
    assert converted_docx.stat().st_size > 0

    # 2. Test full NativeExtractionCapability pipeline execution on the .doc file
    cap = NativeExtractionCapability()
    req = Request(
        request_id="req-legacy-doc-001",
        requirement="read_native",
        profile=ExecutionProfile.INSTANT,
        inputs=(
            InputRef(
                input_id="inp-001",
                source_path=doc_file,
                display_name="hello_sarathi.doc",
                size_bytes=doc_file.stat().st_size,
            ),
        ),
    )
    ctx = ExecutionContext(
        run_id="run-legacy-doc-001",
        request_id="req-legacy-doc-001",
        trace_id="tr-001",
        span_id="sp-001",
    )

    result = cap.execute(req, ctx)
    assert isinstance(result.data, CanonicalDocument)
    doc = result.data
    assert "Sarathi Automated Legacy Word Test" in doc.text
    assert doc.metadata.get("source_format") == "doc_legacy"
    assert doc.metadata.get("converted_docx_path") is not None
    assert Path(doc.metadata["converted_docx_path"]).is_file()

    # Verify extracted artifacts include docx
    docx_artifacts = [p for p in result.artifact_payloads if p.intent.name.endswith(".docx")]
    assert len(docx_artifacts) >= 1


@pytest.mark.skipif(not is_word_converter_available(), reason="Microsoft Word not installed on host")
def test_e2e_word_doc_font_conversion_full_pipeline(tmp_path: Path) -> None:
    """End-to-end verification: legacy .doc through Agni (read_native -> font_conversion)."""
    import subprocess

    from sarathi.agni import Agni
    from sarathi.darpana import Darpana

    doc_file = tmp_path / "krutidev_test.doc"

    # Create a .doc file with KrutiDev text ('Hkkjr ljdkj' is 'भारत सरकार')
    create_script = f"""
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    try {{
        $d = $word.Documents.Add()
        $p = $d.Paragraphs.Add()
        $p.Range.Text = "Hkkjr ljdkj"
        $p.Range.Font.Name = "Kruti Dev 010"
        $d.SaveAs2('{str(doc_file.resolve()).replace("'", "''")}', 0)
        $d.Close($false)
    }} finally {{
        $word.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    }}
    """
    res = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", create_script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert res.returncode == 0, f"Failed to create test .doc file: {res.stderr}"

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        darpana=Darpana(capacity=50),
    )

    req = Request(
        request_id="req-legacy-fc-001",
        requirement="font_conversion",
        inputs=(
            InputRef(
                input_id="inp-fc-001",
                source_path=doc_file,
                display_name="krutidev_test.doc",
                size_bytes=doc_file.stat().st_size,
            ),
        ),
        profile=ExecutionProfile.ACCURATE,
        custom_options={"source_font": "krutidev010", "font_mode": "auto_unicode"},
    )
    ctx = ExecutionContext(
        run_id="run-legacy-fc-001",
        request_id="req-legacy-fc-001",
        trace_id="tr-fc-001",
        span_id="sp-fc-001",
    )

    result = agni.execute(req, context=ctx)
    assert isinstance(result.data, CanonicalDocument)
    # Text should be converted from 'Hkkjr ljdkj' to Devanagari Unicode 'भारत सरकार'
    assert "भारत सरकार" in result.data.text

    # Verify docx artifact was committed
    docx_artifacts = [a for a in result.artifacts if a.path.name.endswith(".docx")]
    assert len(docx_artifacts) >= 1


@pytest.mark.skipif(not is_word_converter_available(), reason="Microsoft Word not installed on host")
def test_e2e_word_doc_translation_full_pipeline(tmp_path: Path) -> None:
    """End-to-end verification: legacy .doc through Agni (read_native -> translation)."""
    import subprocess

    from sarathi.agni import Agni
    from sarathi.darpana import Darpana
    from sarathi.shakti.translation.capability import TranslationCapability
    from tests.translation.conftest import DeterministicTestBackend

    doc_file = tmp_path / "hindi_sample.doc"

    # Create a .doc file with Hindi text
    create_script = f"""
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    try {{
        $d = $word.Documents.Add()
        $p = $d.Paragraphs.Add()
        $p.Range.Text = "भारतीय रिजर्व बैंक ने नई मौद्रिक नीति की घोषणा की।"
        $d.SaveAs2('{str(doc_file.resolve()).replace("'", "''")}', 0)
        $d.Close($false)
    }} finally {{
        $word.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    }}
    """
    res = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", create_script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert res.returncode == 0, f"Failed to create test .doc file: {res.stderr}"

    darpana = Darpana(capacity=50)
    test_cap = TranslationCapability(darpana=darpana, backend=DeterministicTestBackend())

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        darpana=darpana,
        capabilities={
            "read_native": NativeExtractionCapability(),
            "translation": test_cap,
        },
    )

    req = Request(
        request_id="req-legacy-tr-001",
        requirement="translation",
        inputs=(
            InputRef(
                input_id="inp-tr-001",
                source_path=doc_file,
                display_name="hindi_sample.doc",
                size_bytes=doc_file.stat().st_size,
            ),
        ),
        profile=ExecutionProfile.ACCURATE,
        custom_options={"direction": "hi-en"},
    )
    ctx = ExecutionContext(
        run_id="run-legacy-tr-001",
        request_id="req-legacy-tr-001",
        trace_id="tr-tr-001",
        span_id="sp-tr-001",
    )

    result = agni.execute(req, context=ctx)
    assert isinstance(result.data, CanonicalDocument)
    assert "Reserve Bank of India" in result.data.text

    docx_artifacts = [a for a in result.artifacts if a.path.name.endswith(".docx")]
    assert len(docx_artifacts) >= 1
    for a in docx_artifacts:
        assert a.path.is_file()
        assert a.size_bytes > 0
