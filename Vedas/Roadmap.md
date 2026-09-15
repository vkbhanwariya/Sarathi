# Engineering Roadmap — OCR & Native Extraction Pipeline

This document captures the verified high-value findings and architectural improvements for Sarathi's OCR and native extraction engines.

---

## Priority Ledger

| Priority | Subsystem / Area | Current State & Root Cause | Target Solution | Primary Impact |
| :--- | :--- | :--- | :--- | :--- |
| **P0** | **OCR Device Routing** | In `coordinator.py`, cache stores both `f"{engine_key}:{device}"` and generic `engine_key`. A subsequent CPU request hits the generic GPU alias. | Key cache strictly by `(engine_key, target_device)` with zero device-independent alias. | **Hardware execution correctness** across mixed-device runs. |
| **P1** | **PDF OCR Rasterization** | `extract_single_page_image` in `rasterize.py` opens and closes the PDF from bytes per page under `_PYMUPDF_LOCK`. | Open PDF once in a raster producer; stream rendered pages into a bounded queue. | **Drastic speedup and lower memory churn** on 20+ page PDFs. |
| **P1** | **Weak-Crop Batching** | `coordinator.py` sends low-confidence spans to `engine(crop, use_det=False)` sequentially one-by-one. | Collate weak crops across the page and submit a single batch array to the recognizer. | **High GPU/CPU utilization & lower latency** on dense scanned pages. |
| **P1** | **Final Confidence Truth** | Page confidence is calculated from original recognition output before retry substitutions. | Recompute page-level mean confidence from the final accepted spans. | **Factual, verifiable confidence metrics** for downstream audit. |
| **P1** | **Native PDF TextPage Reuse** | `read_pdf` in `readers/pdf.py` calls `page.get_text()` separately for `"blocks"`, `"text"`, and `"dict"`. | Construct PyMuPDF `TextPage` once per page; extract all representations from it. | **50–80% faster native PDF ingestion**. |
| **P1** | **Native Table Headers** | `readers/pdf.py` blindly promotes `extracted_rows[0]` to table headers. | Use PyMuPDF's `tab.header.names` and `tab.header.external` properties. | **Table fidelity** for statements with external titles. |
| **P1** | **DOCX Nested Run Walker** | `readers/docx.py` only inspects direct child `<w:r>` tags, missing text in hyperlinks/fields. | Recursively traverse visible run containers (`<w:hyperlink>`, `<w:fldSimple>`, `<w:sdt>`). | **Extraction completeness** for real-world legal and office documents. |
| **P1** | **Native vs. OCR Arbitration** | PDF pages with any text are treated as usable, ignoring large full-page scanned background images. | Compute page image bounding-box coverage vs. text density to trigger OCR on scanned pages with watermarks/page numbers. | **Prevents silent loss of scanned content** in hybrid PDFs. |
| **P2** | **HTML Mixed Content** | `readers/html.py` discards body narrative text whenever a table is found. | Preserve both document narrative text in `PageData` and structured tables in `TableData`. | **Eliminates text loss** in HTML reports and notices. |
| **P2** | **OCR Borderless Tables** | Permissive table detection can convert multi-column text into false tables. | Apply structural confidence gate (column coordinate alignment, gap consistency, row stability). | **Prevents false positive tables** on multi-column layouts. |
| **P2** | **OCR Concurrency / Async** | All OpenVINO calls are serialized under `_infer_lock`. | Benchmark inference vs. rasterization bottleneck; evaluate `AsyncInferQueue` pool on Intel GPU. | **Multi-page throughput**. |

---

## Phased Implementation Sequence

### Phase 1: Correctness & Low-Risk Quick Wins
1. **Engine Cache Device Isolation** (`src/sarathi/shakti/ocr/engine/coordinator.py`):
   - Replace dual keying with strict `(engine_key, target_device)` dictionary.
2. **Post-Retry Confidence Recomputation** (`coordinator.py`):
   - Recalculate mean page confidence and pramana records from post-retry span list.
3. **DOCX Inline Content Extraction** (`src/sarathi/shakti/native_extraction/readers/docx.py`):
   - Implement unified run walker covering `<w:r>`, `<w:hyperlink>`, `<w:fldSimple>`, and `<w:sdt>`.
4. **HTML Narrative + Table Preservation** (`src/sarathi/shakti/native_extraction/readers/html.py`):
   - Populate `PageData` with narrative text even when `TableData` is discovered.

### Phase 2: Native & Raster Throughput
1. **PyMuPDF TextPage Reuse** (`src/sarathi/shakti/native_extraction/readers/pdf.py`):
   - Instantiate `page.get_textpage()` once per page.
2. **Native PDF Table Headers** (`readers/pdf.py`):
   - Integrate `tab.header.names` and `tab.header.external`.
3. **Producer-Consumer Raster Pipeline** (`src/sarathi/shakti/ocr/engine/rasterize.py`):
   - Open PDF once, render pages sequentially into a bounded queue (max 4–8 pages in memory).

### Phase 3: OCR Batching & Hybrid Arbitration
1. **Batch Weak-Crop Recognition** (`coordinator.py`):
   - Accumulate weak crops per page and feed to recognizer in one batch.
2. **Hybrid Page-Quality Decision**:
   - Inspect PyMuPDF `page.get_images()` and text bounding-box area ratio to accurately detect scanned pages.
3. **Table Structural Regularity Scoring** (`src/sarathi/shakti/ocr/engine/layout.py`):
   - Add column x-position stability check before creating borderless tables.

### Phase 4: Hardware Measurement & Concurrency
1. **OpenVINO Inference Profiling**:
   - Measure actual time spent in rasterization, preprocessing, inference, and postprocessing.
2. **Evaluate AsyncInferQueue**:
   - Benchmark throughput on target Intel GPU (UHD 770) vs CPU.
