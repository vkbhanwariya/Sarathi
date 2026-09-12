# Sarathi

Sarathi is a local-first document intelligence system for extracting, understanding, translating, converting, and consolidating documents. It provides fail-closed local processing with optional cloud integration.

All changes are validated directly on `main` against the 5 permanent CI gates.

---

## Supported Capabilities

- **Native Document Extraction**: Text, table, and structure extraction from PDF, DOCX, XLSX, legacy XLS (BIFF8), HTML tables, XML Spreadsheet 2003, and delimited text (CSV, TSV, semicolon, pipe).
- **Local Optical Character Recognition (OCR)**: RapidOCR with OpenVINO acceleration and targeted Tesseract 5 fallback.
- **Neural Translation**: Bidirectional Hindi <-> English translation via local CTranslate2 and SentencePiece models.
- **Legacy Hindi Font Conversion**: Automatic detection and conversion of legacy non-Unicode font encodings (Kruti Dev, Devlys, Chanakya, Shusha, Shivaji) to standard Unicode Devanagari.
- **Bank Statement Processing**: Tabular statement parsing, header mapping, transaction normalization, and running balance reconciliation for HDFC, ICICI, SBI, and standard financial formats.
- **Statutory & Legal Extraction**: Algorithmic extraction and mathematical checksum validation for PAN, TAN, GSTIN, CIN, CNR (eCourts), DIN, and IRN.
- **OpenXML Output Generation**: Standardized DOCX generation and transformation with script-aware bilingual typography.
- **Optional Cloud Providers**: Cloud adapters for Mistral AI, Google Gemini, Microsoft Azure, and Bhashini.

---

## Main Dependencies

- **Runtime**: Python `>=3.13,<3.14`
- **Core Runtime**: `starlette`, `uvicorn`, `pymupdf`, `polars`, `openpyxl`, `python-calamine`, `xlrd`, `charset-normalizer`, `beautifulsoup4`, `pyyaml`
- **Frontend**: TypeScript, Preact, Vite (served strictly over loopback `127.0.0.1`)
- **Optional Capabilities**:
  - `ocr`: `rapidocr`, `openvino`, `opencv-python-headless`, `pillow`, `pytesseract`
  - `translation`: `ctranslate2`, `sentencepiece`
  - `cloud`: `httpx`

---

## Quick Start

### 1. Installation

Install the Python runtime and dependencies:

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

## Detailed Documentation

Comprehensive engineering documentation is maintained in [`Vedas/`](Vedas/README.md):

- **[Architecture & Runtime Flow](Vedas/Architecture.md)**: Canonical subsystem ownership, runtime coordination, and architectural invariants.
- **[Capabilities Specification](Vedas/Capabilities.md)**: Inputs, outputs, fallbacks, configurations, and limitations for each capability.
- **[Runtime Configuration](Vedas/Configuration.md)**: Configurable options, defaults, and security/cloud processing settings.
- **[Supported Formats](Vedas/Formats.md)**: Details on supported PDF, DOCX, spreadsheet, delimited text, and legacy font formats.
- **[Troubleshooting](Vedas/Troubleshooting.md)**: Diagnoses and actionable fixes for OCR, OpenVINO, fonts, encodings, and network setup.
- **[Developer Workflow & CI Commands](Vedas/Development.md)**: Exact commands for testing, linting, building, and running CI gates.
- **[Local Web Transport](Vedas/Mukha_Transport.md)**: ASGI server configuration, SSE streaming, and security boundary.
- **[Production Architecture Manifest](Vedas/architecture.manifest.json)**: Machine-readable system topology.