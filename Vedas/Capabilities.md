# Sarathi Capabilities

This document specifies the document intelligence capabilities implemented under `src/sarathi/shakti/`. Each capability is registered through a `PluginProvider` in Kosh, resolved by Manthan, and executed by Pravaha.

---

## 1. Native Extraction (`native_extraction`)

Directly extracts text, tables, and document hierarchy from native digital formats without raster OCR.

- **Input**: File bytes matching PDF, DOCX, XLSX, legacy XLS (BIFF8), HTML tables, XML Spreadsheet 2003 (SpreadsheetML), and delimited text (CSV, TSV, semicolon, pipe).
- **Output**: `CanonicalDocument` containing `PageData`, `TextSpan` bounding boxes, `TableData`, and metadata; generates plain text and DOCX preview artifacts.
- **Main Fallback Behavior**: For PDF documents with missing, empty, or unparseable text, sets `needs_ocr=True` to trigger an automatic OCR escalation hand-off via Manthan. For non-PDF formats, emits an empty-content warning without escalating.
- **Relevant Configuration**: `[storage]` (`input_root`, `output_root`, `runtime_root`).
- **Known Limitations**: Does not process raw raster images directly. Encrypted or password-protected files must be decrypted prior to ingestion.

---

## 2. Optical Character Recognition (`ocr`)

Performs local optical character recognition on document images and rasterized PDF pages.

- **Input**: Raster images (PNG, JPEG, TIFF, BMP) or rasterized PDF pages.
- **Output**: `CanonicalDocument` with recognized text lines, page-relative bounding box polygons, confidence scores, and plain text and DOCX artifacts.
- **Main Fallback Behavior**: Primary inference runs on RapidOCR with OpenVINO acceleration (models: `det`, `rec`, `cls`, `rec_devanagari`, `rec_v6_en`). In accurate profile, ambiguous or low-confidence alphanumeric spans trigger targeted local Tesseract 5 fallback recognition.
- **Relevant Configuration**: `[hardware]` (`detect_accelerators`, `gpu_capacity_per_device`, `npu_capacity_per_device`). Local model assets configured in `data/ocr/manifest.json`.
- **Known Limitations**: Requires local ONNX model assets in `data/ocr/models/`. Tesseract fallback requires a local Tesseract 5 executable with language packs (`eng`, `hin`).

---

## 3. Translation (`translation`)

Provides neural machine translation for document text while preserving formatting and structure.

- **Input**: `CanonicalDocument` or plain text with source and target language pairs.
- **Output**: Translated `CanonicalDocument` preserving text spans and table structures, with bilingual plain text and DOCX artifacts.
- **Main Fallback Behavior**: Executes via local CTranslate2 engine using quantized models and SentencePiece tokenizers. Protected entities (numbers, dates, statutory IDs, URLs, and configured glossary terms) are preserved without translation. Fails explicitly if the requested language direction is unavailable.
- **Relevant Configuration**: Model directory in `data/translation/`; `[cache]` (`enabled`, `ttl_seconds`) for caching repeated translation segments.
- **Known Limitations**: Local neural models support Hindi <-> English (`hi` <-> `en`). Other language pairs require configured cloud provider adapters.

---

## 4. Legacy Font Conversion (`font_conversion`)

Converts legacy non-Unicode Indian font encodings to standardized Unicode Devanagari.

- **Input**: Plain text, PDF text spans, or DOCX runs containing legacy 8-bit Devanagari font glyphs.
- **Output**: Unicode-compliant Devanagari text and transformed DOCX artifacts preserving font styles and document layout.
- **Main Fallback Behavior**: Detects legacy encodings using statistical character signatures (`_KRUTI_SIGNATURES`, `_CHANAKYA_SIGNATURES`, `_SHUSHA_SIGNATURES`) and TrueType font table metadata. Text lacking sufficient signature evidence (<2 signatures) or matching modern Unicode font lists is preserved unchanged without modification.
- **Relevant Configuration**: Font mapping definitions in `data/fonts/` (`krutidev010.json`, `devlys010.json`, `chanakya010.json`, `shusha010.json`, `shivaji010.json`).
- **Known Limitations**: Requires at least 2 distinct character signatures for automatic text-signature detection. Short strings (<10 characters) without font metadata may not trigger auto-detection.

---

## 5. Bank Statements (`bank_statements`)

Parses, normalizes, and reconciles financial account statements into structured transaction tables.

- **Input**: `CanonicalDocument` containing tabular financial data from native extraction or OCR.
- **Output**: Structured `TransactionRecord` sets with normalized transaction dates, descriptions, reference numbers, debit/credit values, and running balances; exports to CSV, XLSX, JSON, and DOCX.
- **Main Fallback Behavior**: Matches headers against bank-specific layout definitions (`hdfc.yaml`, `icici.yaml`, `sbi.yaml`). If no institution match is found, falls back to common financial table layout heuristics (`common.yaml`). Emits warnings if running balance arithmetic does not reconcile.
- **Relevant Configuration**: Bank templates in `data/banks/`.
- **Known Limitations**: Requires tabular row/column structure. Cannot reliably parse free-text transaction summaries or multi-column non-tabular layouts.

---

## 6. Statutory Processing (`statutory`)

Extracts and mathematically verifies statutory, tax, and corporate identifiers from government and legal documents.

- **Input**: `CanonicalDocument` or plain text from contracts, tax filings, invoices, or legal orders.
- **Output**: Validated statutory entity metadata records (`StatutoryMetadata`) covering GSTIN, PAN, TAN, CIN, CNR (eCourts), DIN, and IRN, with individual validation flags and structured summary artifacts.
- **Main Fallback Behavior**: Applies formal checksum algorithms (Luhn Mod-36 for GSTIN; structure, state code, and entity type verification for PAN, TAN, CIN, CNR, DIN, IRN). Invalid identifiers are flagged with `is_valid=False` and failure reasons rather than discarded.
- **Relevant Configuration**: None required; validation algorithms and patterns are built-in.
- **Known Limitations**: Syntactic and algorithmic validation only; does not perform real-time verification against live government databases.

---

## 7. DOCX / Output Generation (`docx_exporter`)

Assembles standardized OpenXML `.docx` documents and transforms existing DOCX packages with bilingual typography.

- **Input**: `CanonicalDocument` structures or raw DOCX package bytes.
- **Output**: Validated ECMA-376 OpenXML `.docx` files.
- **Main Fallback Behavior**: Segments text runs by script: applies Nirmala UI (12 pt) for Devanagari text and Times New Roman (12 pt) for Latin/numeric text. Preserves existing styles (bold, italic, tables, headings). Falls back to plain text export if DOCX package assembly fails.
- **Relevant Configuration**: None required; default typography profiles are embedded.
- **Known Limitations**: Requires valid OpenXML package structure. Legacy binary `.doc` files must be converted to `.docx` before transformation.

---

## 8. Optional Cloud Providers (`mistral`, `gemini`, `azure`, `bhashini`)

Integrates optional external cloud services for OCR and translation when local execution is not requested or requires cloud assistance.

- **Input**: Document images or text payloads sent via provider-specific REST APIs.
- **Output**: `CanonicalDocument` structures and output artifacts identical to local capabilities.
- **Main Fallback Behavior**: Cloud providers run only when authorized by Kavacha. If network access or credentials are not configured, readiness checks report the provider as unavailable and Manthan rejects the plan rather than silently falling back to unrequested services.
- **Relevant Configuration**:
  - `[security]`: `allow_network_access = true`, `allow_external_processing = true`, and secret names listed in `allowed_secrets`.
  - Sections: `[mistral]`, `[gemini]`, `[azure]`, `[bhashini]`.
- **Known Limitations**: Requires active internet connectivity and valid API credentials. Subject to external network latency, provider rate limits, and egress policy.
