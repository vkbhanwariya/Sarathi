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

## 3. Bytecode Compilation & Ruff Lint (CI Gate 1)

Verify Python syntax, bytecode compilation, and Ruff code formatting/lint rules:

```powershell
uv run python -m compileall -q src tests tools
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

---

## 8. Planning Gate: Overengineering & ROI Verification

Before writing code or modifying dependencies, agents and contributors must satisfy Core Rule 2 and the pre-implementation planning checklist in [`AGENTS.md`](../AGENTS.md).

Every implementation proposal must present an explicit **Overengineering & ROI Assessment**:
- **Demonstrated Need vs. Speculative Need**: Solves a current, verified requirement without speculative abstractions.
- **What It Replaces vs. What It Introduces**: Quantifies dependencies, code footprint, and runtime overhead.
- **Simpler Alternatives Explored**: Verifies why standard library, built-in features, or direct functions are insufficient.
- **Concrete ROI**: States the measurable gain in correctness, speed, security, or maintainability.
