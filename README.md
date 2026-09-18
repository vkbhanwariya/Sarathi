# Sarathi

Sarathi is a local-first document intelligence system for extracting, understanding, translating, converting, and consolidating documents. It provides fail-closed local processing with optional cloud integration.

All changes are validated directly on `main` against the 5 permanent CI gates.

---

## Supported Capabilities

- **Native Document Extraction**: High-performance text, table, and structure extraction from PDF via PyMuPDF (`pymupdf`), DOCX, XLSX, legacy XLS (BIFF8 via Calamine/xlrd), HTML tables, XML Spreadsheet 2003, and delimited text (CSV, TSV, semicolon, pipe).
- **Local Optical Character Recognition (OCR)**: RapidOCR with OpenVINO acceleration (Intel Arc iGPU and CPU) and selective same-engine weak-crop retry with CLAHE enhancement.
- **Neural Translation**: Bidirectional Hindi <-> English translation via local CTranslate2 and SentencePiece models (IndicTrans2 and OPUS-MT). Features domain legal context, dynamic statutory glossary matching (PMLA, Banking), statutory identifier harmonization, and rate-paced cloud seeding.
- **Legacy Hindi Font Conversion**: Automatic detection and conversion of legacy non-Unicode font encodings (Kruti Dev, Devlys, Chanakya, Shusha, Shivaji) to standard Unicode Devanagari. Features embedded TrueType SFNT inspection via PyMuPDF, 14 precompiled Akshara synthesis regexes with AVX2 SIMD acceleration (`rapidfuzz`, `regex`), typewriter mechanical error correction, and statutory acronym protection.
- **Bank Statement Processing**: Tabular statement parsing, header mapping, transaction normalization, and running balance reconciliation for HDFC, ICICI, SBI, and standard financial formats.
- **Statutory & Legal Extraction**: Algorithmic extraction and mathematical checksum validation for PAN, TAN, GSTIN, CIN, CNR (eCourts), DIN, and IRN.
- **OpenXML Output Generation**: Standardized DOCX generation and transformation with script-aware bilingual typography.
- **Optional Cloud Providers**: Cloud adapters for Mistral AI, Google Gemini, and Microsoft Azure with proactive 2.0s rate pacing, Retry-After header parsing, exponential backoff, and per-document legal isolation.

---

## Main Dependencies

- **Runtime**: Python `>=3.13,<3.14`
- **Core Runtime**: `starlette`, `uvicorn`, `pymupdf`, `polars`, `openpyxl`, `python-calamine`, `xlrd`, `charset-normalizer`, `beautifulsoup4`, `pyyaml`
- **Frontend**: TypeScript, Preact, Vite (served strictly over loopback `127.0.0.1`)
- **Optional Capabilities**:
  - `ocr`: `rapidocr`, `openvino`, `opencv-python-headless`, `pillow`
  - `translation`: `ctranslate2`, `sentencepiece`
  - `font_conversion`: `rapidfuzz`, `regex`
  - `layout`: `pymupdf-layout`
  - `cloud`: `httpx`

---

## Quick Start

### 1. Installation & Environment Sync

The automated bootstrapper script configures `uv`, Python 3.13, and the root `.venv`.

**Double-click in Windows File Explorer:**
Double-click `tools\scripts\update_sarathi.cmd`

**Or run in PowerShell:**
```powershell
powershell -ExecutionPolicy Bypass -File .\tools\scripts\update_sarathi.ps1
```

Or configure manually via `uv`:

```powershell
uv python install 3.13
uv sync --all-extras --group dev
```

### 2. Run Local Web Interface

Start the local web application at `http://127.0.0.1:8000/`:

```powershell
.\arambha.bat
```

Or run the module directly:

```powershell
uv run python -m sarathi
```

### 3. CLI Usage

Run document processing directly from the command line:

```powershell
uv run sarathi --input "path/to/document.pdf" --requirement "read_native" --profile "instant"
```

---

## Engineering Rules & ROI Discipline

Sarathi enforces strict modularity and zero-overengineering rules declared in [`AGENTS.md`](AGENTS.md). Any proposal introducing new dependencies or major structural changes requires an explicit **Overengineering & ROI Assessment** demonstrating measurable gains and evaluating simpler built-in alternatives before implementation.

---

## Fast Validation & Developer Gates

Before every commit, execute the single-turn compound pre-commit gate:

```powershell
uv run python -m compileall -q src tests tools; uv run ruff check .; git diff --check
```

The optimized test suite runs deterministically in **~25 seconds** (>75% wall-clock reduction):

```powershell
uv run --all-extras --group dev pytest -q -m "not browser and not performance and not real_model and not architecture"
```

---

## Detailed Documentation

Comprehensive engineering documentation is maintained in [`Vedas/`](Vedas/README.md):

- **[Architecture & Runtime Flow](Vedas/Architecture.md)**: Canonical subsystem ownership, runtime coordination, and architectural invariants.
- **[Capabilities Specification](Vedas/Capabilities.md)**: Inputs, outputs, fallbacks, configurations, and limitations for each capability.
- **[Runtime Configuration](Vedas/Configuration.md)**: Configurable options, defaults, and security/cloud processing settings.
- **[Supported Formats](Vedas/Formats.md)**: Details on supported PDF, DOCX, spreadsheet, delimited text, and legacy font formats.
- **[Troubleshooting](Vedas/Troubleshooting.md)**: Diagnoses and actionable fixes for OCR, OpenVINO, fonts, encodings, and network setup.
- **[Developer Workflow & CI Commands](Vedas/Development.md)**: Exact commands for testing, linting, building, and running CI gates.
- **[Local Web Transport](Vedas/Mukha_Transport.md)**: ASGI server configuration, SSE streaming, and security boundary.
- **[Design & Product Decisions](Vedas/Decisions.md)**: Canonical UI/UX progressive Home task hierarchy and capability mapping.
- **[Production Architecture Manifest](Vedas/architecture.manifest.json)**: Machine-readable system topology.