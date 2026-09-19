# Sarathi Capabilities

This document specifies the document intelligence capabilities implemented under `src/sarathi/shakti/`. Each capability is registered through a `PluginProvider` in Kosh, resolved by Manthan, and executed by Pravaha.

---

## 1. Native Extraction (`native_extraction`)

Directly extracts text, tables, and document hierarchy from native digital formats without raster OCR.

- **Input**: File bytes matching PDF, DOCX, XLSX, legacy XLS (BIFF8 via Calamine/xlrd), HTML tables, XML Spreadsheet 2003 (SpreadsheetML), and delimited text (CSV, TSV, semicolon, pipe).
- **Output**: `CanonicalDocument` containing `PageData`, `TextSpan` bounding boxes, `TableData`, and metadata; generates plain text and DOCX preview artifacts.
- **Main Fallback Behavior**: For PDF documents with missing, empty, or unparseable text, sets `needs_ocr=True` to trigger an automatic OCR escalation hand-off via Manthan. For non-PDF formats, emits an empty-content warning without escalating. Reuses a single `TextPage` per page and evaluates page image coverage first to bypass redundant table extraction on scanned pages.
- **Engine & Architecture**: Powered by high-performance PyMuPDF (`pymupdf`) for native vector PDF text, span bounding boxes, and embedded TrueType font program extraction (`doc.extract_font(xref)`). Deep layout analysis with reading order recovery is supported via `pymupdf-layout` under the `layout_preserving` profile.
  - **Archive & XML Defenses**: Ingested DOCX, XLSX, and ZIP archives are processed via `SafeZipFile` (in `shakti.text.safe_zip`), strictly enforcing uncompressed byte caps (1 GiB), compression ratio bounds (200.0), and member count limits (10,000) to protect against zip bombs. All XML parsing is secured via `defusedxml` to reject DTD entity expansion (Billion Laughs) and external entity injection.
  - **Vector Drawing Stroke Table Extractor**: Uses `find_tables(vertical_strategy="lines", horizontal_strategy="lines")` with automated fallback to vector drawing path clustering (`_extract_vector_stroke_tables`), directly reconstructing borderless and vector-ruled table grids sub-millisecond without neural model overhead.
  - **Logical Stream-Order Transduction**: Converts legacy font encodings in PDF physical stream order before spatial reading-order sorting, eliminating character run fragmentation and preserving complex conjunct integrity.
- **Relevant Configuration**: `[storage]` (`input_root`, `output_root`, `runtime_root`), `[limits]` (`max_input_bytes`, `max_uncompressed_bytes`, `max_compression_ratio`, `max_zip_members`).
- **Known Limitations**: Does not process raw raster images directly. Encrypted or password-protected files must be decrypted prior to ingestion.

---

## 2. Optical Character Recognition (`ocr`)

Performs local optical character recognition on document images and rasterized PDF pages.

- **Input**: Raster images (PNG, JPEG, TIFF, BMP) or rasterized PDF pages.
- **Output**: `CanonicalDocument` with recognized text lines, page-relative bounding box polygons, confidence scores, and plain text and DOCX artifacts.
- **Main Fallback Behavior**: Primary inference runs on OpenVINO-accelerated RapidOCR (OpenVINO `>=2026.4.0` with Intel Arc iGPU batch size 48 and persistent shader cache `Runtime/Cache/openvino_model_cache`; models: `det`, `cls`, `rec_devanagari`, `rec_v6_en`), defaulting to PP-OCRv5 Devanagari (`rec_devanagari`, recognizing both Hindi/Devanagari script and mixed English alphanumeric text) across Instant and Accurate profiles. English/Latin documents route to PP-OCRv6 Small (`rec_v6_en`) via `lang="en"`. In Accurate and Layout-Preserving profiles, ambiguous or low-confidence crops trigger same-engine weak-crop retry with CLAHE/contrast enhancement, eliminating external secondary OCR engines. Consequence-driven verification automatically elevates retry thresholds (to 0.85) and review warning thresholds (to 0.90) for high-consequence entities (currency, amounts, statutory IDs, dates, account references, legal sections, percentage rates). An atomic content-addressed per-page checkpoint cache (`Runtime/Cache/ocr_checkpoints/`) eliminates recomputation across retries, preserves cached items across transient I/O faults, and enforces age- and byte-based cache eviction. The entire OCR runtime is 100% self-contained within ONNX/OpenVINO targeting Intel Arc GPU first with CPU fallback. Instant profile optimizes throughput by bypassing per-crop angle classification (`use_cls=False`), while Accurate profile preserves orientation classification. Spatial reading order is hierarchically reconstructed using pure-Python Recursive XY-Cut partitioning, eliminating multi-column text interweaving.
- **Image Preprocessing & Optical Enhancement**:
  - **Projection-Profile Deskew**: Implemented in `deskew_image`: computes vertical/horizontal ink projection profiles to estimate skew angle accurately, skipping rotation when confidence is low or when full-page borders/tables are present.
  - **Otsu Adaptive Binarization**: Replaces static thresholds with dynamic `cv2.threshold(..., THRESH_OTSU)` for gradient-illuminated and unevenly scanned pages.
  - **Page Orientation Detection**: Implemented in `choose_page_rotation`: evaluates mean confidence and aspect ratio of recognized bounding boxes; automatically tests and corrects 90°, 180°, and 270° scan misorientations, recording applied rotation in metadata and emitting an `OCR_PAGE_ROTATED` warning.
  - **Hue-Agnostic Stamp Removal**: Implemented in `detect_stamps`: computes paper-relative chroma to segment red, blue, violet, and dark stamps; filters connected components by aspect ratio to preserve legitimate red headings and thin text lines; fills stamp regions with estimated paper background; and emits `STAMP_REMOVAL_APPLIED` only when stamps are actually removed.
  - **Preservative Alphanumeric Filter**: `filter_english_and_numbers` preserves Latin-1 Supplement and Latin Extended letters (`\u00C0-\u024F`), currency (`¥`), and legal/math symbols (`§`, `©`, `®`, `°`, `±`, `×`, `÷`, `½`, `¼`, `¾`, `™`, `…`).
- **Self-Grounded Empirical Benchmarking**: Autonomous gold-truth generation tool (`tools/benchmark_ocr_legacy_gold.py`) sweeps DPIs (150 to 400) to optimize the Pareto frontier and empirically sets the adaptive DPI formula:
  $$\text{Adaptive DPI} = \text{clamp}\left(\frac{32}{\text{median\_glyph\_height\_pt}} \times 72, 150, 400\right)$$
- **Relevant Configuration**: `[hardware]` (`detect_accelerators`, `gpu_capacity_per_device`, `npu_capacity_per_device`), `[storage]` (`runtime_root`). Local model assets configured in `data/ocr/manifest.json`.
- **Known Limitations**: Requires local ONNX model assets in `data/ocr/models/` (`det`, `cls`, `rec_devanagari`, `rec_v6_en`).

---

## 3. Translation (`translation`)

Provides neural machine translation for document text while preserving formatting and structure.

- **Input**: `CanonicalDocument` or plain text with source and target language pairs.
- **Output**: Translated `CanonicalDocument` preserving text spans and table structures, with bilingual plain text and DOCX artifacts.
- **Main Fallback Behavior**: Executes via local CTranslate2 engine supporting AI4Bharat **IndicTrans2** (primary default) and **OPUS-MT** under the canonical `translation` capability. Features dual SentencePiece tokenizers (`model.SRC` and `model.TGT` or `spm.model`), shared vocabularies, and a high-throughput multi-core CPU batch decoder (`translate_batch`). Document translation pre-collects all unique strings across pages, tables, and spans to execute in a single batched pass across all 4 P-cores (`intra_threads=4`, `OMP_NUM_THREADS=4`), synthesizing redundant document-level texts from translated pages to eliminate duplicate inference. Model instances are cached strictly by `(engine, model_path, device, device_index)` to prevent duplicate model allocations across differing concurrency configurations. Explicit beam size and decoding length bounds are enforced, emitting a `TRANSLATION_TRUNCATION_SUSPECTED` warning if hypothesis length reaches decoding bounds.
- **Sentence Segmentation**: Implemented in `split_sentences()`: segments document text cleanly while strictly preserving newlines and abbreviations (Mr., Dr., Sec., No., Hon., Rs., etc.), preventing fragmented sentence splitting and newline stripping.
- **Domain Legal Context & Glossaries**: Integrates dynamic domain context matching and statutory legal glossaries (`pmla.json`, `banking_financial.json`). Features on-device cached glossary matching partitioning terms into at most 8 pre-compiled alternation regex groups, reducing regex compilation overhead to sub-millisecond execution. Anubhava dictionary corrections use precompiled Devanagari script lookarounds `(?<![\u0900-\u097F\w])…(?![\u0900-\u097F\w])` to prevent partial substring corruption inside larger words.
- **Proper-Noun Legal Transliteration Guard**: Implemented in `proper_noun_guard.py`: identifies legal kinship markers and honorific titles (`Shri`, `Smt`, `Mohd`, `W/o`, `S/o`, `D/o`), shields proper nouns with opaque SentencePiece placeholders (`§PROTECTED_NOUN_N§`), and applies ISO 15919 phonetic transliteration to prevent neural translation hallucinations or semantic mistranslations of names and village records.
- **Entity Protection & Transliteration**: Protected entities (numbers, dates, statutory IDs, URLs, and configured glossary terms) are preserved without translation. The number regex preserves adjacent whitespace and date regex boundaries without stripping original text. Language detection automatically discriminates Devanagari regional sub-languages (Hindi `hi`, Marathi `mr`, Nepali `ne`, Sanskrit `sa`) via diagnostic character signatures (e.g. `ळ`) and lexical markers, guarding against accidental translation of non-Hindi texts using the Hindi model unless explicitly overridden. Administrative Romanized Indic (Hinglish) text is detected and phonetically transliterated into Unicode Devanagari via a deterministic rule transducer. Fails explicitly with `DEPENDENCY_UNAVAILABLE` if the requested language direction or model weights are missing.
- **Relevant Configuration**: Model directory in `data/translation/models/indictrans2/` and `data/translation/models/opus_mt/`; `[cache]` (`enabled`, `ttl_seconds`) for caching repeated translation segments. Automated provisioning via `tools/scripts/Setup-TranslationModels.ps1`.
- **Known Limitations**: Local neural models support Hindi <-> English (`hi` <-> `en`). Other language pairs require configured cloud provider adapters.

---

## 4. Legacy Font Conversion (`font_conversion`)

Converts legacy non-Unicode Indian font encodings to standardized Unicode Devanagari.

- **Input**: Plain text, PDF text spans, or DOCX runs containing legacy 8-bit Devanagari font glyphs.
- **Output**: Unicode-compliant Devanagari text and transformed DOCX artifacts preserving font styles and document layout.
- **Main Fallback Behavior**:
  - **Binary FontTools Inspection**: Replaced manual binary unpackers with `font_inspector.py` (via `fontTools.ttLib`), parsing `name`, `post`, and multi-subtable `cmap` structures, and calculating normalized character map signatures and anchor outline hashes via `RecordingPen`. Includes a modern font guard that detects `GSUB` tables with `deva`/`dev2` scripts to prevent false-positive conversion.
  - **Single-Inheritance Profile Hierarchy**: Font profiles inherit from abstract base profiles (`krutidev_base.json` extended by `krutidev010.json`, `krutidev011.json`, and `krutidev290.json`) to eliminate duplicate mapping definitions.
  - **Declarative 7-Pass Akshara Transduction**: Implemented in `converter.py`:
    1. Multi-character clusters & ligatures
    2. Standalone glyphs
    3. Pre-base vowel reordering (`ि` shifting behind multi-part conjuncts)
    4. Post-base reph repositioning (`र्` placed after base consonants)
    5. Nukta / Matra normalization
    6. Unicode canonicalization (NFC)
    7. Pramana fidelity & confidence telemetry
  - **MacRoman Inversion**: Automatically inverts high-bit `0x80`–`0xFF` byte corruption via `byte_normalizer.py` before transducer ingestion.
  - **OpenVINO Metric Visual Prototype Fallback**: Implemented in `visual_resolver.py`: renders PDF glyph crops at median glyph height and classifies unknown or scrambled font families against pre-rendered reference binary prototypes using metric distance, with open-set rejection (`> 0.35`) and patch majority voting.
  - **Statutory Acronym Protection**: Protects critical statutory and legal acronyms (FIR, PMLA, CrPC, BNS, BNSS, BSA, IPC, etc.) from accidental corruption during legacy glyph transcoding.
- **Relevant Configuration**: Font mapping definitions in `data/fonts/` (`krutidev_base.json`, `krutidev010.json`, `krutidev011.json`, `krutidev290.json`, `devlys010.json`, `chanakya010.json`, `shusha010.json`, `shivaji010.json`).
- **Known Limitations**: Requires at least 2 distinct character signatures for automatic text-signature detection. Short strings (<10 characters) without font metadata may not trigger auto-detection.

---

## 5. Bank Statements (`bank_statements`)

Parses, normalizes, and reconciles financial account statements into structured transaction tables.

- **Input**: `CanonicalDocument` containing tabular financial data from native extraction or OCR.
- **Output**: Structured `TransactionRecord` sets with normalized transaction dates, descriptions, reference numbers, debit/credit values, and running balances; exports to CSV, XLSX, JSON, and DOCX.
- **Main Fallback Behavior**: Matches headers against bank-specific layout definitions (`hdfc.yaml`, `icici.yaml`, `sbi.yaml`). If no institution match is found, falls back to common financial table layout heuristics (`common.yaml`) using an expanded universal lexicon of Indian banking variants and automated parenthetical token normalization (e.g. `withdrawal(dr)`, `deposit(cr)`, `balance(inr)`), seamlessly supporting Axis, Kotak, PNB, BOB, Canara, and other Indian banks without requiring dedicated per-bank profiles. Emits warnings if running balance arithmetic does not reconcile.
- **Banking Integrity & UTR/IFSC Auto-Repair**: Implemented in `utr_repair.py`:
  - **RBI Syntax Validation**: Validates 16/22-character UTR numbers and 11-character IFSC codes against RBI structure rules.
  - **Heuristic OCR Auto-Repair**: Fixes common OCR glyph confusions (`O` $\leftrightarrow$ `0`, `I` $\leftrightarrow$ `1`, `S` $\leftrightarrow$ `5`, `B` $\leftrightarrow$ `8`) when the surrounding segment satisfies financial syntactic invariants.
  - **Double-Entry Arithmetic Reconciliation**: Mathematically verifies:
    $$\text{Previous Balance} + \text{Credit} - \text{Debit} = \text{Running Balance} \pm 0.01$$
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
- **Main Fallback Behavior**: Applies formal checksum algorithms (Luhn Mod-36 for GSTIN; structure, state code, and entity type verification for PAN, TAN, CIN, CNR, DIN, IRN). Invalid identifiers are flagged with `is_valid=False` and failure reasons rather than discarded. When OCR candidate corrections (`0` $\leftrightarrow$ `O`, `1` $\leftrightarrow$ `I`) are applied to salvage statutory identifiers, emits a structured `STATUTORY_ID_OCR_REPAIRED` warning containing original and repaired values.
- **Relevant Configuration**: None required; validation algorithms and patterns are built-in.
- **Known Limitations**: Syntactic and algorithmic validation only; does not perform real-time verification against live government databases.

---

## 7. In-Place Multi-Part DOCX Transcoder (`docx_exporter`)

Assembles standardized OpenXML `.docx` documents and transforms existing DOCX packages in-place with bilingual typography.

- **Input**: `CanonicalDocument` structures or raw DOCX package bytes.
- **Output**: Validated ECMA-376 OpenXML `.docx` files.
- **In-Place Multi-Part Transcoder**: Implemented in `transformer.py` using `python-docx` and `oxml`:
  - Traverses the entire package hierarchy including document body, headers, footers, footnotes, endnotes, and embedded tables.
  - Converts legacy non-Unicode font runs (KrutiDev, Devlys, Chanakya, Shusha) directly to Unicode Devanagari in-place.
  - Strictly preserves font run styling (bold, italic, underline, highlight), text colors, run font sizes, and paragraph geometry.
  - Font profiles are loaded directly from `shakti.text.legacy_fonts`, eliminating circular package bridges.
- **Bilingual Typography**: Segments text runs by script: applies Nirmala UI (12 pt) for Devanagari text and Times New Roman (12 pt) for Latin/numeric text.
- **Relevant Configuration**: None required; default typography profiles and table styling parameters are embedded.
- **Known Limitations**: Requires valid OpenXML package structure. Legacy binary `.doc` files must be converted to `.docx` before transformation.

---

## 8. Optional Cloud Providers (`mistral`, `gemini`, `azure`)

Integrates optional external cloud services for OCR and translation when local execution is not requested or requires cloud assistance.

- **Input**: Document images or text payloads sent via provider-specific REST APIs.
- **Output**: `CanonicalDocument` structures and output artifacts identical to local capabilities.
- **Main Fallback Behavior**: Cloud providers run only when authorized by Kavacha. If network access or credentials are not configured, readiness checks report the provider as unavailable and Manthan rejects the plan rather than silently falling back to unrequested services.
- **Unified Transport & Resilience**:
  - **Shared Cloud HTTP Transport**: Uses `CloudHttpClient` (in `shakti.cloud.http`): maintains a connection pool per provider, an interruptible thread-safe token bucket rate limiter (`requests_per_minute`), centralized API key redaction in exception messages, and standard Sarathi User-Agent branding.
  - **Dynamic Backoff & Polling**: Retries 429/503 and network timeouts with exponential backoff honoring `Retry-After`. Azure operations support independent `poll_timeout_seconds` (default 600 s).
  - **Multi-Segment Batching & Fallback Warnings**: Dispatches translation segments in parallel batches (`yantra.execute_subtasks`). If batch translation fails, gracefully falls back to per-item dispatch while emitting a diagnostic `CLOUD_BATCH_FALLBACK` warning.
  - **Gemini Single-Page PDF Streaming**: Multi-page PDFs are automatically split into single-page PDF streams via PyMuPDF to preserve true page numbers and bounding box fidelity, with `responseLogprobs` configured.
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

---

## 10. Canonical Plan Pipeline Execution (`pipeline`)

Provides topological sequential plan execution and continuation handoff via `sarathi.nabhi.pravaha.pipeline.execute_pipeline` (invoked via `Pravaha.execute_plan`).

- **Mechanism**: Orchestrates the sequential execution of resolved capability plans across registered capabilities. Each stage operates with input and security authorization (`Kavacha`), hardware accelerator binding (`Yantra`), intermediate checkpoint caching (`Smriti`), bounded retry with exponential backoff, and quarantine isolation. Intermediate canonical documents produced by upstream stages (e.g., PyMuPDF native extraction or OpenVINO RapidOCR on Intel Arc iGPU) are handed off directly to downstream stages (e.g., CTranslate2 neural translation on multi-core CPU or bank statement reconciliation).
- **Accelerator Binding & Efficiency**: Stages are bound to dedicated hardware devices managed by Yantra, preventing compute-intensive neural inference from choking on single-core serialization and eliminating contention between GPU and CPU workloads.
- **Fail-Safe Invariants**: Strict fail-closed error propagation, provenance chain maintenance, warning aggregation across stages, and atomic lifecycle telemetry recording (`Darpana`).
