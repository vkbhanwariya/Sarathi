# Bank Statement Schema Mapping & Onboarding Guide

`Vedas/Bank_Statement_Mapping_Guide.md` is the canonical reference for ingesting, profiling, and mapping new bank statement formats into Sarathi. It enables any developer or AI assistant to onboard new bank formats immediately without re-explaining the architecture.

---

## 1. Subsystem Architecture & Ingestion Flow

Bank statement extraction and normalization is owned by `sarathi.shakti.bank_statements`. It executes in a deterministic, zero-network, Decimal-precision pipeline:

```mermaid
flowchart TD
    A["Input File (.pdf, .xlsx, .xls, .csv)"] --> B["Format Sniffing (File Ext vs Actual Magic Bytes)"]
    B --> C["Native Extraction (read_native) / Fallback OCR"]
    C --> D["Table Locator (classify_table & find_header_row_index)"]
    D --> E["Header Schema Matcher (HeaderMapper.resolve_best_profile)"]
    E --> F["Bank Profile Selected (src/sarathi/data/banks/<bank_id>.yaml)"]
    F --> G["Row Classifier & Decimal Parser (parse_decimal_amount, parse_date)"]
    G --> H["Deduplicator (multi-month overlap detection)"]
    H --> I["Financial Balance Validator (Opening + Credits - Debits == Closing)"]
    I --> J["Output Deliverables (Consolidated_Bank_Statement.parquet & .xlsx)"]
```

---

## 2. File Format vs Actual Hidden Format Sniffing

Indian banks export statements under misleading file extensions. The ingestion pipeline sniffs content by magic bytes and binary signatures (`sarathi.shakti.native_extraction.detector`):

| Declared Extension | Actual Hidden Binary Format | Sniffing Signature | Engine Handling |
| :--- | :--- | :--- | :--- |
| `.xls` | **HTML Web Table** | `b"<html"` or `<table` | `HTML_TABLE` reader extracts `<td>` cells directly into structured tables. |
| `.xls` | **SpreadsheetML 2003 XML** | `xmlns="urn:schemas-microsoft-com:office:spreadsheet"` | `SPREADSHEET_ML` XML parser. |
| `.xls` | **Legacy OLE / BIFF8** | `b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"` | Calamine / legacy BIFF parser. |
| `.xlsx` | **OpenXML Package** | `b"PK\x03\x04"` with `xl/workbook.xml` | Calamine / openpyxl reader. |
| `.csv` | **UTF-16LE / TSV / Pipe** | BOM `b"\xff\xfe"` or `\t` / `\|` delimiters | `DelimitedReader` with automatic delimiter & encoding sniff. |
| `.pdf` | **Vector Text PDF** | `b"%PDF-"` with stream font glyphs | PyMuPDF text & vector table reconstruction. |
| `.pdf` | **Scanned Image PDF** | `b"%PDF-"` with image-only pages | Automatic continuation handoff to `ocr`. |

> [!IMPORTANT]
> Never assume the file extension reflects the real format. Always inspect the underlying container before diagnosing extraction failures.

---

## 3. Dynamic Header Schema Matcher (`resolve_best_profile`)

Sarathi does not rely solely on bank logo text. It uses **Dynamic Header Schema Matching**:
1. When a transaction table is located, its header cells (`hdr_cells`) are extracted.
2. `HeaderMapper.resolve_best_profile(hdr_cells, candidate_profile)` evaluates the extracted columns against **all registered profiles** in `src/sarathi/data/banks/*.yaml` (resolved via `sutra.get_canonical_data_root() / "banks"`).
3. Scoring algorithm:
   - **Anchor Fields**: `date` (+3.0), `description` (+2.0), `balance` (+2.5), `debit` (+2.0), `credit` (+2.0), `amount` (+2.0), `reference_number`/`cheque_number` (+1.0).
   - **Precision Bonuses**: `bank_exact` match (+2.0), `bank_fuzzy` match (+1.0), `generic_exact` (+0.5).
   - **Candidate Prior**: +1.0 tie-breaker bonus if text detection also identified the bank.
4. The bank profile with the highest composite score is selected to parse the statement.

---

## 4. Standard Bank Profile Specification (`src/sarathi/data/banks/<bank_id>.yaml`)

Every bank format has a YAML profile under `src/sarathi/data/banks/<bank_id>.yaml`. Profiles are packaged with the distribution wheel and loaded dynamically on startup:

```yaml
# src/sarathi/data/banks/<bank_id>.yaml

profile_id: "bank_code"               # Required: Lowercase identifier (e.g. "sbi", "hdfc", "canara", "union")
bank_name: "Full Institutional Name"  # Required: Display name (e.g. "Union Bank of India")

aliases:                              # Variations of bank name found in text
  - "union bank"
  - "union bank of india"
  - "ubi"

identification_keywords:              # Unique text tokens confirming this bank
  - "union bank of india"
  - "unionbankofindia.co.in"
  - "unionbankonline"

headers:                              # CRITICAL: Maps source column headers to canonical fields
  date:
    - "txn date"
    - "transaction date"
    - "date"
    - "tran date"
    - "value date"
  description:
    - "particulars"
    - "narration"
    - "transaction details"
    - "description"
    - "remarks"
  reference_number:
    - "ref no"
    - "ref no."
    - "ref/chq no"
    - "utr"
    - "transaction id"
  cheque_number:
    - "chq no"
    - "cheque no"
    - "chq. no."
  debit:
    - "withdrawal"
    - "withdrawal amount"
    - "debit"
    - "dr"
    - "debit (inr)"
  credit:
    - "deposit"
    - "deposit amount"
    - "credit"
    - "cr"
    - "credit (inr)"
  balance:
    - "balance"
    - "running balance"
    - "closing balance"
    - "balance (inr)"

date_formats:                         # Supported date formats in order of likelihood
  - "%d/%m/%Y"                        # e.g. 23/09/2026
  - "%d-%m-%Y"                        # e.g. 23-09-2026
  - "%d %b %Y"                        # e.g. 23 Sep 2026
  - "%d-%b-%Y"                        # e.g. 23-Sep-2026
  - "%d/%m/%y"                        # e.g. 23/09/26

metadata_patterns:                    # Regex to extract account metadata from statement header
  account_number: '(?:Account\s*(?:No\.?|Number)?|A\/c\s*No\.?)\s*[:\-]?\s*([0-9Xx\*]{9,18})'
  account_holder: '(?:Customer|Account\s*Holder|Name)\s*[:\-]?\s*([^\n\r]+)'
  ifsc: 'IFSC(?:\s*Code)?\s*[:\-]?\s*([A-Z]{4}0[A-Z0-9]{6})'
  cif: 'CIF(?:\s*No\.?)?\s*[:\-]?\s*([0-9]{9,12})'

# Optional flags:
# signed_amounts: false               # Set true only if single amount column with +/- signs or Cr/Dr suffix
```

---

## 5. Universal Fallback (`src/sarathi/data/banks/common.yaml`)

If a header variant is common across multiple banks (e.g. `"withdrawals"`, `"deposits"`, `"chq/ref no"`), add it to `src/sarathi/data/banks/common.yaml` under `aliases:`. This ensures generic or uncatalogued banks also resolve cleanly without failing.

---

## 6. Step-by-Step New Bank Onboarding Protocol

When onboarding a new bank statement from `Input/`:

### Step 1: Inspect Raw File & Hidden Format
Run this one-liner in shell to inspect declared vs actual format and view raw table headers:
```powershell
uv run python -c "
from pathlib import Path
from sarathi.shakti.native_extraction.detector import detect_content_format
from sarathi.shakti.native_extraction.capability import NativeExtractionCapability
from sarathi.sankalpa import Request, InputRef, ExecutionProfile, ExecutionContext

file_path = Path('Input/<statement_file>')
raw_bytes = file_path.read_bytes()
print('Format detected:', detect_content_format(raw_bytes, file_path))

cap = NativeExtractionCapability()
req = Request('test', 'read_native', (InputRef('1', file_path, file_path.name, len(raw_bytes)),), ExecutionProfile.INSTANT)
res = cap.execute(req, ExecutionContext('r1', 'req1', 't1', 's1'))
for p_idx, p in enumerate(res.data.pages):
    for t in p.tables:
        print(f'Page {p_idx+1} Headers:', t.headers or (t.rows[0] if t.rows else None))
"
```

### Step 2: Create or Update `src/sarathi/data/banks/<bank_id>.yaml`
1. Copy the exact column headers observed in Step 1 into the `headers:` section.
2. Note the date format in sample rows and add it to `date_formats:`.
3. Check if account number and IFSC regex match the statement header text.

### Step 3: Run Bank Statements Test Suite
Verify that the YAML passes validation and no regressions are introduced:
```powershell
uv run --group dev pytest tests/bank_statements/ -q
```

### Step 4: Run Consolidation & Verify Double-Entry Balances
Run the bank consolidation pipeline and verify:
$$\text{Opening Balance} + \sum \text{Credits} - \sum \text{Debits} == \text{Closing Balance} \pm 0.01$$
Check that deliverable artifacts are produced:
- `Output/<run_id>/Consolidated_Bank_Statement.xlsx`
- `Output/<run_id>/Consolidated_Bank_Statement.parquet`

---

## 7. Common Edge Cases & Fixes

| Issue | Root Cause | Canonical Fix |
| :--- | :--- | :--- |
| `ZERO_TRANSACTIONS_EXTRACTED` | Column names not in YAML `headers:`. | Add the exact column string to `date`, `debit`/`credit`, or `balance` in `<bank>.yaml`. |
| `ZERO_TRANSACTIONS_EXTRACTED` | Header row not recognized by `find_header_row_index`. | Add missing token to `_DATE_TOKENS` or `_AMOUNT_TOKENS` in `table_locator.py`. |
| Multi-line Headers | Bank header spans 2 rows (e.g. `Txn` on Row 0, `Date` on Row 1). | Ensure both rows are concatenated or normalized in `table_locator.py`. |
| Date parsing error | Non-standard format (e.g. `23/09/26` 2-digit year). | Add `"%d/%m/%y"` to `date_formats:`. |
| Devanagari defect warning | Legacy font converter triggered on ASCII symbols in PDF. | Ensure `convert_legacy_fonts` is disabled for English bank statements. |
