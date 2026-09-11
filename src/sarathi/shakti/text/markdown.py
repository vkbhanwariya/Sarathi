"""Neutral Markdown text extraction helpers for Shakti capabilities."""

from __future__ import annotations

from sarathi.sankalpa import TableData


def extract_markdown_tables(text: str) -> list[TableData]:
    """Parse pipe-delimited Markdown table blocks into canonical ``TableData`` objects."""
    tables: list[TableData] = []
    lines = [line.strip() for line in text.splitlines()]

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("|") and line.endswith("|") and line.count("|") >= 2:
            table_lines = [line]
            i += 1
            while i < len(lines) and lines[i].startswith("|") and lines[i].endswith("|"):
                table_lines.append(lines[i])
                i += 1

            if len(table_lines) >= 2:
                headers = tuple(col.strip() for col in table_lines[0].strip("|").split("|"))
                data_start = 1
                if len(table_lines) > 1 and all(c in "-:| " for c in table_lines[1]):
                    data_start = 2

                rows: list[tuple[str, ...]] = []
                for row_line in table_lines[data_start:]:
                    rows.append(tuple(col.strip() for col in row_line.strip("|").split("|")))

                if headers and rows:
                    tables.append(
                        TableData(
                            name=f"table_{len(tables) + 1}",
                            headers=headers,
                            rows=tuple(rows),
                        )
                    )
        else:
            i += 1

    return tables


__all__ = ["extract_markdown_tables"]
