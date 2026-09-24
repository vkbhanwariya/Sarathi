"""In-place Excel (.xlsx) translation transcoder and table workbook builder for Sarathi.

Provides high-fidelity spreadsheet translation:
- Preserves 100% of formulas (=SUM, =VLOOKUP), number formats, and dates.
- Preserves worksheet layout, styles, borders, cell fills, and column widths.
- Adapts font families to Nirmala UI for Devanagari (Hindi) target text.
- Generates clean, styled Excel workbooks from extracted tabular data.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from sarathi.sankalpa import ArtifactIntent, ArtifactPayload, TableData, WarningRecord

_EXCEL_MIME_TYPE: str = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_XLSM_MIME_TYPE: str = "application/vnd.ms-excel.sheet.macroEnabled.12"
_INVALID_SHEET_TITLE_CHARS: re.Pattern[str] = re.compile(r"[:\\/?*\[\]]")
_NUMBER_PATTERN: re.Pattern[str] = re.compile(r"^[-+]?\d+(?:[.,]\d+)?%?$")

_HINDI_FONT_NAME: str = "Nirmala UI"
_ENGLISH_FONT_NAME: str = "Calibri"


def _sanitize_sheet_title(title: str, default: str = "Sheet1") -> str:
    """Sanitize worksheet title to comply with Excel's 31-char limit and illegal chars."""
    if not title or not title.strip():
        return default
    clean = _INVALID_SHEET_TITLE_CHARS.sub(" ", title).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        return default
    return clean[:31]


def _is_translatable_cell_value(val: Any) -> bool:
    """Return True if cell value is a human-readable text string suitable for translation.

    Explicitly excludes:
    - Formulas (starting with '=').
    - Pure numbers (integer, float) and numeric strings ("12345.67").
    - Booleans, dates, times, and empty strings.
    - Structural placeholder tags (e.g. {{PAGE:1}}).
    """
    if val is None:
        return False
    if not isinstance(val, str):
        return False

    s = val.strip()
    if not s:
        return False

    # Formulas must NEVER be modified
    if s.startswith("="):
        return False

    # Skip pure numeric strings and codes
    if _NUMBER_PATTERN.match(s):
        return False

    # Skip internal structural placeholders
    if s.startswith("{{") and s.endswith("}}"):
        return False

    return True


def transform_xlsx_translation_artifact(
    input_bytes: bytes,
    translate_fn: Callable[[list[str]], list[str]],
    filename: str = "Translated_Document.xlsx",
    role: str = "translated_document",
    warnings: list[WarningRecord] | None = None,
    is_hindi_target: bool = True,
    batch_size: int = 64,
    preserve_sheet_names: bool = True,
    keep_vba: bool | None = None,
) -> ArtifactPayload:
    """Transform an existing XLSX/XLSM file in-place by translating story cells while preserving 100% of formatting.

    Preserves untouched:
    - Formulas: (=SUM, =AVERAGE, =IF, etc.) remain intact.
    - Numeric values: Ints, floats, dates, and currency quantities remain typed and formatted.
    - Cell Styles: Fills, borders, alignments, and number formats are unmodified.
    - Multiple Sheets: All worksheets, charts, and table geometries are preserved.
    - Sheet Names: Preserved by default to prevent breaking cross-sheet formula references.
    - VBA Macros: Preserved for .xlsm files when keep_vba is enabled.
    """
    has_vba = False
    zf_io = io.BytesIO(input_bytes)
    try:
        with zipfile.ZipFile(zf_io, "r") as zf:
            has_vba = any("vbaProject.bin" in name for name in zf.namelist())
    except Exception:
        has_vba = False
    finally:
        try:
            zf_io.close()
        except Exception:
            pass

    eff_keep_vba = keep_vba if keep_vba is not None else has_vba
    is_xlsm = filename.lower().endswith(".xlsm") or has_vba
    if is_xlsm and not filename.lower().endswith(".xlsm"):
        filename = f"{Path(filename).stem}.xlsm"

    wb = None
    vba_preserved = False
    if eff_keep_vba:
        try:
            in_buf = io.BytesIO(input_bytes)
            wb = openpyxl.load_workbook(in_buf, data_only=False, keep_vba=True)
            vba_preserved = True
        except Exception:
            wb = None

    if wb is None:
        in_buf = io.BytesIO(input_bytes)
        wb = openpyxl.load_workbook(in_buf, data_only=False, keep_vba=False)
        if has_vba and warnings is not None:
            warnings.append(
                WarningRecord(
                    code="TRANSLATION_VBA_STRIPPED",
                    message="Macro-enabled (.xlsm) workbook VBA macros could not be preserved and were stripped.",
                    stage="translation",
                    context={"filename": filename},
                )
            )

    try:
        cells_to_translate: list[tuple[Cell, str]] = []
        titles_to_translate: list[tuple[Any, str]] = []

        # 1. Harvest translatable string cells across all worksheets
        for ws in wb.worksheets:
            # Preserve sheet names by default to avoid breaking cross-sheet formulas (e.g. =Data!A1)
            if not preserve_sheet_names and _is_translatable_cell_value(ws.title):
                titles_to_translate.append((ws, ws.title))

            for row in ws.iter_rows():
                for cell in row:
                    val = cell.value
                    if _is_translatable_cell_value(val):
                        cells_to_translate.append((cell, str(val)))

        # 2. Batch-translate all unique strings in a single call
        all_raw_strings = [s for _, s in cells_to_translate] + [s for _, s in titles_to_translate]
        unique_strings = list(dict.fromkeys(all_raw_strings))

        if unique_strings:
            translated_unique: list[str] = []
            for i in range(0, len(unique_strings), max(1, batch_size)):
                chunk = unique_strings[i : i + max(1, batch_size)]
                translated_unique.extend(translate_fn(chunk))

            trans_map = dict(zip(unique_strings, translated_unique, strict=True))

            # 3. Update worksheet titles safely
            for ws, orig_title in titles_to_translate:
                if orig_title in trans_map:
                    new_title = _sanitize_sheet_title(trans_map[orig_title], default=ws.title)
                    try:
                        ws.title = new_title
                    except Exception:
                        pass

            # 4. In-place cell update with typography harmonization
            target_font_name = _HINDI_FONT_NAME if is_hindi_target else _ENGLISH_FONT_NAME

            for cell, orig_val in cells_to_translate:
                if orig_val in trans_map:
                    trans_text = trans_map[orig_val]
                    cell.value = trans_text

                    # Harmonize font family while strictly preserving size, bold, italic, color
                    old_font = cell.font
                    if old_font is not None:
                        cell.font = Font(
                            name=target_font_name,
                            size=old_font.size,
                            bold=old_font.bold,
                            italic=old_font.italic,
                            vertAlign=old_font.vertAlign,
                            underline=old_font.underline,
                            strike=old_font.strike,
                            color=old_font.color,
                        )
                    else:
                        cell.font = Font(name=target_font_name)

        out_buf = io.BytesIO()
        wb.save(out_buf)
        content_bytes = out_buf.getvalue()

    finally:
        wb.close()

    mime_type = _XLSM_MIME_TYPE if (is_xlsm and vba_preserved) else _EXCEL_MIME_TYPE
    return ArtifactPayload(
        intent=ArtifactIntent(
            name=filename,
            role=role,
            media_type=mime_type,
        ),
        content=content_bytes,
    )


def build_xlsx_from_tables(
    tables: Sequence[TableData],
    filename: str = "Translated_Document.xlsx",
    role: str = "translated_document",
    is_hindi_target: bool = True,
) -> ArtifactPayload:
    """Generate a clean, professionally styled Excel workbook from canonical TableData instances."""
    wb = openpyxl.Workbook()
    target_font_name = _HINDI_FONT_NAME if is_hindi_target else _ENGLISH_FONT_NAME

    try:
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(name=target_font_name, color="FFFFFF", bold=True, size=11)
        data_font = Font(name=target_font_name, size=10)
        thin_border_side = Side(style="thin", color="D9D9D9")
        cell_border = Border(
            left=thin_border_side,
            right=thin_border_side,
            top=thin_border_side,
            bottom=thin_border_side,
        )

        for t_idx, table in enumerate(tables):
            ws = wb.active if t_idx == 0 else wb.create_sheet()
            raw_title = table.name or f"Table_{t_idx + 1}"
            ws.title = _sanitize_sheet_title(raw_title, default=f"Table_{t_idx + 1}")

            current_row = 1

            # 1. Header row
            if table.headers:
                for col_idx, h_text in enumerate(table.headers, start=1):
                    cell = ws.cell(row=current_row, column=col_idx)
                    cell.value = str(h_text)
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                    cell.border = cell_border
                current_row += 1

            # 2. Data rows
            for row in table.rows:
                for col_idx, val in enumerate(row, start=1):
                    cell = ws.cell(row=current_row, column=col_idx)
                    # Convert to numeric if pure number
                    s_val = str(val).strip() if val is not None else ""
                    if _NUMBER_PATTERN.match(s_val):
                        try:
                            if "." in s_val:
                                cell.value = float(s_val.replace(",", ""))
                            else:
                                cell.value = int(s_val.replace(",", ""))
                        except ValueError:
                            cell.value = s_val
                    else:
                        cell.value = s_val

                    cell.font = data_font
                    cell.border = cell_border
                    cell.alignment = Alignment(vertical="center", wrap_text=True)
                current_row += 1

            # 3. Column width auto-fit (bounded between 12 and 50)
            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for c in col:
                    if c.value is not None:
                        val_str = str(c.value)
                        max_len = max(max_len, len(val_str))
                ws.column_dimensions[col_letter].width = max(12, min(50, max_len + 3))

        out_buf = io.BytesIO()
        wb.save(out_buf)
        content_bytes = out_buf.getvalue()

    finally:
        wb.close()

    return ArtifactPayload(
        intent=ArtifactIntent(
            name=filename,
            role=role,
            media_type=_EXCEL_MIME_TYPE,
        ),
        content=content_bytes,
    )
