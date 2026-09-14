"""Unit tests for Shakti artifact naming and collision safety."""

from __future__ import annotations

from pathlib import Path

from sarathi.sankalpa import InputRef
from sarathi.shakti.artifact_naming import (
    format_artifact_filename,
    sanitize_filename_component,
)


class TestArtifactNaming:
    def test_sanitize_filename_component(self) -> None:
        assert sanitize_filename_component("Simple_Name") == "Simple_Name"
        assert sanitize_filename_component("File With Spaces & Specials!") == "File_With_Spaces_Specials"
        assert sanitize_filename_component("..leading_dots..") == "leading_dots"
        assert sanitize_filename_component("") == "input"

    def test_single_input_artifact_naming(self) -> None:
        inp = InputRef(
            input_id="inp-1",
            source_path=Path("docs/statement.pdf"),
            display_name="statement.pdf",
            size_bytes=100,
        )

        txt_name = format_artifact_filename(inp, "extracted", "txt")
        docx_name = format_artifact_filename(inp, "extracted", "docx")
        ocr_txt = format_artifact_filename(inp, "ocr", "txt")

        assert txt_name == "statement_extracted.txt"
        assert docx_name == "statement_extracted.docx"
        assert ocr_txt == "statement_ocr.txt"

    def test_duplicate_basename_inputs_disambiguated(self) -> None:
        inp1 = InputRef(
            input_id="inp-folderA",
            source_path=Path("folderA/statement.pdf"),
            display_name="statement.pdf",
            size_bytes=100,
        )
        inp2 = InputRef(
            input_id="inp-folderB",
            source_path=Path("folderB/statement.pdf"),
            display_name="statement.pdf",
            size_bytes=100,
        )

        inputs = [inp1, inp2]

        name1 = format_artifact_filename(inp1, "ocr", "txt", all_inputs=inputs, index=0)
        name2 = format_artifact_filename(inp2, "ocr", "txt", all_inputs=inputs, index=1)

        # Disambiguated, no collision!
        assert name1 != name2
        assert name1 == "statement_1_ocr.txt"
        assert name2 == "statement_2_ocr.txt"

    def test_distinct_basename_inputs_preserve_clean_format(self) -> None:
        inp1 = InputRef(
            input_id="inp-1",
            source_path=Path("docs/docA.pdf"),
            display_name="docA.pdf",
            size_bytes=100,
        )
        inp2 = InputRef(
            input_id="inp-2",
            source_path=Path("docs/docB.pdf"),
            display_name="docB.pdf",
            size_bytes=100,
        )

        inputs = [inp1, inp2]

        name1 = format_artifact_filename(inp1, "extracted", "txt", all_inputs=inputs, index=0)
        name2 = format_artifact_filename(inp2, "extracted", "txt", all_inputs=inputs, index=1)

        assert name1 == "docA_extracted.txt"
        assert name2 == "docB_extracted.txt"
