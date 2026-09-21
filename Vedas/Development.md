# Sarathi Developer Guide

Compact developer workflow and commands mirroring the repository's CI gates.

---

## 1. Quickstart & Environment Setup

```powershell
# Automated setup (installs uv, Python 3.13, creates .venv, syncs dependencies)
powershell -ExecutionPolicy Bypass -File .\tools\scripts\update_sarathi.ps1

# Or manual bootstrap via uv
uv python install 3.13
uv sync --all-extras --group dev
```

---

## 2. Model Asset Provisioning

```powershell
# Provision local RapidOCR ONNX models (det, cls, rec_devanagari, rec_v6_en)
powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-OCRModels.ps1

# Provision CTranslate2 neural translation models (IndicTrans2 / OPUS-MT)
powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-TranslationModels.ps1 -Engine indictrans2

# Verify all declared asset checksums offline
uv run python tools/update_assets.py --check
```

---

## 3. Fast Gate & Test Execution Ladder

Always follow the scoped testing ladder before running full test suites:

| Scope | Command | Target / Speed |
| :--- | :--- | :--- |
| **Compound Fast Gate** | `uv run python -m compileall -q src tests tools; uv run ruff check .; git diff --check; git diff --cached --check` | Single-turn compile, lint, and formatting validation (~1s) |
| **Code Index Sync** | `uv run python tools/generate_code_index.py --check` | Ensures `Vedas/CODE_INDEX.md` matches source AST |
| **Focused Unit / Fix** | `uv run --group dev pytest <test_path> -x -q` | Fail-fast on first failure |
| **Subsystem Suite** | `uv run --group dev pytest tests/<subsystem>/ -q` | Scope verification (e.g. `tests/bank_statements/`, `tests/ocr/`) |
| **Architecture Gate** | `uv run --group dev pytest -q -m architecture` | Instant boundary and manifest topology validation (~2s) |
| **Milestone Full Suite** | `uv run --group dev pytest` | Full deterministic test suite (~30s) |
| **Real Model Pipelines** | `uv run --group dev pytest -m real_model` | Neural inference tests with real downloaded weights |

---

## 4. Frontend Development

```powershell
cd ui
npm ci              # Install dependencies
npm run build       # Compile single-page application to src/sarathi/mukha/web/ui/
npm run dev         # Launch Vite loopback dev server on 127.0.0.1:5173
```
