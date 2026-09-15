# Engineering Roadmap — OCR, Layout Preservation & Native Extraction Pipeline

This document captures the verified high-value findings, architectural improvements, and execution plan for Sarathi's OCR, layout reconstruction, DOCX export, and native extraction engines.

---

## Priority Ledger

| Priority | Subsystem / Area | Current State & Root Cause | Target Solution | Primary Impact |
| :--- | :--- | :--- | :--- | :--- |
| **P0** | **OCR Device Routing** | In `coordinator.py`, cache stores both `f"{engine_key}:{device}"` and generic `engine_key`. A subsequent CPU request hits the generic GPU alias. | Key cache strictly by `(engine_key, target_device)` with zero device-independent alias. | **Hardware execution correctness** across mixed-device runs. |
| **P0/P1** | **OpenVINO Inference Concurrency** | Page tasks dispatch in parallel via Yantra, but all inference calls serialize behind a single `_infer_lock` due to shared `InferRequest`. | Allocate `InferRequest` per worker or use OpenVINO's `AsyncInferQueue` sized to approved concurrency; switch GPU hint to `THROUGHPUT`. | **Throughput scaling** on multi-page documents (unlocks 4 GPU / 2 NPU streams). |
| **P1** | **Heading & Font-Size Propagation** | `layout.py` detects headings (`curr.max_h >= 1.35 * median_h`) only for break decisions and discards them; `ocr/typography.py`'s `infer_line_font_size` is uncalled; `docx_exporter` only consumes literal markdown prefixes (`# `). | Propagate heading levels and font sizes via `TextSpan.metadata` or paragraph models into `docx_exporter/builder.py`. | **Visual hierarchy preservation** in generated DOCX deliverables. |
| **P1** | **Provenance & Telemetry Accuracy** | Telemetry and UI label weak-crop retries as `"ne_ocr"` / `"NE-OCR"`, even though NE-OCR was decommissioned in favor of same-engine RapidOCR retry. | Accurately record `fallback_engine: "same_engine_retry"` and display "Same-Engine Retry" across telemetry and UI. | **Factual provenance and audit transparency**. |
| **P1** | **PDF OCR Rasterization** | `extract_single_page_image` in `rasterize.py` re-opens and parses the entire PDF byte stream from scratch per page under `_PYMUPDF_LOCK`. | Open PDF once in a raster producer; stream rendered pages into a bounded queue (4–8 pages). | **Major reduction in wall-clock time and memory churn** on multi-page PDFs. |
| **P1** | **Weak-Crop Batching** | `coordinator.py` re-invokes the recognizer sequentially one-by-one per weak crop inside `_infer_lock`. | Collate weak crops per page and call `engine(crops_batch, use_det=False, use_cls=False)` in a single batched inference call. | **High GPU/CPU utilization & lower latency** on dense scanned pages. |
| **P1** | **Final Confidence Truth** | Page confidence is calculated from original recognition output before retry substitutions. | Recompute page-level mean confidence and pramana records from the final accepted spans. | **Factual, verifiable confidence metrics** for downstream audit. |
| **P1** | **Readiness Check Cache** | `check_ocr_readiness` in `readiness.py` calls `verify_ocr_manifest_and_models` without a cache, re-hashing all model files on every readiness check. | Memoize model verification using an in-memory mtime/size cache. | **Eliminates repeated SHA-256 disk I/O** on UI health polls. |
| **P1** | **Native PDF TextPage Reuse** | `read_pdf` in `readers/pdf.py` calls `page.get_text()` separately for `"blocks"`, `"text"`, and `"dict"`. | Construct PyMuPDF `TextPage` once per page; extract all representations from it. | **50–80% faster native PDF ingestion**. |
| **P1** | **Native Table Headers** | `readers/pdf.py` blindly promotes `extracted_rows[0]` to table headers. | Use PyMuPDF's `tab.header.names` and `tab.header.external` properties. | **Table fidelity** for statements with external titles. |
| **P1** | **DOCX Nested Run Walker** | `readers/docx.py` only inspects direct child `<w:r>` tags, missing text in hyperlinks/fields. | Recursively traverse visible run containers (`<w:hyperlink>`, `<w:fldSimple>`, `<w:sdt>`). | **Extraction completeness** for real-world legal and office documents. |
| **P1** | **Native vs. OCR Arbitration** | PDF pages with any text are treated as usable, ignoring large full-page scanned background images. | Compute page image bounding-box coverage vs. text density to trigger OCR on scanned pages with watermarks/page numbers. | **Prevents silent loss of scanned content** in hybrid PDFs. |
| **P2** | **Alphanumeric Filter Bullet Preservation** | `_ALPHANUMERIC_FILTER_RE` in `parser.py` strips `•`, `–`, `—` before `layout.py`'s `_LIST_BULLET_RE` can run. | Whitelist structural punctuation (`•`, `–`, `—`, typographic quotes) in `_ALPHANUMERIC_FILTER_RE`. | **Preserves list detection and bullet formatting** under `english_numbers_only`. |
| **P2** | **OCR Line Spacing (Metric-Aware)** | `layout.py`'s `group_paragraphs` joins spans on the same line with unconditional `" ".join(...)`. | Use font-metric gap-aware joining (`reconstruct_line_from_spans` in `text/typography.py`). | **Prevents broken words and conjunct clusters** (`"C orporation"`). |
| **P2** | **Table Spanning Cells & Ragged Rows** | `_cluster_spans_into_grid` in `layout.py` forces every span into its nearest single column anchor, misaligning merged cells. | Detect column-spanning cells and emit a `WarningRecord` when row cell count deviates sharply from header count. | **Prevents silent column misalignment** in financial statements. |
| **P2** | **Adaptive DPI Selection** | Fixed 150 DPI across all document profiles and scan qualities. | Allow 200–300 DPI for `ACCURATE` / `LAYOUT_PRESERVING` or adaptive DPI on weak-crop retries. | **Higher character resolution** for small fonts, footnotes, and statutory stamps. |
| **P2** | **HTML Mixed Content** | `readers/html.py` discards body narrative text whenever a table is found. | Preserve both document narrative text in `PageData` and structured tables in `TableData`. | **Eliminates text loss** in HTML reports and notices. |
| **P2** | **Multi-Column DOCX Layout** | Multi-column layouts linearized by XY-cut collapse into single-column text in DOCX. | Emit `<w:cols w:num="2"/>` and paragraph indentation `<w:ind w:left=...>` when `LAYOUT_PRESERVING` is active. | **Faithful visual representation** of two-column documents. |

---

## Phased Implementation Sequence

### Phase 1: Zero-Risk Correctness & Provenance Truth
1. **Engine Cache Device Isolation** (`src/sarathi/shakti/ocr/engine/coordinator.py`):
   - Replace dual keying with strict `(engine_key, target_device)` dictionary.
2. **Provenance & Telemetry Mislabling Fix** (`src/sarathi/shakti/ocr/telemetry.py` & `src/sarathi/mukha/presenter.py`):
   - Update fallback labels to `"same_engine_retry"` / `"Same-Engine Retry"`.
3. **Alphanumeric Bullet Preservation** (`src/sarathi/shakti/ocr/engine/parser.py`):
   - Allow `•`, `–`, `—`, quotes in `_ALPHANUMERIC_FILTER_RE`.
4. **Post-Retry Confidence Recomputation** (`coordinator.py`):
   - Recalculate mean page confidence and pramana records from post-retry span list.
5. **Readiness Check Caching** (`src/sarathi/shakti/ocr/engine/readiness.py`):
   - Memoize SHA-256 verification results across calls.
6. **DOCX Inline Content Extraction** (`src/sarathi/shakti/native_extraction/readers/docx.py`):
   - Implement unified run walker covering `<w:r>`, `<w:hyperlink>`, `<w:fldSimple>`, and `<w:sdt>`.
7. **HTML Narrative + Table Preservation** (`src/sarathi/shakti/native_extraction/readers/html.py`):
   - Populate `PageData` with narrative text even when `TableData` is discovered.

### Phase 2: Layout Preservation & Native Extraction Speed
1. **Heading & Typography Continuity to DOCX** (`layout.py`, `ocr/typography.py`, `docx_exporter/builder.py`):
   - Wire `infer_line_font_size` and `is_heading` geometry into span/paragraph metadata or markdown headings consumed by `builder.py`.
2. **Metric-Aware Line Joining for OCR** (`layout.py`):
   - Replace naive space join with `reconstruct_line_from_spans`.
3. **PyMuPDF TextPage Reuse** (`src/sarathi/shakti/native_extraction/readers/pdf.py`):
   - Instantiate `page.get_textpage()` once per page.
4. **Native PDF Table Headers** (`readers/pdf.py`):
   - Integrate `tab.header.names` and `tab.header.external`.

### Phase 3: Throughput & Pipeline Batching
1. **Producer-Consumer Raster Pipeline** (`src/sarathi/shakti/ocr/engine/rasterize.py`):
   - Open PDF once, render pages sequentially into a bounded queue (max 4–8 pages in memory).
2. **Batch Weak-Crop Recognition** (`coordinator.py`):
   - Accumulate weak crops per page and feed to recognizer in one batch call (`use_det=False`).
3. **OpenVINO Inference Concurrency**:
   - Benchmark inference vs. rasterization; allocate `InferRequest` pool or `AsyncInferQueue` to unblock `_infer_lock`.
   - Set `PERFORMANCE_HINT: THROUGHPUT` when concurrency > 1.
4. **Adaptive DPI & Quality Controls**:
   - Expose DPI knob in custom options; evaluate 200–300 DPI for high-accuracy runs.

### Phase 4: Structural Fidelity & Arbitration
1. **Table Regularity Scoring & Spanning Cell Warning** (`layout.py`):
   - Detect wide cells spanning multiple column anchors; emit `WarningRecord` on ragged row structures.
2. **Hybrid PDF Scanned Page Arbitration**:
   - Compare image bounding box area vs. text density to catch scanned pages with minimal text artifacts.
3. **Multi-Column DOCX Styling**:
   - Translate detected XY-cut column splits into Word section columns (`<w:cols>`) and paragraph indentation (`<w:ind>`).
