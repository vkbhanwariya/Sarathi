# Sarathi Capabilities

This document specifies the document intelligence capabilities in `src/sarathi/shakti/`. Each capability is registered via a `PluginProvider` in Kosh, resolved into an ordered execution plan by Manthan, and executed by Pravaha.

---

## Capabilities Overview Matrix

| Capability | Identifier | Engine & Primary Hardware Target | Supported Inputs | Primary Deliverables |
| :--- | :--- | :--- | :--- | :--- |
| **Native Extraction** | `native_extraction` | PyMuPDF vector parser (CPU) | Digital PDF, DOCX, XLSX, XLS, HTML, CSV/TSV | `CanonicalDocument`, extracted tables, preview text |
| **Local OCR** | `ocr` | RapidOCR on OpenVINO (Intel Arc iGPU) | Scanned PDF, PNG, JPEG, TIFF, BMP | `CanonicalDocument`, bounding boxes, DOCX preview |
| **Neural Translation** | `translation` | CTranslate2 Krutrim-Translate (14-Core CPU, 4096 Context) | `CanonicalDocument`, Hindi / English text | Translated `CanonicalDocument`, bilingual DOCX |
| **Font Conversion** | `font_conversion` | Declarative 7-pass Akshara Transducer (CPU) | Word (`.docx`), Excel (`.xlsx`), legacy font text | Clean Unicode Devanagari `.docx`, `.xlsx` |
| **Bank Statements** | `bank_statements` | Financial Reconciler & Polars Vectorizer (CPU) | Tabular bank statements (PDF, XLSX, CSV) | `List_of_Accounts.xlsx`, `Consolidated_Transactions.xlsx`, 32-col `.parquet`, run manifest |
| **Statutory Extraction** | `statutory` | Algorithmic Checksum Engine (CPU) | `CanonicalDocument`, legal/tax documents | Validated GSTIN, PAN, TAN, CIN, CNR, DIN metadata |
| **DOCX Exporter** | `docx_exporter` | OpenXML WordprocessingML Packager (CPU) | `CanonicalDocument`, raw DOCX packages | Formatted Word `.docx` with bilingual typography |
| **Cloud Adapters** | `mistral` | REST APIs (Authorized Egress Only) | Images, PDFs | Remote OCR fallback (Mistral OCR) |

---

## 1. Native Extraction (`native_extraction`)
- **Engine**: PyMuPDF (`pymupdf`) vector text and character bounding box extraction. High-performance Rust layout and reading-order recovery via `xberg` under `layout_preserving` profile (also powers native PPTX and RTF extraction).
- **Format Coverage**:
  - *Spreadsheets*: Modern XLSX/XLSM (`python-calamine` / `openpyxl`), legacy BIFF8 XLS (Calamine / `xlrd`), XML SpreadsheetML 2003, and HTML tables disguised as `.xls`.
  - *Delimited Text*: CSV, TSV, semicolon, pipe (dialect auto-sniffed via `csv.Sniffer`, memory-efficient columnar parsing via `polars`).
  - *Encodings*: Auto-sniffed via `charset-normalizer` (UTF-8/16, CP1252, Latin-1, with graceful replacement fallback).
- **Stroke Table Recovery**: Clusters vector drawing paths (`_extract_vector_stroke_tables`) to reconstruct borderless and ruled tables sub-millisecond without neural model overhead.
- **Chunked Multi-Process Extraction**: For vector PDFs > 4 pages, PyMuPDF extraction executes across partitioned page chunks via `ProcessPoolExecutor` with isolated address spaces, eliminating Python GIL and Fitz context lock contention on multi-core CPUs (tuned for Intel Core Ultra 5 125H). Retains synchronous in-process path for $\le 4$ pages with automatic serial fallback on subprocess exceptions.
- **Archive & XML Defenses**: Safe zip decompression caps (1 GiB uncompressed, 200.0 ratio bound, 10,000 members) and `defusedxml` protection against Billion Laughs and XXE.
- **Fallback**: Sets `needs_ocr=True` on scanned or empty-text PDFs to trigger automated OCR escalation via Manthan.

---

## 2. Optical Character Recognition (`ocr`)
- **Engine**: RapidOCR targeting Intel Arc iGPU via OpenVINO (`>=2026.4.0`) with persistent shader cache (`Runtime/Cache/openvino_model_cache`).
- **Models**: PP-OCRv5 Devanagari (`rec_devanagari`, Hindi + English alphanumeric) and PP-OCRv6 English (`rec_v6_en`).
- **Optimization & Layout**:
  - Pure-Python Recursive XY-Cut partitioning and spatial reading order reconstruction.
  - Horizontal column-gutter isolation preventing cross-column row combining in multi-column layouts and borderless statements.
  - Baseline-anchored vowel matra jitter tolerance preserving Devanagari word integrity.
  - Terminal punctuation-aware paragraph continuity tracking across line boundaries.
  - Same-engine weak-crop retry on low-confidence spans with CLAHE/contrast enhancement.
  - Deep layout reconstruction & table extraction via OpenCV morphology and coordinate clustering under `LAYOUT_PRESERVING` profile or `preserve_layout` custom option, with `LAYOUT_TABLE_ROW_RAGGED` warnings.
  - Source-coordinate transform preservation: DPI (`source_dpi`) is tracked through execution profiles (150 DPI for instant, 200 DPI for accurate, 250 DPI for high DPI) to ensure pixel-perfect preview crops in UI review.
  - Consequence-driven verification: elevated retry (0.85) and review (0.90) thresholds for currency, amounts, statutory IDs, dates, and legal sections. Preserves observed candidate values and requires review without manufacturing fake checksum digits.
  - Content-addressed per-page checkpoint cache (`Runtime/Cache/ocr_checkpoints/`) for instant recovery.

---

## 3. Neural Machine Translation (`translation`)
- **Engine**: CTranslate2 running Krutrim-Translate (4096 Context INT8) across all 4 CPU P-cores (`intra_threads=4`, `inter_threads=1`, dynamic decoding length scaling). Dual-model RAM pre-warming ensures sub-second switching between Hindi → English and English → Hindi. Thread topology is centrally budgeted via `sarathi.yantra.manager.get_neural_thread_topology()`.
- **Token Chunking**: Subdivides long sentences reserving language prefix tokens (`[src_tag, tgt_tag]`) to strictly prevent CTranslate2 context window overflow.
- **Batching & Efficiency**: Pre-collects and length-buckets all unique strings across pages, tables, and spans to execute in a single batched CPU pass (`translate_batch`).
- **Safeguards & Glossaries**:
  - **Proper Noun Guard**: Identifies kinship markers/titles (`Shri`, `Smt`, `S/o`) and applies ISO 15919 transliteration to prevent hallucinations of personal and village names.
  - **Domain Glossaries**: Cached regex alternation groups for statutory legal terminology (PMLA, IPC, BNS, Banking).
  - **Entity Protection**: Automatically masks dates, numbers, URLs, and statutory IDs with opaque tokens during translation.
  - **Factual Validator**: Post-translation validator checking preservation of typed facts including currency amounts (`₹`, `$`, `Rs.`), percentage rates (`%`), signed numbers, and statutory IDs.
  - **Office Document Fidelity**: In-place OpenXML spreadsheet (`.xlsx`, `.xlsm`) translation synchronizing `TableColumn` definitions with translated headers, preserving VBA macros and formulas without OpenXML corruption.

---

## 4. Legacy Font Conversion (`font_conversion`)
- **Engine**: Declarative 7-pass Akshara transduction engine (ligatures, consonants, pre-base `ि` vowel reordering, post-base `र्` reph repositioning, and NFC normalization).
- **Supported Fonts**: Kruti Dev (010, 011, 290), Devlys 010, Chanakya 010, Shusha 010, Shivaji 010.
- **FontTools Inspection**: Parses SFNT `cmap` signatures and RecordingPen glyph hashes via `font_inspector.py`.
- **Safeguards**: MacRoman high-bit byte stream inversion, typewriter mechanical repairs, and statutory acronym protection (FIR, PMLA, CrPC, BNS).
- **Public Encapsulation**: Exposes clean public methods on `FontConversionCapability` (`normalize_docx_bytes()`, `convert_text()`, `is_legacy_text()`, `profiles`) preventing ownership leakage across domain capabilities.

---

## 5. Bank Statements (`bank_statements`)
- **Engine**: Dynamic institutional schema matcher (`<bank>_<container>_<variant>.yaml`) with registered-profile prioritization and universal fallback heuristic (`common.yaml`).
- **Canonical Indian Bank Master Registry**: Enforces strict institutional naming across 158 RBI-recognized Indian banks (`src/sarathi/data/banks/banks_catalog.json`). Authoritative 4-letter IFSC prefix matching and normalized alias resolution prevent random table or Excel headers from leaking as bank names. Unidentified institutions are strictly assigned `"Unknown Bank"` and emit a non-fatal `ValidationIssue(code="UNKNOWN_BANK", ...)` warning, flagging the statement in the Exceptions ledger.
- **Deterministic Identity & Provenance**:
  - **Account Identity & Fingerprinting**: Derives typed `AccountIdentity` with canonical immutable `account_key` and `identity_strength` rating (`STRONG` / `WEAK`). Raw account numbers are safely masked (retaining last 4 digits). SHA-256 `account_key` is computed deterministically from normalized unmasked account numbers (delimiters stripped) decoupled from IFSC prefix. Re-masking preserves the original identity key without cryptographic destruction. Masked account numbers alone are treated as weak evidence and never conflated across distinct accounts.
  - **Deterministic Statement & Continuous Transaction IDs**: Every statement receives a unique `statement_id` (`stmt_<bank>_acc_<fingerprint>_<doc_fingerprint>`). Transactions receive continuous, unique sequential IDs (`TXN-0001`..`TXN-NNNN`) sorted hierarchically by source input file order, worksheet index, and chronological date+time, preserving `source_input_id`, `input_location` (e.g. `File_S1_R04`), `page_number`, and `row_index`.
- **Integrity & Financial Reconciliation**:
  - **Double-Entry Arithmetic**: Verifies $\text{Opening Balance} + \text{Credits} - \text{Debits} == \text{Closing Balance} \pm 0.01$ per statement and page, capturing discrepancies in a calculated reconciliation diff. Boundary balances are strictly isolated per account in multi-account workbooks.
  - **Continuous Running Balance & Signed Amounts**: Validates row-by-row balance progression, handles signed balance amounts (`Dr`/`Cr`, trailing `-`), and detects debit/credit column inversion.
  - **Currency & Forex Isolation**: Statements default to Indian Rupee (`INR`). Debit, credit, and balance columns on Indian bank accounts are strictly denominated in INR. Foreign currency mentions and exchange rates in transaction descriptions (e.g. international e-commerce or POS purchases) are isolated as descriptive narration and never contaminate statement currency or column amounts. Explicit profile configurations or labeled statement headers (e.g. `Currency: USD`) are respected, maintaining discrete debit and credit totals by currency (`totals_by_currency`).
  - **Date Disambiguation & Repeated Dates**: Resolves dates strictly in profile priority order, parses separate `value_date` and `posting_date`, and forwards blank/repetition markers (`"`, `ditto`, `do`, `-`).
  - **Cheque vs Reference Isolation**: Enforces strict separation between cheque numbers (`cheque_number`) and transaction/UTR reference numbers (`reference_number`).
  - **UTR & IFSC Syntax Repair**: Validates 16/22-character UTR numbers and 11-character IFSC codes, repairing OCR confusion (`0` $\leftrightarrow$ `O`, `1` $\leftrightarrow$ `I`, `8` $\leftrightarrow$ `B`) reusing canonical `IFSC_PATTERN` from statutory.
  - **Multi-Month Deduplication & Status Escalation**: Eliminates overlapping transactions across consecutive statement files within verified account groups. Probable duplicates escalate status to `ValidationStatus.WARNING`, and audit exceptions are deduplicated across statement and consolidation scopes.
- **Canonical Output Deliverables**:
  - **Master Account Directory (`List_of_Accounts.xlsx`)**:
    1. `Accounts`: 6-column Master Account Directory (`S.No.`, `Name of the Account Holder`, `Account No.`, `Bank Name`, `Input Location Range`, `Transaction ID Range`). Aggregates multiple monthly statements into **exactly 1 row per unique bank account**, displaying overarching input location and transaction ID ranges.
    2. `Processing_Summary`: 13-column extraction and schema audit ledger (`S.No.`, `Source File`, `Account No.`, `Bank Name`, `Profile Used`, `Header Match Score`, `Total Rows Scanned`, `Successful Transactions`, `Duplicates Removed`, `Failed / Skipped Rows`, `Status`, `Warnings Count`, `Warning / Audit Details`) with bottom `=SUM(...)` totals. Row metrics are strictly statement/file-scoped.
  - **Passbook Ledger (`Consolidated_Transactions.xlsx`)**: Clean 9-column passbook ledger (`Transaction ID`, `Input Location`, `Date`, `Description`, `Ref / UTR No.`, `Cheque No.`, `Debit`, `Credit`, `Balance`) with Indian number formatting `0,00,000.00`, native Excel dates, continuous sequential IDs (`TXN-0001`..`TXN-NNNN`), and dynamic `=SUBTOTAL(9, ...)` totals (safely guarded and omitted when mixed currencies are present to avoid invalid combined financial totals).
  - **32-Column Enriched Parquet (`Consolidated_Bank_Statement.parquet`)**: High-performance columnar dataset preserving exact `pl.Decimal(38, scale)` precision, `transaction_hash`, `transaction_mode`, `eod_balance`, `balance_as_on`, full metadata, and source provenance for downstream analytical queries.
  - **Execution Manifest (`run-manifest.json`)**: Cryptographic SHA-256 hashes, input outcomes, provenance lineage, and runtime telemetry.
- **Provider Readiness**:
  - `BankStatementsProvider.readiness()` evaluates registered profiles in `src/sarathi/data/banks/` and falls back cleanly to `common.yaml`, reporting readiness status and active profile counts without throwing exceptions.
- **Schema Mapping & Profiling**: See [`Bank_Statement_Mapping_Guide.md`](Bank_Statement_Mapping_Guide.md) for dynamic schema matching and onboarding new bank YAML profiles.

---

## 6. Statutory Extraction (`statutory`)
- **Engine**: Algorithmic checksum validators and regex detectors for Indian government and corporate identifiers.
- **Canonical Domain Primitives**: Authoritative `STATUTORY_ID_BOUNDED_PATTERN`, `IFSC_PATTERN`, and checksum algorithms are defined in `sarathi.shakti.statutory.checksums` and shared across OCR recovery, bank statements, and translation validation.
- **Covered Identifiers**: GSTIN (Luhn Mod-36 checksum), PAN, TAN, CIN, CNR (eCourts 16-character format), DIN, and IRN.
- **Behavior**: Flagged with `is_valid=False` and failure reasons rather than discarded. Emits `STATUTORY_ID_OCR_REPAIRED` when OCR character confusion is resolved.

---

## 7. DOCX Exporter (`docx_exporter`)
- **Engine**: In-place OpenXML WordprocessingML transformer (`transformer.py`) and package builder.
- **Behavior**: Transcodes legacy font runs in-place across paragraphs, tables, headers, footers, and footnotes while preserving bold, italic, font sizes, colors, and table geometries.
- **Bilingual Typography**: Formats Devanagari text in Nirmala UI (12 pt) and Latin/numeric text in Times New Roman (12 pt).

---

## 8. Optional Cloud OCR Providers (`mistral`)
- **Engine**: REST clients implementing `CloudHttpClient` with per-provider connection pools and token-bucket rate limiters.
- **Fail-Closed Security**: Blocked by default. Enabled only when `[security]` grants explicit network access and secret permission (`MISTRAL_API_KEY`). Fails fast without leaking plain text or paths.

---

## 9. Execution Profiles Matrix

| Profile | Strategy | OCR Behavior | Extraction & Validation Behavior |
| :--- | :--- | :--- | :--- |
| **`INSTANT`** | Throughput-optimized single pass | Bypasses crop angle classifier (`use_cls=False`); standard RapidOCR resolution. | Fast single-pass native extraction; standard reconciliation heuristics. |
| **`ACCURATE`** | Quality-optimized multi-pass | Full image preprocessing (CLAHE, deskew, binarization); full angle classification (`use_cls=True`); same-engine weak-crop retry. | Strict balance verification, bi-directional anchoring, inversion detection, deduplication. |
| **`LAYOUT_PRESERVING`** | Spatial structure preservation | Full preprocessing, orientation classification, and Recursive XY-Cut spatial partitioning. | Multi-column flow preservation, Xberg Rust reading-order recovery, table reconstruction, and block boundary isolation. |
| **`CUSTOM`** | Parameter-controlled execution | Configured via `request.custom_options` (model overrides, angle thresholds, DPI). | Custom validation thresholds and options. |
