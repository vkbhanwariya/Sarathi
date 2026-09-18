# Upgrades — High-ROI Architectural Capabilities Specification

This document serves as the authoritative technical specification and design reference for the **7 High-ROI Architectural Capabilities** planned for Sarathi. Each specification defines the problem, architectural owner, technical design, contracts, hardware synergy, and verification criteria.

---

## Roadmap Overview

| # | Capability | Canonical Owner | Primary Target | Expected ROI |
| :- | :--- | :--- | :--- | :--- |
| **1** | **Legacy Font Identification & Staged Transduction (FontTools + SIL NRSI + KrutiExtract)** | `shakti.font_conversion` & `native_extraction` | PDF embedded fonts & legacy Devanagari text | 100% binary font identity + stream-order extraction + 7-pass staged decoding fixing digits & Shusha. |
| **2** | **In-Place Multi-Part DOCX Transcoder** | `shakti.docx_exporter` | `.docx` documents with legacy fonts | Transcodes headers, footers, footnotes, and tables in-place with zero formatting loss. |
| **3** | **Vector Drawing PDF Table Extractor** | `shakti.native_extraction` | Native vector-ruled PDFs (statements, gazettes) | Sub-millisecond table boundary reconstruction directly from vector strokes without neural models. |
| **4** | **Banking Integrity & UTR/IFSC Auto-Repair** | `shakti.bank_statements` | Scanned & native financial statements | Mathematical double-entry balance verification and deterministic OCR confusion repair (`0`↔`O`, `1`↔`I`). |
| **5** | **Proper-Noun Legal Transliteration Guard** | `shakti.translation` | Administrative, court, and revenue records | Rule-based phonetic transliteration protecting Indian names/villages from semantic NMT mistranslation. |
| **6** | **High-Throughput Stage Pipeline Overlap** | `nabhi.pravaha` / `yantra` | Multi-document and multi-stage jobs | Overlaps Intel Arc iGPU (OCR) and Core Ultra CPU (Translation) for up to 2× batch throughput. |
| **7** | **Self-Grounded OCR Benchmark & Hardware Tuning** | `tools` / `shakti.ocr` | Born-digital legacy PDFs & RapidOCR/OpenVINO | Automated ground-truth generation without human transcription; empirical Pareto tuning for Arc iGPU. |

---

## 1. Legacy Font Identification & Staged Transduction (FontTools, SIL NRSI & KrutiExtract)

### Objective
Pair **authoritative binary font identification** (FontTools) with **stream-order native extraction** (KrutiExtract) and **7-pass staged Devanagari decoding** (SIL NRSI), preventing visual geometry scrambled keystrokes (`vkSj` ➔ `vkjS`), replacing flat dictionary replacements with a staged pure-Python transduction pipeline, and resolving critical profile bugs in KrutiDev and Shusha.

### Canonical Ownership
- **Owner**: `sarathi.shakti.font_conversion` & `sarathi.shakti.native_extraction`
- **Modules**:
  - `src/sarathi/shakti/font_conversion/font_inspector.py` (Binary font identification & GSUB guard)
  - `src/sarathi/shakti/font_conversion/converter.py` (Declarative 7-pass `AksharaConverter` execution pipeline)
  - `src/sarathi/shakti/font_conversion/profiles.py` (Extended `LegacyFontProfile` schema & inheritance)
  - `src/sarathi/shakti/font_conversion/byte_normalizer.py` (MacRoman ➔ Windows-1252 byte stream repair)
  - `src/sarathi/shakti/native_extraction/readers/pdf.py` (Stream-order legacy conversion before layout reconstruction)
- **Developer Tools**:
  - `tools/audit_legacy_font.py` (TTF validation & cmap signature generator)
  - `tools/audit_font_profile.py` (Profile fidelity & round-trip ambiguity auditor)
  - `tools/audit_sil_legacy_maps.py` (Build-time SIL `.map` differential fixture generator)
  - `tools/mine_mapping_candidates.py` (Mapping candidate miner from aligned legacy/Unicode pairs)
  - `tools/glyph_sheet.py` (Visual glyph crop audit sheet generator)
- **Profiles & Data**:
  - `data/fonts/krutidev_base.json` (Shared KrutiDev rules)
  - `data/fonts/krutidev010.json`, `krutidev011.json`, `krutidev290.json` (Variant overlay deltas)
  - `data/fonts/shusha010.json` (Reconstructed authentic Shusha profile)

---

### Part A: Binary Font Identification (FontTools)

1. **Standards-Aware Name Table Parsing**:
   - Replaces the 47-line manual SFNT binary unpacker in `detector.py:40-87`.
   - Uses `fontTools.ttLib.TTFont(BytesIO(font_bytes), lazy=True)`.
   - Calls `font['name'].getBestFamilyName()` and `getBestFullName()` to handle Windows Unicode (`platformID=3`), Macintosh Roman (`platformID=1`), and Latin-1 name records robustly without binary offset errors.
2. **GSUB Modern Font Guard**:
   - Checks `font.has_key('GSUB')` and probes script tags for `'deva'` or `'dev2'`.
   - If present, the font is conclusively classified as a **Modern Unicode Font** (e.g. Lohit, Noto Sans Devanagari, Mangal, Nirmala UI).
   - Guarantees **zero false-positive legacy conversion** on unknown or custom modern fonts.
3. **CMap Multi-Subtable Encoding Inspection**:
   - Inspects all subtables in `font['cmap'].tables` rather than calling `getBestCmap()` (which prioritizes modern Unicode).
   - Detects Windows Symbol subtables (`platformID=3, platEncID=0`) and Mac Roman subtables (`platformID=1, platEncID=0`), where byte codes `0x20–0xFF` map directly to Hindi glyph indices.
   - Generates deterministic `cmap_signature` (SHA-256 fingerprint of character-to-glyph code assignments).
4. **Anchor Glyph Outline Fingerprinting**:
   - Selects 16–24 discriminative anchor glyph positions (e.g., character codes for `d`, `[k`, `Fk`, `Hk`, `x`, `ñ`, `ò`, `ö`, `Ù`, `Ø`).
   - Uses `fontTools.pens.recordingPen.RecordingPen` to record vector contours and compute scale-invariant path hashes.
   - Detects renamed or obfuscated clones (e.g., government departments renaming `Kruti Dev 010` to `DeptHindi_Regular`).
5. **Build-Time Profile Auditor (`tools/audit_legacy_font.py`)**:
   - CLI utility validating `data/fonts/*.json` mapping profiles against canonical reference TTFs (`KrutiDev010.ttf`, `DevLys010.ttf`, `Chanakya.ttf`, `Shusha.ttf`, `Shivaji.ttf`).
   - Generates coverage reports: mapped character count, unmapped glyphs present in font, dead character mappings, and precomputed `cmap_signature`.

---

### Part B: Staged Transduction & Profile Audits (SIL NRSI Oracle)

1. **Critical Profile Audits & Corrections**:
   - **KrutiDev010 ASCII Digits Fix (P0)**:
     - *Issue*: `data/fonts/krutidev010.json` erroneously mapped `"0": "०"` .. `"9": "९"`, corrupting dates (`19/09/2026`), bank account numbers, monetary amounts, and legal sections (`Section 138`) into Devanagari numerals.
     - *Correction*: Align with SIL `KrutiDev010.map` (`ByteClass[OneToOneDigit]`): keep ASCII `48..57` (`0..9`) strictly as Latin digits, and map Alt-code bytes `131..140` to Devanagari numerals `१..९, ०`.
     - *Heuristic Guard*: Provide `preserve_ascii_digits: bool = True` in `AksharaConverter` with profile/document override for non-standard hacked fonts.
   - **Shusha Profile Reconstruction (P0)**:
     - *Issue*: `data/fonts/shusha010.json` contained a fatal reph deadlock (`"postfix_reph": "R"` vs `"R": "उ"` being consumed in Step 3 before Step 4) and an artificial alphabetical placeholder (`a: क, b: ख... 1: र, 2: ल...`).
     - *Correction*: Rebuild from SIL `Shusha.map`: consonant stem `a` (`VERTBAR`), ikar `i` (`105`), reph `-` (`45`), halant `\` (`92`), and nukta `,` (`44`), with authentic half-consonant and conjunct inventories.
   - **KrutiDev 010 vs 011 vs 290 Variant Separation (P1)**:
     - `krutidev010`: `SH_1/SH_2 = 147/148` (`श्`), `SHR_1/SHR_2 = 145/146` (`श्र्`).
     - `krutidev011`: Swaps `145/146` (`श्`) and `147/148` (`श्र्`). Decoding 011 with 010 mappings inverts these characters.
     - `krutidev290`: Nukta is byte `164` (not `43`), with distinct conjunct forms and half-letters.
     - Implemented as variant deltas inheriting from a common `krutidev_base.json`.

2. **7-Pass Pure-Python Staged Transduction Model**:
   ```
   Raw Legacy Text
         ↓
   Pass 1: Canonicalize Duplicate Presentation Glyphs (22 duplicate Kruti byte forms → canonical tokens)
         ↓
   Pass 2: Input Repair & Typist Artifacts (collapse duplicate nasals, typist reordering errors)
         ↓
   Pass 3: Context-Sensitive Rewrites (e.g. '%' after digit → ':', otherwise visarga 'ः')
         ↓
   Pass 4: Pre-Base Matra Reordering (reorder 'f' / 'i' across consonant clusters)
         ↓
   Pass 5: Longest-Match Forward Mapping (compiled regex transducer across multi/single-char mappings)
         ↓
   Pass 6: Postfix Reph Reordering (transpose 'Z' / '-' to syllable-initial Unicode 'र्')
         ↓
   Pass 7: Unicode NFC Normalization & Presentation Joiner Stripping
         ↓
   Canonical Clean Semantic Unicode Text
   ```

3. **Joiner Policy (Semantic Unicode vs Visual Round-Trip)**:
   - SIL maps generate `् + ZWJ` (U+200D) and `् + ZWNJ` (U+200C) to support visual half-forms for round-trip legacy conversion.
   - For Sarathi's search, extraction, and Indic translation pipeline, excess joiners fracture subword tokenization and NER.
   - **Sarathi Invariant**: Strip unsemantic presentation joiners in Pass 7, emitting clean Unicode NFC, while preserving ZWJ only where orthographically mandatory (e.g. eyelash Ra `र्‍`).

4. **Build-Time Differential Oracle (`tools/audit_sil_legacy_maps.py`)**:
   - **Zero Native Dependency**: Does **not** introduce the TECkit C/C++ runtime into Sarathi. Keeps Sarathi 100% pure Python.
   - **Offline Fixture Generation**: Parses human-readable SIL `.map` files into deterministic JSON test vectors under `tests/font_conversion/fixtures/sil/`.
   - **Permanent Regression Guard**: Automatically validates Sarathi's `AksharaConverter` against SIL's canonical input/output pairs.

5. **Declarative Pipeline Execution (Zero Family Branching)**:
   - Eliminates hardcoded family branches (`if profile.family in ("krutidev", "devlys"): ... elif profile.family == "chanakya": ...`) inside `converter.py`.
   - The 7 passes execute generically based on declarative profile fields (`prefixes`, `postfix_reph`, `context_rules`, `canonicalization_rules`, `post_corrections`), ensuring new font variants require zero converter code modifications.

6. **Conversion Telemetry & Unmapped Symbol Histogram**:
   - `FontConversionResult` and `ProvenanceRecord` capture runtime diagnostic metrics:
     - `mapped_chars_count`, `replacement_operations`, `reorder_operations`.
     - `unmapped_symbols_histogram`: Frequency dictionary of unmapped legacy characters (e.g. `{"å": 742, "™": 381}`). Immediately surfaces high-frequency missing glyphs from real production documents.

---

### Part C: Stream-Order Ingestion & Font-Run Arbitration (KrutiExtract Invariants)

1. **Logical Character Stream Preservation (P0 — Essential Pipeline Inversion)**:
   - **The Failure Mode**: In legacy typewriter fonts, characters appear in the PDF content stream in keystroke typing order (`v`, `k`, `S`, `j` for `vkSj` ➔ `और`). When spatial layout engines sort text spans geometrically by 2D bounding boxes, diacritics and top matras (with zero/negative horizontal advances or elevated bounding boxes) get misplaced: $\texttt{vkSj} \xrightarrow{\text{spatial sort}} \texttt{vkjS}$. Once jumbled, even a 100% perfect mapping table produces corrupted gibberish.
   - **Pipeline Inversion Invariant**: For any page where a legacy font is confirmed, convert the raw text stream to Unicode *before* applying spatial/geometry line reconstruction:
     $$\text{PDF Content Stream} \longrightarrow \text{Stream-Order Legacy Conversion} \longrightarrow \text{Unicode Text (NFC)} \longrightarrow \text{Layout / Line Reconstruction}$$
   - Guarantees that multi-character aksharas, pre-base matras (`ि`), and reph are converted while their phonetic keystroke sequence remains intact.

2. **Font-Run-Based Arbitration & Fail-Closed Protection (P0)**:
   - Evaluates `TextSpan.metadata["font_name"]` as the authoritative primary arbitrator, eliminating fragile text-level English/Hindi regex heuristics for ambiguous sequences (e.g. `thou`, `rail`, `case`):
     - **Modern Unicode Font** (e.g. `Mangal`, `Noto Sans Devanagari`, `Nirmala UI`) ➔ **PRESERVE** (zero conversion).
     - **Known Latin Font** (e.g. `Times New Roman`, `Calibri`, `Arial`) ➔ **PRESERVE** (zero conversion).
     - **Exact Supported Legacy Font** (e.g. `Kruti Dev 010`, `DevLys 010`, `Chanakya`) ➔ **CONVERT** with exact profile.
     - **Unsupported Legacy Font** (e.g. `Shivaji01`, `Akruti`, `Ajanta`) ➔ **PRESERVE + WARNING** (`UNSUPPORTED_LEGACY_FONT`). Enforces the strict invariant: **wrong conversion < no conversion**. Never guess a nearest profile.
     - **Unknown / Obfuscated Font** ➔ Fall back to `TextProtector` and detection signatures.

3. **MacRoman ➔ Windows-1252 Byte Stream Normalization (P0/P1)**:
   - **Root Cause**: Defective PDF generators embed 8-bit legacy Devanagari fonts under `/Encoding /MacRomanEncoding` rather than `/WinAnsiEncoding`. PyMuPDF decodes bytes `0x80..0xFF` into MacRoman Unicode representations (e.g. `⁄UÊ¡SÕÊŸ`), breaking both font detection and mapping tables.
   - **Normalizer (`src/sarathi/shakti/font_conversion/byte_normalizer.py`)**:
     - Detects diagnostic MacRoman signature characters (`⁄` U+2044, `◊` U+25CA, `‚` U+201A, `ﬂ` U+FB02, `ﬁ` U+FB01, `Ÿ` U+0178, `Ê` U+00CA).
     - Deterministically inverts the mapping: `text.encode("mac_roman").decode("cp1252", errors="replace")`.
     - Completely idempotent and zero-op for standard text streams.

4. **Glyph-Sheet Visual Audit Utility (`tools/glyph_sheet.py`)**:
   - Renders each source byte/codepoint alongside its rendered vector glyph crop from the actual PDF/font.
   - Enables human visual verification when auditing new or ambiguous legacy font encodings.

5. **Profile Fidelity & Round-Trip Auditor (`tools/audit_font_profile.py`)**:
   - Executes round-trip audits (`Legacy ➔ Unicode ➔ Legacy`) across all registered profiles.
   - Categorizes each mapping into:
     - `canonical` (exact 1:1 round-trip).
     - `intentional_alias` (many-to-one legacy glyph aliases mapping to the same Unicode sequence, backed by an explicit `reverse_preferred` target).
     - `unexpected_loss` (ambiguous or missing reverse target).
   - Enforces the invariant: every many-to-one mapping must define an explicit `reverse_preferred` target, preventing reverse export from silently mutating KrutiDev text.

6. **Mapping Candidate Miner from Aligned Pairs (`tools/mine_mapping_candidates.py`)**:
   - Mines new or missing legacy glyph mappings from dual-stream born-digital PDFs (raw legacy byte stream paired with verified Unicode OCR/reference text).
   - Uses weighted sequence alignment across Unicode akshara boundaries to extract `MappingCandidate(legacy, unicode, support, confidence)`.
   - Discovered candidates (such as the 109 KrutiDev candidates identified in AksharEngine) are audited against SIL and FontTools consensus before being committed to canonical profiles via `anubhava.toml`.

---

### Part D: Implementation Invariants & Phased Roadmap

1. **Lightweight Modular Architecture**:
   - All legacy font conversion and stream ingestion logic lives strictly within existing canonical owners:
     - Transduction pipeline: [`converter.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/converter.py) (`AksharaConverter`).
     - Binary font inspection: [`font_inspector.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/font_inspector.py).
     - Byte stream normalization: [`byte_normalizer.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/byte_normalizer.py).
     - Stream-order ingestion: [`readers/pdf.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/readers/pdf.py).
   - Total new codebase footprint is bounded to $<600$ lines of clean, maintainable Python without unnecessary wrappers or duplicate paths.

2. **File-Based Profile Inheritance**:
   - Profiles are defined as human-auditable, git-versioned JSON files under `data/fonts/`.
   - Supports lightweight inheritance via `"extends": "krutidev_base"`, enabling variant profiles (`krutidev011.json`, `krutidev290.json`) to declare only their specific delta overrides.
   - Loads in $<1\text{ ms}$ with zero database dependencies.

3. **Deterministic 4-Tier Arbitration Precedence**:
   - Resolves font conversion per span using a deterministic hierarchy:
     1. *Binary Font Inspection*: If embedded font contains `GSUB` Devanagari ➔ Modern Unicode (Preserve). If Symbol cmap ➔ Legacy Font.
     2. *Font Name Match*: Exact family match in `LegacyFontProfile` registry.
     3. *Unsupported Legacy Check*: Known legacy family with no mapping ➔ Preserve + emit `UNSUPPORTED_LEGACY_FONT` warning (**wrong conversion < no conversion**).
     4. *Fallback*: Only when font is unlabelled/obfuscated ➔ evaluate `TextProtector` and regex detection signatures.

4. **Devanagari Structural Invariant Validator**:
   - A fast regex invariant checker detecting illegal orphan combining marks (leading `ि` without consonant, duplicate virama) as a regression guard before final output.

5. **Difficult-Character Golden Regression Corpus**:
   - Permanent test suite in `tests/font_conversion/fixtures/` validating rare and complex ligatures:
     `कि`, `क्ति`, `क्र`, `त्र`, `प्र`, `श्र`, `क्ष`, `ज्ञ`, `द्ध`, `द्व`, `र्‍`, `र्कीं`, `ड़क`, `ढ़`, `फ़`, `क़`, `ज़`, `र्क`, `र्क्ष`.

6. **Phased Implementation Roadmap**:
   - **Phase 1 (Ingestion & Arbitration)**: Stream-order PDF extraction in `pdf.py`, font-run arbitration (`TextSpan.font_name`), and MacRoman byte normalizer.
   - **Phase 2 (Staged Decoder & Profile Audits)**: P0 ASCII digits fix in `krutidev010.json`, authentic Shusha reconstruction, and 7-pass transduction in `converter.py`.
   - **Phase 3 (Variant Deltas & FontTools Guard)**: Profile inheritance (`krutidev_base.json` + `011`/`290` deltas) and `font_inspector.py`.
   - **Phase 4 (Verification & Benchmarking Tools)**: SIL differential oracle fixtures, `tools/audit_font_profile.py`, `tools/mine_mapping_candidates.py`, `tools/glyph_sheet.py`, and `tools/benchmark_ocr_legacy_gold.py`.

### Fallback Policy
- `fonttools` is declared in `pyproject.toml` under optional dependencies `[font_conversion]` and `[dependency-groups] dev`.
- If `fonttools` is not installed or font bytes are absent (standard DOCX without embedded fonts), the system falls back safely to the canonical font-name normalization and textual regex signature detector in `detector.py`.

---

## 2. In-Place Multi-Part DOCX XML Transcoder

### Objective
Provide lossless legacy Hindi font transcoding for Word documents (`.docx`), preserving 100% of formatting, tables, images, margins, headers, footers, and footnotes.

### Canonical Ownership
- **Owner**: `sarathi.shakti.docx_exporter`
- **Module**: `src/sarathi/shakti/docx_exporter/transformer.py`
- **Capability Bridge**: `sarathi.shakti.font_conversion.capability`

### Technical Specification
1. **Multi-Part XML Container Traversal**:
   - Currently, `transformer.py` processes only `word/document.xml`.
   - The upgraded transformer scans the OpenXML zip archive for all document story parts matching:
     - `word/header[0-9]*.xml` (institutional headers like *"कार्यालय जिला कलक्टर"*)
     - `word/footer[0-9]*.xml` (page numbering, court case references)
     - `word/footnotes.xml` and `word/endnotes.xml` (statutory citations, annotations)
2. **Run-Level Transcoding & Font Substitution**:
   - Within each XML part, iterates all run elements (`<w:r>`).
   - Inspects `<w:rFonts>` attributes (`w:ascii`, `w:hAnsi`, `w:cs`).
   - When a legacy font (e.g. `Kruti Dev 010`, `DevLys 010`, `Chanakya`) is matched:
     - Transcodes inner `<w:t>` text to Unicode Devanagari using Sarathi's Akshara converter (`akshara.py`).
     - Replaces font attributes with neutral Unicode font specifications:
       `<w:rFonts w:ascii="Mangal" w:hAnsi="Mangal" w:cs="Mangal"/>` (or configured target font).
     - Dynamically applies font size normalization via `font_size_normalizer.py` (compensating for KrutiDev's oversized visual metrics).
3. **XML Serialization & Namespace Fidelity**:
   - Uses `_serialize_xml_preserving_namespaces()` to ensure all OpenXML schema declarations (`w`, `r`, `m`, `v`, `wp`, `w14`) remain strictly valid.

---

## 3. Vector Drawing PDF Table Extractor

### Objective
Reconstruct structured tables from vector-ruled PDF pages in sub-milliseconds without computer vision, rasterization, or neural models.

### Canonical Ownership
- **Owner**: `sarathi.shakti.native_extraction`
- **Module**: `src/sarathi/shakti/native_extraction/readers/pdf.py`

### Technical Specification
1. **Enhanced TableFinder Configuration**:
   - Configures PyMuPDF's `page.find_tables()` with precise parameters:
     - `vertical_strategy="lines"`, `horizontal_strategy="lines"`
     - `snap_tolerance=3.0`, `join_tolerance=3.0`
     - `min_words_vertical=1`
2. **Vector Stroke Fallback Clustering**:
   - For documents where `find_tables()` returns no tables but `page.get_drawings()` indicates significant vector stroke paths:
     - Filters paths by line width and collinearity.
     - Clusters intersecting horizontal and vertical vector lines into bounding rectangle grids.
     - Intersects native text spans with cell bounding boxes using interval trees.
3. **Structured Representation**:
   - Constructs canonical `TableData` dataclasses with detected headers, rows, and bounding box coordinates (`bounding_box=(x0, y0, x1, y1)`).
   - Injected into `PageData.tables` and promoted to `CanonicalDocument.tables`.

---

## 4. Banking Financial Integrity & UTR/IFSC Auto-Repair

### Objective
Transform Sarathi from a text extractor into a mathematically verified financial intelligence engine that detects and auto-repairs common OCR character confusions on critical banking identifiers.

### Canonical Ownership
- **Owner**: `sarathi.shakti.bank_statements`
- **New Module**: `src/sarathi/shakti/bank_statements/utr_repair.py`
- **Enhanced Module**: `src/sarathi/shakti/bank_statements/validator.py`

### Technical Specification
1. **UTR & IFSC Syntax Extraction**:
   - Extracts 16-character RTGS/NEFT references, 22-character UPI references, and 11-character IFSC codes from transaction narration strings.
   - Precompiled regexes matching RBI syntax standards:
     - IFSC: `\b[A-Z]{4}0[A-Z0-9]{6}\b`
     - UTR: `\b[A-Z]{4}[RNC][0-9]{8,17}\b`
2. **Deterministic OCR Confusion Repair**:
   - Enforces structural invariants:
     - **IFSC 5th Character**: Always `'0'` (repairs OCR `'O'` ➔ `'0'`).
     - **IFSC First 4 Characters**: Always letters (repairs `'0'` ➔ `'O'`, `'1'` ➔ `'I'`, `'8'` ➔ `'B'`).
     - **UTR Timestamp/Sequence Tokens**: Validates numeric continuity against transaction dates.
3. **Mathematical Balance Equation Verification**:
   - Enforces the invariant:
     $$\text{Opening Balance} + \sum \text{Credits} - \sum \text{Debits} = \text{Closing Balance}$$
   - When running balance continuity fails:
     - Identifies the specific row where $\Delta \text{Balance} \neq \text{Credit} - \text{Debit}$.
     - Checks whether single-digit OCR noise in amount fields (e.g. `.` vs `,`, missing decimal) reconciles the equation.
     - Emits `FINANCIAL_UTR_REPAIRED` and `FINANCIAL_BALANCE_MISMATCH` validation issues with row numbers and exact mismatch amounts.

---

## 5. Proper-Noun Transliteration Guard for Legal Translation

### Objective
Prevent neural translation models (IndicTrans2, OPUS-MT) from semantically mistranslating Indian personal names, kinship relations, villages, tehsils, and statutory titles.

### Canonical Ownership
- **Owner**: `sarathi.shakti.translation`
- **Module**: `src/sarathi/shakti/translation/protector.py` & `harmonizer.py`

### Technical Specification
1. **Honorific & Kinship Entity Detection**:
   - Identifies Devanagari proper names preceded by diagnostic legal/administrative prefixes:
     `(?:\b(?:श्री|श्रीमती|सुश्री|स्व\.|पुत्र|पुत्री|पत्नी|निवासी|मौजा|ग्राम|थाना|तहसील|जिला|पटवारी|तहसीलदार)\s+)([^\s,।\n]+(?:\s+[^\s,।\n]+)?)`
2. **Deterministic ISO 15919 / Administrative Phonetic Transliteration**:
   - Converts extracted Devanagari tokens into standardized Romanized text:
     - `रामगोपाल` ➔ `Ramgopal` (never *"Ram, protector of cows"*)
     - `मोहनलाल` ➔ `Mohanlal`
     - `बानसूर` ➔ `Bansur`
     - `अलवर` ➔ `Alwar`
3. **SentencePiece Placeholder Isolation**:
   - Replaces the proper noun with a SentencePiece-safe numeric placeholder (`999xxxx`) before feeding to IndicTrans2.
   - During post-translation reconstruction, swaps the placeholder with the phonetically transliterated English name.
   - Preserves legal and revenue integrity without requiring external named-entity recognition (NER) models.

---

## 6. High-Throughput Pipeline Parallelism (Stage Overlap)

### Objective
Maximize hardware utilization across the **Intel Core Ultra 5 125H CPU** and **Intel Arc iGPU** simultaneously during multi-stage document execution (such as OCR ➔ Translation).

### Canonical Ownership
- **Owner**: `sarathi.nabhi.pravaha` / `sarathi.yantra`
- **Module**: `src/sarathi/nabhi/pravaha/pipeline.py`

### Technical Specification
1. **Current Sequential Bottleneck**:
   - Currently, a multi-stage request (OCR ➔ Translation on 5 documents) executes as:
     $$\text{All Docs OCR on iGPU (CPU idle)} \longrightarrow \text{All Docs Translation on CPU (iGPU idle)}$$
2. **Pipelined Document Handoff**:
   - When Document $i$ completes Stage 1 on the Arc iGPU, it is immediately placed onto an asynchronous handoff queue for Stage 2.
   - Stage 2 worker pool on CPU P-cores begins CTranslate2 neural translation of Document $i$.
   - Simultaneously, Stage 1 worker on the Arc iGPU begins OCR inference on Document $i+1$.
3. **Hardware Synergy**:
   - **Arc iGPU**: 100% busy running OpenVINO FP16 OCR.
   - **Core Ultra CPU**: 100% busy running CTranslate2 AVX2 multi-core batch translation.
   - Delivers up to **40–50% reduction in total job completion time** for multi-document batches.

---

## 7. Self-Grounded OCR Ground-Truth Benchmark & Hardware Tuning

### Objective
Provide an autonomous, empirical OCR benchmarking engine that generates **100% mathematically exact Unicode ground truth** from born-digital legacy PDFs without human transcription, enabling quantitative hyperparameter, resolution, and preprocessing tuning for RapidOCR / OpenVINO on the **Intel Arc iGPU** and **Core Ultra 5 125H CPU**.

### Canonical Ownership
- **Owner**: `sarathi.shakti.ocr` & `sarathi.yantra`
- **Tool**: `tools/benchmark_ocr_legacy_gold.py`
- **Consumer**: `sarathi.shakti.ocr.engine` & adaptive rerasterization policies

### Technical Specification
1. **Self-Grounded Gold Truth Generation**:
   - Born-digital legacy PDFs (e.g. state gazettes, court judgments, circulars typed in KrutiDev/DevLys) contain both clean vector/raster glyphs and native keystroke bytes.
   - **Step 1 (Ground Truth)**: Extracts native legacy text and converts via `AksharaConverter` ➔ **100% exact reference Unicode text (GOLD TRUTH)**.
   - **Step 2 (Rasterization)**: Renders the identical PDF page/region using `BoundedPageRasterizer` across resolution ladders ($150, 200, 250, 300, 350, 400$ DPI).
   - **Step 3 (Neural Inference)**: Executes RapidOCR with OpenVINO FP16 on the **Intel Arc iGPU**.
   - **Step 4 (Evaluation)**: Normalizes both texts (Unicode NFC, whitespace) and computes Character Error Rate (CER) and Word Error Rate (WER) via Levenshtein edit distance.
2. **Empirical Resolution & Preprocessing Sweeps**:
   - Evaluates DPI settings across clean documents, simulated photocopy degradation, and complex small-font tables.
   - Benchmarks image preprocessing operators (CLAHE, bilateral filter, adaptive thresholding, deskew, unsharp mask) against unadulterated renders.
   - Quantifies the hardware Pareto frontier:
     $$\text{Pareto Metric} = \frac{\text{Accuracy (1 - CER)}}{\text{Latency (ms)} \times \text{Peak VRAM (MB)}}$$
3. **Adaptive Rerasterization Threshold Calibration**:
   - Provides empirical data to settle the adaptive rerasterization policy:
     - Measures whether $200$ DPI solves $\ge 85\%$ of production pages.
     - Calibrates the exact OCR confidence cutoff that triggers selective $300$ DPI rerasterization, preventing expensive global high-DPI execution.

---

## Verification & Acceptance Criteria

Every capability will be validated through dedicated unit and integration tests complying with the compound pre-commit fast gate:

```powershell
uv run python -m compileall -q src tests tools; uv run ruff check .; git diff --check
```

### Scoped Test Execution Matrix

| Capability | Scoped Test Command | Success Invariants |
| :--- | :--- | :--- |
| **FontTools & Inspector** | `uv run --group dev pytest tests/font_conversion/test_font_inspector.py -q` | Correct family extraction from TTF bytes; GSUB modern font classification; symbol cmap detection. |
| **SIL Differential Oracle** | `uv run --group dev pytest tests/font_conversion/test_sil_differential.py -q` | 100% agreement on KrutiDev 010/011/290 and Shusha test vectors; correct Latin digit preservation. |
| **Profile Fidelity & Audit** | `uv run python tools/audit_font_profile.py --all-profiles` | Verify 100% round-trip fidelity, detect ambiguous reverse targets, ensure explicit reverse_preferred. |
| **Legacy Stream Extraction** | `uv run --group dev pytest tests/native_extraction/test_pdf_legacy_stream.py -q` | Stream-order conversion preserves keystroke sequence; zero geometric matra jumbling. |
| **DOCX Transcoding** | `uv run --group dev pytest tests/font_conversion/test_docx_multipart.py -q` | Headers, footers, footnotes, and body converted to Unicode; all OpenXML styles and namespaces preserved. |
| **Vector PDF Tables** | `uv run --group dev pytest tests/native_extraction/test_pdf_vector_tables.py -q` | Extract ruled tables with exact bounding boxes and cell contents without OCR. |
| **Banking Integrity** | `uv run --group dev pytest tests/bank_statements/test_utr_repair.py -q` | Detect and repair corrupted UTR/IFSC codes; flag debit/credit balance mismatches with exact row references. |
| **Proper-Noun Guard** | `uv run --group dev pytest tests/translation/test_proper_noun_guard.py -q` | Honorific/kinship names transliterated phonetically; zero semantic mistranslations in IndicTrans2 output. |
| **Pipeline Overlap** | `uv run --group dev pytest tests/nabhi/test_pipeline_overlap.py -q` | Document N translates on CPU concurrently while Document N+1 performs OCR on iGPU. |
| **Self-Grounded OCR Benchmark** | `uv run python tools/benchmark_ocr_legacy_gold.py --dry-run` | Automated gold truth extraction from legacy PDF; CER/WER evaluation on Arc iGPU. |
| **Architecture Gate** | `uv run --group dev pytest -q -m architecture` | Instant verification that code topology and manifest remain 100% synchronized. |
