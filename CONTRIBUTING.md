# Contributing to Sarathi

Thank you for contributing to Sarathi. To maintain architectural integrity and deterministic runtime behavior, all contributions must strictly adhere to the project's canonical design authority.

## Architectural Authority

- **Single Source of Truth**: [AGENTS.md](file:///e:/Sarathi/AGENTS.md), [README.md](file:///e:/Sarathi/README.md), and locked specifications in [Vedas/](file:///e:/Sarathi/Vedas/) are the binding authority for architecture, contracts, subsystem ownership, and scoped testing.
- **Core Principles**: One canonical owner per responsibility, complete propagation across boundaries, zero fake success, and no hidden fallbacks. Always consult `AGENTS.md` before designing or modifying code.

## Development Workflow

1. **Environment Setup**:
   - Python 3.13 (`>=3.13,<3.14`).
   - Sync locked dependencies:
     ```powershell
     uv sync --all-extras --group dev
     ```

2. **Pre-Commit Verification**:
   Before submitting changes or opening a pull request, run the canonical verification gate:
   ```powershell
   uv run --group dev python -m compileall -q src tests
   uv run --group dev pytest -q <targeted-test-path>
   git diff --check
   ```

3. **Scoped Testing**:
   Follow the Targeted Testing Matrix in `AGENTS.md`: test according to impact (local change $\rightarrow$ targeted test; subsystem change $\rightarrow$ subsystem tests; global milestone $\rightarrow$ full suite).

4. **Protected Baselines**:
   The Font Conversion subsystem (`src/sarathi/shakti/font_conversion/`, `src/sarathi/shakti/docx_exporter.py`, and `tests/font_conversion/`) is a protected baseline. Any cross-cutting changes must verify that `uv run --group dev pytest -q tests/font_conversion` remains 100% passing.
