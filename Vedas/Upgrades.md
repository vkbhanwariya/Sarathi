# Upgrades — High-ROI Architectural Capabilities Specification

This document serves as the authoritative technical specification and design reference for the **7 High-ROI Architectural Capabilities** planned for Sarathi. Each specification defines the problem, architectural owner, technical design, contracts, hardware synergy, and verification criteria.

---

## Roadmap Overview

| # | Capability | Canonical Owner | Primary Target | Expected ROI |
| :- | :--- | :--- | :--- | :--- |
| **1** | **Legacy Font Identification & Staged Transduction (FontTools + SIL NRSI + KrutiExtract + Visual Fallback)** | `shakti.font_conversion` & `native_extraction` | PDF embedded fonts & legacy Devanagari text | 100% binary font identity + stream-order extraction + 7-pass staged decoding + OpenVINO metric visual fallback with open-set rejection. |
| **2** | **In-Place Multi-Part DOCX Transcoder** | `shakti.docx_exporter` | `.docx` documents with legacy fonts | Transcodes headers, footers, footnotes, and tables in-place with zero formatting loss. |
| **3** | **Vector Drawing PDF Table Extractor** | `shakti.native_extraction` | Native vector-ruled PDFs (statements, gazettes) | Sub-millisecond table boundary reconstruction directly from vector strokes without neural models. |
| **4** | **Banking Integrity & UTR/IFSC Auto-Repair** | `shakti.bank_statements` | Scanned & native financial statements | Mathematical double-entry balance verification and deterministic OCR confusion repair (`0`↔`O`, `1`↔`I`). |
| **5** | **Proper-Noun Legal Transliteration Guard** | `shakti.translation` | Administrative, court, and revenue records | Rule-based phonetic transliteration protecting Indian names/villages from semantic NMT mistranslation. |
| **6** | **High-Throughput Stage Pipeline Overlap** | `nabhi.pravaha` / `yantra` | Multi-document and multi-stage jobs | Overlaps Intel Arc iGPU (OCR) and Core Ultra CPU (Translation) for up to 2× batch throughput. |
| **7** | **Self-Grounded OCR Benchmark & Hardware Tuning** | `tools` / `shakti.ocr` | Born-digital legacy PDFs & RapidOCR/OpenVINO | Automated ground-truth generation without human transcription; empirical Pareto tuning for Arc iGPU. |

---

## 1. Legacy Font Identification & Staged Transduction (FontTools, SIL NRSI, KrutiExtract & OpenVINO Metric Fallback)

### Objective
Pair **authoritative binary font identification** (FontTools) with **stream-order native extraction** (KrutiExtract), **7-pass staged Devanagari decoding** (SIL NRSI), and **visual metric prototype retrieval** (OpenVINO), preventing visual geometry scrambled keystrokes (`vkSj` ➔ `vkjS`), resolving obfuscated PDF font subsets (`ABCDEF+F1`), replacing flat dictionary replacements with a staged pure-Python transduction pipeline, and resolving critical profile bugs in KrutiDev and Shusha.

### Canonical Ownership
- **Owner**: `sarathi.shakti.font_conversion` & `sarathi.shakti.native_extraction`
- **Modules**:
  - `src/sarathi/shakti/font_conversion/font_inspector.py` (Binary font identification & GSUB guard)
  - `src/sarathi/shakti/font_conversion/converter.py` (Declarative 7-pass `AksharaConverter` execution pipeline)
  - `src/sarathi/shakti/font_conversion/profiles.py` (Extended `LegacyFontProfile` schema & inheritance)
  - `src/sarathi/shakti/font_conversion/byte_normalizer.py` (MacRoman ➔ Windows-1252 byte stream repair)
  - `src/sarathi/shakti/font_conversion/visual_resolver.py` (OpenVINO visual font fallback & metric prototype retrieval)
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
  - `data/fonts/legacy_prototypes.bin` (Precomputed unit-normalized prototype vectors for 15–20 legacy Indic font families)

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
   - Staged into `anubhava.toml` for human verification before promotion into canonical profiles.

7. **Multi-Source Consensus Triangulation & Candidate Auditing**:
   - Evaluates mined mapping candidates and external datasets across independent reference sources:
     $$\text{Consensus Target} = \text{Mode}(\text{SIL TECkit}, \text{Sarathi}, \text{AksharEngine}, \text{KrutiExtract}, \text{FontTools TTF Outlines})$$
   - Audits the 109 KrutiDev mapping candidates absent from Sarathi and resolves the 24 conflicting definitions (e.g. `ñ`, `…`, `‰`, `—`, `é`, `«`, `|`, `æ`, `ô`, `T`, `÷`, `ê`, `ë`, `è`, `Í`, `‚`, `·`, `\`, `+`, `&`) using vector glyph outline matching before promotion.
   - Safely incorporates missing conjuncts (`ट्ट`, `ट्ठ`, `ड्ड`, `ड्ढ`, `छ्य`, `ट्य`, `ठ्य`, `ड्य`, `ढ्य`, `ट्र`, `ड्र`) and nukta consonants (`क़`, `ख़`, `ग़`, `ज़`, `ड़`, `ढ़`, `फ़`, `ऩ`, `ऱ`).

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

3. **Deterministic 5-Tier Arbitration Precedence**:
   - Resolves font conversion per span using a deterministic hierarchy:
     1. *Binary Font Inspection (FontTools)*: If embedded font contains `GSUB` Devanagari ➔ Modern Unicode (Preserve). If Symbol/MacRoman cmap ➔ Legacy Font. Anchor glyph outline hash match.
     2. *Font Name Match*: Exact family match in `LegacyFontProfile` registry.
     3. *Unsupported Legacy Check*: Known legacy family with no mapping ➔ Preserve + emit `UNSUPPORTED_LEGACY_FONT` warning (**wrong conversion < no conversion**).
     4. *Visual Font Fallback (OpenVINO Metric Prototype Retrieval)*: When embedded font bytes are missing, corrupted, or obfuscated (e.g. `/ABCDEF+F1`), render 3–5 representative text-line crops, extract embeddings via OpenVINO FP16, and perform cosine distance prototype matching against the 15-family catalog with per-family calibrated threshold $\tau_f$ and open-set rejection (`is_unknown = True` ➔ preserve raw bytes).
     5. *Statistical Fallback*: Only when visual resolver is unavailable or disabled ➔ evaluate `TextProtector` and regex detection signatures.

4. **Devanagari Structural Invariant Validator**:
   - A fast regex invariant checker detecting illegal orphan combining marks (leading `ि` without consonant, duplicate virama) as a regression guard before final output.

5. **Difficult-Character Golden Regression Corpus**:
   - Permanent test suite in `tests/font_conversion/fixtures/` validating rare and complex ligatures:
     `कि`, `क्ति`, `क्र`, `त्र`, `प्र`, `श्र`, `क्ष`, `ज्ञ`, `द्ध`, `द्व`, `र्‍`, `र्कीं`, `ड़क`, `ढ़`, `फ़`, `क़`, `ज़`, `र्क`, `र्क्ष`.

6. **Phased Implementation Roadmap**:
   - **Phase 1 (Ingestion & Arbitration)**: Stream-order PDF extraction in `pdf.py`, font-run arbitration (`TextSpan.font_name`), and MacRoman byte normalizer.
   - **Phase 2 (Declarative Decoder & Profile Audits)**: P0 ASCII digits fix in `krutidev010.json`, authentic Shusha reconstruction, declarative 7-pass transduction in `converter.py`, and unmapped symbol histogram telemetry.
   - **Phase 3 (Variant Deltas & Reverse Fidelity)**: Profile inheritance (`krutidev_base.json` + `011`/`290` deltas), explicit `reverse_preferred` schema enforcement, and `font_inspector.py`.
   - **Phase 4 (Visual Metric Retrieval & Verification)**: OpenVINO FP16 visual font fallback (`visual_resolver.py`) with open-set rejection, SIL differential oracle fixtures, `tools/audit_font_profile.py`, `tools/mine_mapping_candidates.py`, `tools/glyph_sheet.py`, and `tools/benchmark_ocr_legacy_gold.py`.

### Fallback Policy
- `fonttools` is declared in `pyproject.toml` under optional dependencies `[font_conversion]` and `[dependency-groups] dev`.
- If `fonttools` is not installed or font bytes are absent (standard DOCX without embedded fonts), the system falls back safely to visual prototype retrieval or canonical font-name normalization and textual regex signature detection in `detector.py`.

---

### Part E: Visual Font Identification Fallback & Metric Retrieval (OpenVINO)

1. **The Obfuscated Font Problem**:
   - In government gazettes and court records, PDF generators frequently subset fonts under randomized pseudonyms (e.g. `/ABCDEF+F1`, `/TT0`) and strip TrueType `name` and `cmap` tables.
   - The logical keystrokes remain intact (e.g. `dksVZ esa`), but binary font inspection yields zero family information.
   - Visual inspection of the rendered glyph shapes provides the conclusive missing evidence channel.

2. **Metric Prototype Retrieval (Zero-Retraining Extensibility)**:
   - Uses a compact ConvNeXt-Tiny visual feature backbone exported to OpenVINO FP16 for the **Intel Arc iGPU** (via `yantra.devices`), completely eliminating PyTorch and Timm runtime dependencies.
   - Maintains a lightweight binary index (`data/fonts/legacy_prototypes.bin`, $<500\text{ KB}$) containing precomputed, unit-normalized $D$-dimensional prototype vectors representing 15–20 canonical legacy Indic families (`Kruti Dev 010`, `011`, `290`, `DevLys 010`, `100`, `Chanakya`, `Walkman-Chanakya`, `Shusha`, `Shivaji`, `APS`, `Shree-Lipi`).
   - Adding a new legacy font variant requires zero neural retraining: render reference glyph crops from the font, extract backbone embeddings, compute the centroid prototype vector, and append to the index.

3. **Open-Set Rejection & Calibrated Per-Family Thresholds**:
   - Standard neural classifiers are closed-set: they force any unknown font into the nearest seen class (e.g. classifying an unmapped regional font as `KrutiDev010`), corrupting text into plausible-looking gibberish.
   - Sarathi computes cosine similarity against enrolled prototypes:
     $$s_f = \cos(\mathbf{e}_{\text{crop}}, \mathbf{p}_f) = \frac{\mathbf{e}_{\text{crop}} \cdot \mathbf{p}_f}{\|\mathbf{e}_{\text{crop}}\| \|\mathbf{p}_f\|}$$
   - Evaluates similarity against per-family calibrated thresholds $\tau_f$ derived from real degraded document crops (e.g. $\tau_{\text{Kruti010}} = 0.73, \tau_{\text{DevLys010}} = 0.71$).
   - If $\max_f (s_f) < \tau_f$, the resolver returns `VisualFontEvidence(is_unknown=True, candidates=[])`, triggering fail-safe preservation (`UNSUPPORTED_LEGACY_FONT`).

4. **Patch Voting & Bounded Document Caching**:
   - Never rasterizes entire pages for font identification. Extracts 3–5 representative text-line crops corresponding to the target font `xref`.
   - Averages patch embeddings: $\mathbf{e}_{\text{font}} = \frac{1}{K} \sum_{k=1}^K \mathbf{e}_k$.
   - Caches the decision by `(doc_id, font_xref, crop_phash)`: a 100-page document incurs exactly 1 visual inference pass per unique font.

5. **Evidence Fusion Invariants**:
   - Visual font identification operates strictly as an evidence channel (`VisualFontEvidence`), not an autonomous profile selector.
   - When visual classification indicates close variants (e.g. `Kruti Dev 010` vs `DevLys 010`), text-signature confirmation is evaluated before committing to a profile.
   - Scanned raster PDFs never route through visual font conversion (raster images flow directly to RapidOCR Unicode inference).

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
4. **Glyph Line-Height Content-Adaptive DPI Calculation**:
   - Fixed-DPI rerasterization (e.g. globally rerendering at 300 or 400 DPI) wastes memory and GPU cycles.
   - 2D pixel interpolation (e.g. upscaling a 200 DPI crop by 400%) smooths pixel edges without restoring missing stroke topology, leading to high-confidence OCR hallucination when source glyph height $h_{\text{median}} < 18\text{ px}$.
   - **Adaptive DPI Formula**:
     - During initial fast 200 DPI page scan, measure the median character line height $h_{\text{median}}$ across low-confidence bounding boxes ($\text{confidence} < 0.85$).
     - Calculate target DPI to normalize Devanagari glyphs to the optimal OCR recognition height ($32\text{ px}$):
       $$\text{Target DPI} = \min\left(400, \text{round}\left(200 \times \frac{32}{h_{\text{median}}}\right)\right)$$
     - Rerasterize the specific bounding box directly from the underlying vector PDF at the computed Target DPI using `BoundedPageRasterizer`, preserving sharp stroke topology without global page overhead.

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
| **Visual Font Resolver** | `uv run --group dev pytest tests/font_conversion/test_visual_resolver.py -q` | Open-set rejection on unknown fonts; calibrated threshold evaluation; exact prototype cosine retrieval. |
| **Legacy Stream Extraction** | `uv run --group dev pytest tests/native_extraction/test_pdf_legacy_stream.py -q` | Stream-order conversion preserves keystroke sequence; zero geometric matra jumbling. |
| **DOCX Transcoding** | `uv run --group dev pytest tests/font_conversion/test_docx_multipart.py -q` | Headers, footers, footnotes, and body converted to Unicode; all OpenXML styles and namespaces preserved. |
| **Vector PDF Tables** | `uv run --group dev pytest tests/native_extraction/test_pdf_vector_tables.py -q` | Extract ruled tables with exact bounding boxes and cell contents without OCR. |
| **Banking Integrity** | `uv run --group dev pytest tests/bank_statements/test_utr_repair.py -q` | Detect and repair corrupted UTR/IFSC codes; flag debit/credit balance mismatches with exact row references. |
| **Proper-Noun Guard** | `uv run --group dev pytest tests/translation/test_proper_noun_guard.py -q` | Honorific/kinship names transliterated phonetically; zero semantic mistranslations in IndicTrans2 output. |
| **Pipeline Overlap** | `uv run --group dev pytest tests/nabhi/test_pipeline_overlap.py -q` | Document N translates on CPU concurrently while Document N+1 performs OCR on iGPU. |
| **Self-Grounded OCR Benchmark** | `uv run python tools/benchmark_ocr_legacy_gold.py --dry-run` | Automated gold truth extraction from legacy PDF; CER/WER evaluation on Arc iGPU; glyph height adaptive DPI calculation. |
| **Architecture Gate** | `uv run --group dev pytest -q -m architecture` | Instant verification that code topology and manifest remain 100% synchronized. |
