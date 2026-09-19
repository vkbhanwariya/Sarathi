# Developer Commands

Exact developer workflows and testing commands for Sarathi, mirroring the 5 permanent CI gates.

---

## 1. Installation & Environment Management

### Automated Setup & Maintenance (`tools/scripts/update_sarathi.ps1` / `update_sarathi.cmd`)

The bootstrapper ensures complete, isolated environment management:

- **Double-Click in File Explorer / CMD:** Double-click `tools\scripts\update_sarathi.cmd` (automatically bypasses execution policy and keeps the window open until a key is pressed).
- **PowerShell Console:**
```powershell
powershell -ExecutionPolicy Bypass -File .\tools\scripts\update_sarathi.ps1
```

Capabilities:
- Operates entirely in user space (no Administrator elevation required).
- Installs or updates `uv` and Python 3.13.
- Creates and maintains the dedicated virtual environment locked strictly to `E:\Sarathi\.venv`.
- Synchronizes all capability extras and dev tools (`uv sync --all-extras --group dev`).
- Offers an interactive menu or CLI flags (`-BumpPins`) for lockfile updates, PyPI package check, and pin bumping.
- Filters out upstream-constrained dependencies (`antlr4-python3-runtime`, `pyee`, `python-slugify`).

### OCR Model Asset Provisioning (`tools/scripts/Setup-OCRModels.ps1`)

Provisions and cryptographically verifies declared OpenVINO RapidOCR ONNX model assets in `data/ocr/models/` against `data/ocr/manifest.json`:

```powershell
# Verify existing model assets without downloading
powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-OCRModels.ps1 -VerifyOnly

# Download missing models from canonical upstream mirrors (ModelScope / HuggingFace)
powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-OCRModels.ps1

# Provision from a local folder containing pre-downloaded ONNX models
powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-OCRModels.ps1 -SourceDir C:\Downloads\OCRModels
```

Required models provisioned:
- `det`: `ch_PP-OCRv5_det_mobile.onnx`
- `cls`: `ch_ppocr_mobile_v2.0_cls_mobile.onnx`
- `rec_devanagari`: `devanagari_PP-OCRv5_rec_mobile.onnx`
- `rec_v6_en`: `PP-OCRv6_rec_small.onnx`

### Translation Model Asset Provisioning (`tools/scripts/Setup-TranslationModels.ps1`)

Provisions and cryptographically verifies declared CTranslate2 neural translation model assets in `data/translation/models/` against SHA-256 checksums:

```powershell
# Verify existing model assets without downloading
powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-TranslationModels.ps1 -VerifyOnly

# Provision high-fidelity IndicTrans2 neural models (default in production)
powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-TranslationModels.ps1 -Engine indictrans2

# Provision lightweight OPUS-MT models
powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-TranslationModels.ps1 -Engine opus_mt

# Provision both engines
powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-TranslationModels.ps1 -Engine all

# Provision from a local folder containing pre-downloaded models (100% offline)
powershell -ExecutionPolicy Bypass -File .\tools\scripts\Setup-TranslationModels.ps1 -Engine indictrans2 -SourceDir C:\Downloads\TranslationModels
```

Required models provisioned:
- `indictrans2`: `indictrans2-indic-en-dist-200M` (`hi` → `en`) and `indictrans2-en-indic-dist-200M` (`en` → `hi`) with dual SentencePiece tokenizers.
- `opus_mt`: `opus-mt-hi-en` and `opus-mt-en-hi` with SentencePiece models.

### Unified External Asset Inspection & Updates (`tools/update_assets.py`)

Centralized asset management, integrity auditing, and optional upstream synchronization declared in `data/external_sources.json`:

```powershell
# 100% offline integrity and checksum check
uv run python tools/update_assets.py --check

# Or via update_sarathi script
powershell -ExecutionPolicy Bypass -File .\tools\scripts\update_sarathi.ps1 -CheckAssets

# Update SIL font fixtures from canonical upstream definitions
uv run python tools/update_assets.py --update-sil

# Update/provision RapidOCR models with SHA-256 verification
uv run python tools/update_assets.py --update-ocr

# Provision/verify all external assets on demand
powershell -ExecutionPolicy Bypass -File .\tools\scripts\update_sarathi.ps1 -UpdateAssets
```

### Manual Setup via `uv`

```powershell
uv python install 3.13
uv sync --all-extras --group dev
```

---

## 2. Run Application

### Local Web UI

Launch the loopback web server and open the browser interface:

```powershell
.\arambha.bat
```

Or run the module directly:

```powershell
uv run python -m sarathi
```

The application runs at `http://127.0.0.1:8000/`.

### CLI Execution

Execute pipeline operations directly from the command line:

```powershell
uv run sarathi --input "path/to/document.pdf" --requirement "read_native" --profile "instant"
```

---

## 3. Bytecode Compilation, Ruff Lint & Pre-Commit Fast Gate (CI Gate 1)

Before committing or pushing, execute the compound fast gate to validate compilation, linting, and whitespace/git diff integrity in a single command:

```powershell
uv run python -m compileall -q src tests tools; uv run ruff check .; git diff --check; git diff --cached --check
```

To automatically format or fix safe lint violations:

```powershell
uv run ruff format .
uv run ruff check --fix .
```

---

## 4. Architecture Tests (CI Gate 2)

Validate repository hygiene, subsystem ownership boundaries, and alignment with `Vedas/architecture.manifest.json`:

```powershell
uv run --group dev pytest -q tests/architecture
```

---

## 5. Frontend Build (CI Gate 3)

Compile the TypeScript/Preact single-page application and bundle assets into `src/sarathi/mukha/web/ui/`:

```powershell
cd ui
npm ci
npm run build
cd ..
```

---

## 6. Unit & Integration Tests (CI Gate 4)

Sarathi features an optimized deterministic test suite that executes across all subsystems in **~25 seconds** excluding architecture tests (>75% wall-clock reduction), or **~44 seconds** for the full suite including architecture tests.

### Deterministic CI Gate Execution
```powershell
uv run --all-extras --group dev pytest -q -m "not browser and not performance and not real_model and not architecture"
```

### Test Execution Ladder ("Test Impact, Not Anxiety")
Run scoped tests during development; full suite only at milestones:

| Scope of Change | Command | Target Duration |
| :--- | :--- | :--- |
| **Focused fix / unit** | `uv run --group dev pytest <path> -x -q` (fail fast on first error) | < 1s |
| **Subsystem / Capability** | `uv run --group dev pytest tests/<subsystem>/ -q` | 1–3s |
| **Architecture Gate** | `uv run --group dev pytest -q -m architecture` | ~2.3s |
| **Milestone / Full Suite** | `uv run --all-extras --group dev pytest -q -m "not browser and not performance and not real_model"` | ~44s (~25s without architecture) |
| **Heavy Model Pipelines** | `uv run --all-extras --group dev pytest -m real_model` | On neural model changes |

### Optimization & Efficiency Patterns
- **Teardown Thread Synchronization**: Uses `_wait_for_idle(web_server)` before teardown rather than hardcoded sleeps or thread join timeouts.
- **Instant Retry Mocks**: Mocked exponential backoff loops patch `time.sleep` to eliminate artificial 30s+ wait delays in unit tests.
- **Session-Scoped Backend Fixtures**: Compiles translation corpora and glossaries once per test session.
- **Parameterized Test Matrices**: Parameterizes repetitive assertions into compact `@pytest.mark.parametrize` matrices.

---

## 7. Playwright Browser Tests (CI Gate 5)

Install Playwright browsers (one-time setup):

```powershell
uv run playwright install --with-deps chromium
```

Run the end-to-end browser test suite:

```powershell
uv run --all-extras --group dev pytest -q -m browser
```

---

## 8. Planning Gate: Overengineering & ROI Verification

Before writing code or modifying dependencies, agents and contributors must satisfy Core Rule 2 and the pre-implementation planning checklist in [`AGENTS.md`](../AGENTS.md).

Every implementation proposal must present an explicit **Overengineering & ROI Assessment**:
- **Demonstrated Need vs. Speculative Need**: Solves a current, verified requirement without speculative abstractions.
- **What It Replaces vs. What It Introduces**: Quantifies dependencies, code footprint, and runtime overhead.
- **Simpler Alternatives Explored**: Verifies why standard library, built-in features, or direct functions are insufficient.
- **Concrete ROI**: States the measurable gain in correctness, speed, security, or maintainability.
