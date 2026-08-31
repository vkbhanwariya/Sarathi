# Sarathi V2 — Shruti — Read & Native Extraction Specification

**Specification Updated:** 31-08-2026, 07:32 PM IST (Asia/Kolkata)

Scope: **Shruti — Read / Native Extraction** content detection, native readers,
quality gate, output provenance, dependencies, and acceptance behavior.

## Purpose

Shruti attempts direct/native extraction before OCR and owns format-specific
reading. File extensions are hints; actual bytes and content determine the
reader.

## Actual-content-first Detection

``` text
Input file / byte stream
        ↓
Read signature + initial bytes
        ↓
Detect actual content type
├── ZIP/XML workbook       → XLSX/XLSM path
├── OLE/BIFF               → legacy XLS path
├── HTML markup            → HTML-table path
├── SpreadsheetML XML      → XML spreadsheet path
├── CSV/text               → text path + encoding detection
├── PDF                    → native PDF path
└── unknown                → controlled fallback / explicit error
```

This protects cases where a file named `.xls` is actually an HTML table or an
extension would otherwise select the wrong reader.

## Reader Strategy

``` text
Spreadsheet primary     → python-calamine
XLSX/XLSM fallback      → openpyxl
legacy BIFF .xls        → xlrd, targeted compatibility fallback
HTML disguised as .xls  → beautifulsoup4
SpreadsheetML XML       → stdlib xml.etree.ElementTree
CSV primary             → Polars where useful
CSV fallback            → stdlib csv
encoding recovery       → charset-normalizer + BOM/common legacy logic
XLSB fallback           → pyxlsb only if the corpus proves Calamine insufficient
PDF                     → PyMuPDF
```

`xlrd` remains because true legacy BIFF `.xls` is a demonstrated workload.
`pyxlsb` is not added without a reproducible corpus gap.

## Quality Gate and Output

``` text
Native content available?
├── no  → return OCR requirement
└── yes → validate extracted content
          ├── usable                  → canonical document/table result
          └── poor/corrupt/incomplete → return OCR requirement
```

Shruti does not implement OCR. For spreadsheets and tabular inputs, it returns
all relevant sheets/tables with source, sheet/table identity, and location
provenance; it never silently selects only the first or largest table.

## Acceptance

- actual bytes override misleading extensions;
- supported native content is extracted without OCR;
- empty, corrupt, or incomplete native output escalates through an explicit OCR
  requirement;
- all relevant sheets/tables retain provenance;
- true legacy `.xls`, disguised HTML `.xls`, SpreadsheetML, CSV encoding, XLSX,
  XLSM, and PDF cases are regression-tested;
- unsupported content returns a controlled result or explicit error.
