# Engineering Roadmap — Master Review Matrix & Execution Plan

This document captures the verified findings, severity, priority, concrete ROI, and phased execution plan across all pipeline reviews, specifically tailored for Sarathi running on **Intel Core Ultra 5 125H (14 cores, 18 threads) + Intel Arc iGPU (2 hardware streams) + 24 GB Unified RAM**.

---

## 1. Master Findings Matrix

| ID | Subsystem & File | Finding / Improvement | Severity | Priority | Concrete ROI |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **01** | `shakti/ocr`<br>`coordinator.py` | **Engine Cache Device Alias**: Cache stores generic alias; GPU instance can be reused for CPU request or vice versa. | **Critical** | **P0** | **100% device routing correctness**; eliminates silent execution on wrong device. |
| **02** | `yantra` / `sutra`<br>`settings.toml`<br>`devices.py` | **GPU Stream Capacity Oversubscription**: Config asked for 8 streams, code defaulted to 4, but Intel Arc iGPU hardware strictly supports **2 streams** (`RANGE_FOR_STREAMS: (1, 2)`). | **High** | **P0** | **Eliminates driver queuing & GPU context contention**; binds scheduler to physical hardware. |
| **03** | `shakti/ocr`<br>`coordinator.py` | **Dual-Stream GPU Concurrency**: All model calls serialize behind a single `_infer_lock`. Unblock parallel execution for the 2 hardware streams. | **High** | **P0/P1** | **~2x wall-clock OCR throughput** on multi-page documents without thread collisions. |
| **04** | `shakti/ocr`<br>`parser.py` | **Alphanumeric Filter Stripping Bullets**: `_ALPHANUMERIC_FILTER_RE` removes `•`, `–`, `—` before `layout.py` list detection runs under `english_numbers_only`. | **High** | **P1** | **Preserves bulleted lists**; prevents list items from silently degrading into flat body text. |
| **05** | `shakti/ocr` + `docx`<br>`layout.py`<br>`typography.py`<br>`builder.py` | **Heading & Typography Preservation to DOCX**: Headings are measured geometrically (`curr.max_h >= 1.35 * median_h`) but discarded; DOCX exporter only styles `# ` prefixes which OCR never emits. | **High** | **P1** | **High-fidelity DOCX deliverables**; headings render at 14–16pt bold instead of 12pt body text. |
| **06** | `shakti/ocr` + `mukha`<br>`telemetry.py`<br>`presenter.py` | **Provenance Truth ("NE-OCR" Labeling)**: Weak-crop retries mislabeled as `"ne_ocr"` / `"NE-OCR"` in telemetry/UI despite NE-OCR being decommissioned. | **Medium** | **P1** | **Truthful audit provenance** conforming strictly to `AGENTS.md` ("Fail safe, stay honest"). |
| **07** | `shakti/ocr`<br>`coordinator.py` | **Post-Retry Confidence Truth**: Page mean confidence is calculated from initial OCR output, ignoring successful crop retry score improvements. | **Medium** | **P1** | **Factual, verifiable confidence metrics** for downstream review and automated quality gating. |
| **08** | `native_extraction`<br>`readers/docx.py` | **DOCX Nested Run Walker**: Only direct `<w:r>` children are traversed, missing text in hyperlinks (`<w:hyperlink>`), field codes (`<w:fldSimple>`), and structured tags (`<w:sdt>`). | **High** | **P1** | **Extraction completeness**; guarantees no silent omissions of URLs and form fields in legal/office docs. |
| **09** | `native_extraction`<br>`readers/html.py` | **HTML Narrative + Table Coexistence**: Body narrative text is discarded (`pages = ()`, `doc_text = ""`) whenever a table is found. | **High** | **P1** | **Eliminates total text loss** for HTML reports containing both tables and explanatory narrative. |
| **10** | `shakti/ocr`<br>`readiness.py`<br>`provider.py` | **Readiness Check Hashing Cache**: Streamed SHA-256 of all model files runs from scratch on every health check poll with no cache. | **Low** | **P1** | **Zero disk I/O on UI health polling**; instantaneous capability readiness response. |
| **11** | `shakti/ocr`<br>`rasterize.py` | **Single-Open PDF Rasterizer with Bounded Queue**: `extract_single_page_image` re-opens and parses full PDF byte stream per page under a global lock. | **High** | **P1** | **N-fold reduction in PDF parsing overhead**; avoids re-parsing a 50-page PDF 50 separate times. |
| **12** | `native_extraction`<br>`readers/pdf.py` | **Native PDF `TextPage` Reuse**: Page parses glyphs 3 separate times (`"blocks"`, `"text"`, `"dict"`). | **Medium** | **P1** | **50–80% speedup** in native PDF text extraction by parsing `TextPage` once. |
| **13** | `native_extraction`<br>`readers/pdf.py` | **Native Table Header Extraction**: `extracted_rows[0]` is blindly promoted as header, corrupting statements with external titles. | **Medium** | **P1** | **Table structural fidelity** using PyMuPDF `tab.header.names` and `tab.header.external`. |
| **14** | `yantra` / `sutra`<br>`devices.py`<br>`settings.toml` | **CPU Thread Pool Tuning for Meteor Lake**: 18 threads spawned across P-cores, E-cores, and LP SoC cores, causing thread migration onto low-power island cores. | **Medium** | **P1** | **Bounds CPU worker pool to 4–6 cores**; avoids LP E-core latency bottlenecks and thermal throttling. |
| **15** | `shakti/ocr`<br>`openvino.py` | **Persistent OpenVINO GPU Model Cache**: Cold GPU init takes 5.64s compiling shaders on this Arc iGPU. | **Medium** | **P2** | **Drops GPU init from 5.6s to < 0.2s** on all subsequent runs using `CACHE_DIR`. |
| **16** | `shakti/ocr`<br>`layout.py` | **Metric-Aware Line Spacing for OCR**: Unconditional `" ".join(...)` splits Devanagari conjuncts and kerned words (`"C orporation"`). | **Medium** | **P2** | **Eliminates word fragmentation**; leverages font-metric gap logic (`reconstruct_line_from_spans`). |
| **17** | `shakti/ocr`<br>`coordinator.py` | **Weak-Crop Batch Recognition**: Spans needing retry are passed to recognizer one-by-one in a serial loop. | **Medium** | **P2** | **Single batched inference call per page** utilizing vector units (`rec_batch_num`). |
| **18** | `shakti/ocr`<br>`layout.py` | **Table Spanning Cells & Ragged Rows**: Spanning cells forced into single nearest column anchor, misaligning financial tables. | **Medium** | **P2** | **Prevents silent column corruption**; detects span width and emits `WarningRecord` on ragged rows. |
| **19** | `shakti/ocr` + `native`<br>`capability.py` | **Hybrid PDF Scanned Page Arbitration**: Pages with minimal text (watermarks/page numbers) skip OCR even when body is a scanned image. | **Medium** | **P2** | **Area coverage comparison** ensures scanned pages with background images are never silently skipped. |
| **20** | `docx_exporter`<br>`builder.py` | **Multi-Column DOCX Layout**: XY-cut reading order collapses into a single-column flow in Word. | **Low** | **P3** | **Faithful visual representation** of multi-column source pages using `<w:cols w:num="2"/>`. |

---

## 2. Phased Implementation Sequence

### Phase 1: Zero-Risk Correctness & Provenance Truth
1. **Engine Cache Isolation** (`coordinator.py`): Key cache strictly by `(engine_key, target_device)`.
2. **Alphanumeric Bullet Preservation** (`parser.py`): Retain bullets (`•`, `–`, `—`) in `_ALPHANUMERIC_FILTER_RE`.
3. **Provenance Truth Labeling** (`telemetry.py`, `presenter.py`): Label retries as `"same_engine_retry"` / `"Same-Engine Retry"`.
4. **Post-Retry Confidence Recomputation** (`coordinator.py`): Recompute mean confidence from final accepted spans.
5. **Readiness Check Memoization** (`readiness.py`): Cache verified model paths to avoid re-hashing.
6. **DOCX Recursive Run Walker** (`readers/docx.py`): Traverse `<w:hyperlink>`, `<w:fldSimple>`, `<w:sdt>`.
7. **HTML Narrative + Table Coexistence** (`readers/html.py`): Preserve narrative text in `PageData` alongside `TableData`.

### Phase 2: Hardware Tuning & Concurrency (Intel Core Ultra 5 125H + Arc iGPU)
1. **Settings & Stream Alignment** (`settings.toml`, `devices.py`):
   - Set `gpu_capacity_per_device = 2` (matching `RANGE_FOR_STREAMS: (1, 2)`).
   - Set CPU worker capacity to 4–6 (matching P-cores, avoiding 18-thread thrashing).
   - Dynamically bound capacity in `default_inventory` via `RANGE_FOR_STREAMS`.
2. **OpenVINO Device Tuning for Arc iGPU & Meteor Lake** (`openvino.py`):
   - GPU: `NUM_STREAMS = 2`, `PERFORMANCE_HINT = THROUGHPUT`, `INFERENCE_PRECISION_HINT = f16`, `CACHE_MODE = OPTIMIZE_SPEED`.
   - CPU: `ENABLE_CPU_PINNING = True`, `CPU_DENORMALS_OPTIMIZATION = True`.
   - Cache: Persist `CACHE_DIR = Runtime/Cache/openvino_model_cache` to keep GPU load time < 200ms.
3. **Dual-Stream GPU Engine Pool** (`coordinator.py`):
   - Allocate 2 engine instances for GPU and replace `_infer_lock` with a 2-slot semaphore.

### Phase 3: Layout Preservation & Native Extraction Speed
1. **Heading & Typography Propagation to DOCX** (`layout.py`, `ocr/typography.py`, `builder.py`):
   - Tag detected headings (`curr.max_h >= 1.35 * median_h`) and call `infer_line_font_size` to render headings at 14–16pt bold.
2. **Metric-Aware Line Spacing for OCR** (`layout.py`):
   - Replace naive `" ".join(...)` with font-metric gap checks (`reconstruct_line_from_spans`).
3. **PyMuPDF `TextPage` Reuse** (`readers/pdf.py`):
   - Call `page.get_textpage()` once per page (50–80% speedup).
4. **Native Table Header Extraction** (`readers/pdf.py`):
   - Use `tab.header.names` and `tab.header.external`.

### Phase 4: Rasterization Pipeline & OCR Batching
1. **Single-Open PDF Rasterizer with Bounded Queue** (`rasterize.py`):
   - Open PDF once; render pages into a bounded queue (4–8 pages in memory).
2. **Weak-Crop Batch Recognition** (`coordinator.py`):
   - Collate weak crops on a page and call `engine(crops_batch, use_det=False)` in a single batch.
3. **Adaptive DPI Knob**:
   - Allow 200–300 DPI for `ACCURATE` profile and retries.

### Phase 5: Table Structural Fidelity & Advanced DOCX Layout
1. **Table Spanning Cell & Ragged Row Guards** (`layout.py`):
   - Detect spanning cells; emit a `WarningRecord` when rows deviate from header column count.
2. **Hybrid PDF Scanned Page Arbitration**:
   - Compare image bounding box area vs. text density to catch scanned pages with minimal text.
3. **Multi-Column DOCX Section Styling** (`builder.py`):
   - Translate detected XY-cut column splits into Word section columns (`<w:cols w:num="2"/>`).

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
