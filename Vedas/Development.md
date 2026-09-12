# Developer Commands

Exact developer workflows and testing commands for Sarathi, mirroring the 5 permanent CI gates.

---

## 1. Installation

Install the Python 3.13 runtime, all project capabilities, and development tools using `uv`:

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

## 3. Bytecode Compilation & Ruff Lint (CI Gate 1)

Verify Python syntax, bytecode compilation, and Ruff code formatting/lint rules:

```powershell
uv run python -m compileall -q src tests scripts
uv run ruff check .
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

Run the deterministic test suite excluding browser, performance, real model, and architecture tests:

```powershell
uv run --all-extras --group dev pytest -q -m "not browser and not performance and not real_model and not architecture"
```

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
