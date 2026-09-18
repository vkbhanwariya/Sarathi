# Sarathi Capabilities

This document specifies the document intelligence capabilities implemented under `src/sarathi/shakti/`. Each capability is registered through a `PluginProvider` in Kosh, resolved by Manthan, and executed by Pravaha.

---

## 1. Native Extraction (`native_extraction`)

Directly extracts text, tables, and document hierarchy from native digital formats without raster OCR.

- **Input**: File bytes matching PDF, DOCX, XLSX, legacy XLS (BIFF8 via Calamine/xlrd), HTML tables, XML Spreadsheet 2003 (SpreadsheetML), and delimited text (CSV, TSV, semicolon, pipe).
- **Output**: `CanonicalDocument` containing `PageData`, `TextSpan` bounding boxes, `TableData`, and metadata; generates plain text and DOCX preview artifacts.
- **Main Fallback Behavior**: For PDF documents with missing, empty, or unparseable text, sets `needs_ocr=True` to trigger an automatic OCR escalation hand-off via Manthan. For non-PDF formats, emits an empty-content warning without escalating.
- **Engine & Architecture**: Powered by high-performance PyMuPDF (`pymupdf`) for native vector PDF text, span bounding boxes, and embedded TrueType font program extraction (`doc.extract_font(xref)`). Deep layout analysis with reading order recovery is supported via `pymupdf-layout` under the `layout_preserving` profile.
- **Relevant Configuration**: `[storage]` (`input_root`, `output_root`, `runtime_root`).
- **Known Limitations**: Does not process raw raster images directly. Encrypted or password-protected files must be decrypted prior to ingestion.

---

## 2. Optical Character Recognition (`ocr`)

Performs local optical character recognition on document images and rasterized PDF pages.

- **Input**: Raster images (PNG, JPEG, TIFF, BMP) or rasterized PDF pages.
- **Output**: `CanonicalDocument` with recognized text lines, page-relative bounding box polygons, confidence scores, and plain text and DOCX artifacts.
- **Main Fallback Behavior**: Primary inference runs on OpenVINO-accelerated RapidOCR (OpenVINO `>=2026.4.0` with Intel Arc iGPU batch size 48 and persistent shader cache `Runtime/Cache/openvino_model_cache`; models: `det`, `cls`, `rec_devanagari`, `rec_v6_en`), defaulting to PP-OCRv5 Devanagari (`rec_devanagari`, recognizing both Hindi/Devanagari script and mixed English alphanumeric text) across Instant and Accurate profiles. English/Latin documents route to PP-OCRv6 Small (`rec_v6_en`) via `lang="en"`. In Accurate and Layout-Preserving profiles, ambiguous or low-confidence crops trigger same-engine weak-crop retry with CLAHE/contrast enhancement, eliminating external secondary OCR engines. The entire OCR runtime is 100% self-contained within ONNX/OpenVINO targeting Intel Arc GPU first with CPU fallback. Instant profile optimizes throughput by bypassing per-crop angle classification (`use_cls=False`), while Accurate profile preserves orientation classification. Spatial reading order is hierarchically reconstructed using pure-Python Recursive XY-Cut partitioning, eliminating multi-column text interweaving.
- **Relevant Configuration**: `[hardware]` (`detect_accelerators`, `gpu_capacity_per_device`, `npu_capacity_per_device`). Local model assets configured in `data/ocr/manifest.json`.
- **Known Limitations**: Requires local ONNX model assets in `data/ocr/models/` (`det`, `cls`, `rec_devanagari`, `rec_v6_en`).

---

## 3. Translation (`translation`)

Provides neural machine translation for document text while preserving formatting and structure.

- **Input**: `CanonicalDocument` or plain text with source and target language pairs.
- **Output**: Translated `CanonicalDocument` preserving text spans and table structures, with bilingual plain text and DOCX artifacts.
- **Main Fallback Behavior**: Executes via local CTranslate2 engine supporting AI4Bharat **IndicTrans2** (primary default) and **OPUS-MT** under the canonical `translation` capability. Features dual SentencePiece tokenizers (`model.SRC` and `model.TGT` or `spm.model`), shared vocabularies, and a high-throughput multi-core CPU batch decoder (`translate_batch`). Document translation pre-collects all unique strings across pages, tables, and spans to execute in a single batched pass across all 4 P-cores (`intra_threads=4`, `OMP_NUM_THREADS=4`), turning document reconstruction into instant O(1) in-memory lookups.
- **Domain Legal Context & Glossaries**: Integrates dynamic domain context matching and statutory legal glossaries (`pmla.json`, `banking_financial.json`). Features on-device `GlossaryHarmonizer` for post-translation statutory normalization with Unicode-aware Devanagari boundary matching, ensuring statutory terms and identifiers (PAN, TAN, GSTIN, CIN, CNR, DIN, IRN) are harmonized across languages without semantic drift.
- **Entity Protection & Transliteration**: Protected entities (numbers, dates, statutory IDs, URLs, and configured glossary terms) are preserved without translation. Language detection automatically discriminates Devanagari regional sub-languages (Hindi `hi`, Marathi `mr`, Nepali `ne`, Sanskrit `sa`) via diagnostic character signatures (e.g. `ळ`) and lexical markers, guarding against accidental translation of non-Hindi texts using the Hindi model unless explicitly overridden. Administrative Romanized Indic (Hinglish) text is detected and phonetically transliterated into Unicode Devanagari via a deterministic rule transducer. Fails explicitly with `DEPENDENCY_UNAVAILABLE` if the requested language direction or model weights are missing.
- **Relevant Configuration**: Model directory in `data/translation/models/indictrans2/` and `data/translation/models/opus_mt/`; `[cache]` (`enabled`, `ttl_seconds`) for caching repeated translation segments. Automated provisioning via `tools/scripts/Setup-TranslationModels.ps1`.
- **Known Limitations**: Local neural models support Hindi <-> English (`hi` <-> `en`). Other language pairs require configured cloud provider adapters.

---

## 4. Legacy Font Conversion (`font_conversion`)

Converts legacy non-Unicode Indian font encodings to standardized Unicode Devanagari.

- **Input**: Plain text, PDF text spans, or DOCX runs containing legacy 8-bit Devanagari font glyphs.
- **Output**: Unicode-compliant Devanagari text and transformed DOCX artifacts preserving font styles and document layout.
- **Main Fallback Behavior**:
  - **Multi-Modal Detection**: Detects legacy encodings via statistical character signatures (`_KRUTI_SIGNATURES`, `_CHANAKYA_SIGNATURES`, `_SHUSHA_SIGNATURES`) with token sampling (4.2x preflight acceleration) and TrueType SFNT metadata extraction in DOCX runs and PyMuPDF vector PDF streams (`doc.extract_font(xref)`), successfully mapping embedded obfuscated subset fonts (`ABCDEF+KrutiDev010`). Text lacking sufficient signature evidence (<2 signatures) or matching modern Unicode font lists is preserved unchanged without modification.
  - **Akshara Synthesis & Transducers**: Powered by 14 precompiled Akshara synthesis regular expressions with LRU-cached reph patterns and direct-indexing forward/reverse transducers accelerated by AVX2 SIMD libraries (`rapidfuzz` and `regex`).
  - **Linguistic Normalization & Repair**: Preserves chhoti-i following Nukta (`DEVA_MATRAS`), synthesizes decomposed independent vowels (`अा` -> `आ`, `अो` -> `ओ`, `अौ` -> `औ`, `अॅ` -> `ऑ`, `एे` -> `ऐ`), reorders post-matra Nukta, normalizes typewriter half-consonant + Nukta sequences (`क़्` -> `क़्`), and deduplicates typewriter keyboard slips (`।।` -> `॥`, `़़` -> `़`, `ःः` -> `ः`) and stray ZWNJ.
  - **Statutory Acronym Protection**: Protects critical statutory and legal acronyms (FIR, PMLA, CrPC, BNS, BNSS, BSA, IPC, etc.) from accidental corruption during legacy glyph transcoding.
- **Relevant Configuration**: Font mapping definitions in `data/fonts/` (`krutidev010.json`, `devlys010.json`, `chanakya010.json`, `shusha010.json`, `shivaji010.json`).
- **Known Limitations**: Requires at least 2 distinct character signatures for automatic text-signature detection. Short strings (<10 characters) without font metadata may not trigger auto-detection.

---

## 5. Bank Statements (`bank_statements`)

Parses, normalizes, and reconciles financial account statements into structured transaction tables.

- **Input**: `CanonicalDocument` containing tabular financial data from native extraction or OCR.
- **Output**: Structured `TransactionRecord` sets with normalized transaction dates, descriptions, reference numbers, debit/credit values, and running balances; exports to CSV, XLSX, JSON, and DOCX.
- **Main Fallback Behavior**: Matches headers against bank-specific layout definitions (`hdfc.yaml`, `icici.yaml`, `sbi.yaml`). If no institution match is found, falls back to common financial table layout heuristics (`common.yaml`) using an expanded universal lexicon of Indian banking variants and automated parenthetical token normalization (e.g. `withdrawal(dr)`, `deposit(cr)`, `balance(inr)`), seamlessly supporting Axis, Kotak, PNB, BOB, Canara, and other Indian banks without requiring dedicated per-bank profiles. Emits warnings if running balance arithmetic does not reconcile.
- **Relevant Configuration**: Bank templates in `data/banks/`.
- **Known Limitations**: Requires tabular row/column structure. Cannot reliably parse free-text transaction summaries or multi-column non-tabular layouts.

### Domain Rules & Reconciliation Engine
- **Row Classification**: Every extracted row is categorized prior to parsing:
  - `TRANSACTION`: Core row containing date, description, amount, and balance.
  - `CONTINUATION`: Multi-line transaction description wrapped onto a subsequent line.
  - `OPENING_BALANCE` / `CLOSING_BALANCE`: Boundary balance rows extracted for audit reconciliation.
  - `HEADER` / `REPEATED_HEADER`: Primary and repeated page headers categorized and filtered.
  - `NOISE` / `SUMMARY`: Non-transactional disclosures, footnotes, and page numbers.
- **Three Distinct Balance Semantics & Inference**:
  1. *Opening Balance*: Initial statement balance prior to transactions in the period; if missing from header cards, automatically inferred from `closing - total_credits + total_debits`.
  2. *Running Balance*: Per-transaction reported balance; validated continuously via `balance[i] = balance[i-1] + credit - debit`.
  3. *Closing Balance*: Declared statement ending balance; compared against calculated terminal balance to establish reconciliation confidence; if missing, automatically inferred from `opening + total_credits - total_debits`.
- **Bi-Directional Continuity Anchoring**: Runs forward continuity from opening balance and reverse continuity from closing balance to isolate single-row OCR glitches (such as header opening balance artifacts) without cascading false-alarm errors across the statement.
- **Debit / Credit Inversion Detection**: If a statement's columns are inverted (e.g. credits recorded in debit column or vice versa), the validator tests whether swapped arithmetic resolves the running balance delta and logs an inversion warning.
- **Multi-Page Overlap Deduplication**: Compares transaction dates, normalized amounts, reference numbers, and running balances across page boundaries to eliminate duplicate rows caused by pagination overlaps.

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
- **Main Fallback Behavior**: Segments text runs by script: applies Nirmala UI (12 pt) for Devanagari text and Times New Roman (12 pt) for Latin/numeric text. Preserves existing styles (bold, italic, tables, headings). Employs high-fidelity table layout preservation: computes proportional column widths (`<w:tblGrid>`), applies standardized cell margin padding (`<w:tblCellMar>`), enforces `<w:cantSplit/>` to prevent row pagination slicing, anchors tables in narrative flow via `{{TABLE:...}}` markers, and deduplicates consecutive identical rows. Falls back to plain text export if DOCX package assembly fails.
- **Relevant Configuration**: None required; default typography profiles and table styling parameters are embedded.
- **Known Limitations**: Requires valid OpenXML package structure. Legacy binary `.doc` files must be converted to `.docx` before transformation.

---

## 8. Optional Cloud Providers (`mistral`, `gemini`, `azure`)

Integrates optional external cloud services for OCR and translation when local execution is not requested or requires cloud assistance.

- **Input**: Document images or text payloads sent via provider-specific REST APIs.
- **Output**: `CanonicalDocument` structures and output artifacts identical to local capabilities.
- **Main Fallback Behavior**: Cloud providers run only when authorized by Kavacha. If network access or credentials are not configured, readiness checks report the provider as unavailable and Manthan rejects the plan rather than silently falling back to unrequested services.
- **Resilience & Rate Pacing**:
  - **Inter-Request Pacing**: Enforces minimum spacing (`rate_limit_delay_seconds = 2.0`) between consecutive API dispatches, strictly honoring Mistral free-tier (1 RPS / 30 RPM) and Gemini limits.
  - **Dynamic Backoff**: Parses server `Retry-After` and `x-ratelimit-reset` response headers, executing progressive exponential backoff across up to 5 retry attempts.
  - **Multi-Segment Batching & Prompt Seeding**: Dispatches text segments in batched payloads, with prompt glossary seeding capped to top 5 statutory directives to avoid TPM limits.
  - **Fail-Fast Boundary**: Fails fast on `RESOURCE_UNAVAILABLE` or `SECURITY_DENIED` rather than cascading into silent unauthenticated loops.
- **Relevant Configuration**:
  - `[security]`: `allow_network_access = true`, `allow_external_processing = true`, and secret names listed in `allowed_secrets`.
  - Sections: `[mistral]`, `[gemini]`, `[azure]`.
- **Known Limitations**: Requires active internet connectivity and valid API credentials. Subject to external network latency, provider rate limits, and egress policy.

---

## 9. Execution Profiles Matrix

Sarathi defines four standard execution profiles via `sarathi.sankalpa.execution_profile`:

| Profile | Strategy | OCR Behavior | Extraction & Validation Behavior |
| --- | --- | --- | --- |
| **`INSTANT`** | Throughput-optimized single pass | Bypasses heavy preprocessing; bypasses per-crop angle classifier (`use_cls=False`); no eager crop allocation; standard RapidOCR resolution. | Fast single-pass native extraction; standard reconciliation heuristics. |
| **`ACCURATE`** | Quality-optimized multi-pass | Full image preprocessing (CLAHE, deskew, binarization); full orientation classification (`use_cls=True`); targeted same-engine weak-crop retry on low-confidence Devanagari spans with CLAHE enhancement. | Strict running balance verification, bi-directional anchoring, inversion detection, and multi-page deduplication. |
| **`LAYOUT_PRESERVING`** | Structure and spatial preservation | Full image preprocessing, orientation classification, and recursive XY-cut hierarchical ordering preserving spatial column/block layout. | Strict multi-column flow, layout-preserving text alignment, and block boundary isolation. |
| **`CUSTOM`** | Parameter-controlled execution | Execution parameters specified directly via `request.custom_options` (e.g. `use_angle_cls`, custom confidence threshold, explicit model overrides). | Custom validation thresholds and options. |

### Recursive Prerequisite Profile Validation
When a request specifies an execution profile, Manthan recursively validates that every required capability in the dependency chain officially supports that profile. If any transitive dependency does not support the requested profile, the planning phase fails fast with `FailureCode.UNSUPPORTED` rather than executing an inconsistent or silently downgraded pipeline.
