# Contributing to Sarathi

Thank you for contributing to Sarathi. To maintain architectural integrity and deterministic runtime behavior, all changes must strictly adhere to the project's canonical design authority.

## Architectural Authority

1. **Hierarchy of Truth**:
   - `AGENTS.md`, the current `README.md`, and locked Vedas specifications in `Vedas/` are the complete and binding architectural authority.
   - Tests verify approved contracts; they do not invent or redefine them.

2. **Core Principles**:
   - **One Owner, One Canonical Path**: Every shared responsibility has one canonical owner and execution path. Do not create parallel managers, registries, caches, or hidden fallbacks.
   - **No Fake Success**: Never report or return `SUCCESS`, `VALID`, or equivalent unless the operation actually completed and required verification succeeded.
   - **Central Consistency**: When changing a contract or dataclass, update every place that constructs, serializes, deserializes, caches, or inspects it.

## Development Workflow

1. **Python Environment**:
   - Python 3.13 (`>=3.13,<3.14`).
   - Managed via `uv`:
     ```powershell
     uv sync --all-extras --group dev
     ```

2. **Testing According to Scope**:
   - Test according to impact, not anxiety:
     - Local component changes $\rightarrow$ targeted test file (`uv run --group dev pytest -q tests/<subsystem>/test_<file>.py`).
     - Subsystem changes $\rightarrow$ subsystem test directory (`uv run --group dev pytest -q tests/<subsystem>`).
     - Core runtime changes $\rightarrow$ affected integration tests + kernel tests.
   - Pre-commit validation:
     ```powershell
     uv run python -m compileall -q src tests
     uv run ruff check src tests
     uv run --group dev pytest -q <targeted-test-path>
     git diff --check
     ```

3. **Protected Baselines**:
   - The Font Conversion architecture (`src/sarathi/shakti/font_conversion/`, `src/sarathi/shakti/docx_exporter.py`, and `tests/font_conversion/`) is a protected baseline. Any cross-system changes must verify that `uv run --group dev pytest -q tests/font_conversion` remains 100% passing.
