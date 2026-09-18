# Upgrades — High-ROI Architectural Capabilities Specification

This document serves as the authoritative technical specification and design reference for the **6 High-ROI Architectural Capabilities** planned for Sarathi. Each specification defines the problem, architectural owner, technical design, contracts, hardware synergy, and verification criteria.

---

## Roadmap Overview

| # | Capability | Canonical Owner | Primary Target | Expected ROI |
| :- | :--- | :--- | :--- | :--- |
| **1** | **FontTools Integration & Font Inspector** | `shakti.font_conversion` | PDF embedded fonts & build-time profiles | 100% binary-level font identity, eliminates manual SFNT parser, modern font protection. |
| **2** | **In-Place Multi-Part DOCX Transcoder** | `shakti.docx_exporter` | `.docx` documents with legacy fonts | Transcodes headers, footers, footnotes, and tables in-place with zero formatting loss. |
| **3** | **Vector Drawing PDF Table Extractor** | `shakti.native_extraction` | Native vector-ruled PDFs (statements, gazettes) | Sub-millisecond table boundary reconstruction directly from vector strokes without neural models. |
| **4** | **Banking Integrity & UTR/IFSC Auto-Repair** | `shakti.bank_statements` | Scanned & native financial statements | Mathematical double-entry balance verification and deterministic OCR confusion repair (`0`↔`O`, `1`↔`I`). |
| **5** | **Proper-Noun Legal Transliteration Guard** | `shakti.translation` | Administrative, court, and revenue records | Rule-based phonetic transliteration protecting Indian names/villages from semantic NMT mistranslation. |
| **6** | **High-Throughput Stage Pipeline Overlap** | `nabhi.pravaha` / `yantra` | Multi-document and multi-stage jobs | Overlaps Intel Arc iGPU (OCR) and Core Ultra CPU (Translation) for up to 2× batch throughput. |

---

## 1. FontTools Integration & Font Inspector

### Objective
Elevate legacy Indian font conversion from heuristic symptom recognition (name string normalization and text regex matching) to **authoritative binary font identification** whenever embedded font streams exist in document containers (such as PDFs).

### Canonical Ownership
- **Owner**: `sarathi.shakti.font_conversion`
- **New Module**: `src/sarathi/shakti/font_conversion/font_inspector.py`
- **Developer Tool**: `tools/audit_legacy_font.py`
- **Consumer**: `sarathi.shakti.native_extraction.readers.pdf` (`_resolve_pdf_font_names`)

### Technical Specification
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

## Verification & Acceptance Criteria

Every capability will be validated through dedicated unit and integration tests complying with the compound pre-commit fast gate:

```powershell
uv run python -m compileall -q src tests tools; uv run ruff check .; git diff --check
```

### Scoped Test Execution Matrix

| Capability | Scoped Test Command | Success Invariants |
| :--- | :--- | :--- |
| **FontTools & Inspector** | `uv run --group dev pytest tests/font_conversion/test_font_inspector.py -q` | Correct family extraction from TTF bytes; GSUB modern font classification; symbol cmap detection. |
| **DOCX Transcoding** | `uv run --group dev pytest tests/font_conversion/test_docx_multipart.py -q` | Headers, footers, footnotes, and body converted to Unicode; all OpenXML styles and namespaces preserved. |
| **Vector PDF Tables** | `uv run --group dev pytest tests/native_extraction/test_pdf_vector_tables.py -q` | Extract ruled tables with exact bounding boxes and cell contents without OCR. |
| **Banking Integrity** | `uv run --group dev pytest tests/bank_statements/test_utr_repair.py -q` | Detect and repair corrupted UTR/IFSC codes; flag debit/credit balance mismatches with exact row references. |
| **Proper-Noun Guard** | `uv run --group dev pytest tests/translation/test_proper_noun_guard.py -q` | Honorific/kinship names transliterated phonetically; zero semantic mistranslations in IndicTrans2 output. |
| **Pipeline Overlap** | `uv run --group dev pytest tests/nabhi/test_pipeline_overlap.py -q` | Document N translates on CPU concurrently while Document N+1 performs OCR on iGPU. |
| **Architecture Gate** | `uv run --group dev pytest -q -m architecture` | Instant verification that code topology and manifest remain 100% synchronized. |
