---
name: sarathi-dev
description: Authoritative developer runbook for Sarathi. Use when running tests, executing validation gates, verifying architecture manifest sync, or tuning OpenVINO/CTranslate2 workflows for Intel Meteor Lake hardware.
---

# Sarathi Developer Runbook (`sarathi-dev`)

This skill provides the authoritative procedures for testing, linting, manifest verification, and hardware-aligned execution in the Sarathi codebase.

---

## 1. Compound Pre-Commit Fast Gate

Execute this exact one-line command to validate compilation, formatting, and linting in a single tool turn before every commit:

```powershell
uv run python -m compileall -q src tests tools; uv run ruff check .; git diff --check; git diff --cached --check
```

- If `ruff` reports fixable errors, auto-fix with:
  ```powershell
  uv run ruff check --fix .
  uv run ruff format .
  ```

---

## 2. Test Execution Ladder ("Test Impact, Not Anxiety")

Always start with the most narrowly scoped test. Escalate up the ladder only as needed:

| Scope of Change | Command | Intent |
| :--- | :--- | :--- |
| **Focused Unit / Fix** | `uv run --group dev pytest <path> -x -q` | Fail fast on the first error. |
| **Subsystem / Capability** | `uv run --group dev pytest tests/<subsystem>/ -q` | Verify subsystem integrity. |
| **Architecture Gate** | `uv run --group dev pytest -q -m architecture` | Verify manifest sync (~1.4s). |
| **Milestone / Full Suite** | `uv run --group dev pytest` | Full deterministic test suite (~44s). |
| **Heavy Model Pipelines** | `uv run --group dev pytest -m real_model` | Run only when neural weights or OCR models are touched. |

---

## 3. Token & Context Discipline Runbook

To maintain minimal token consumption and maximum accuracy:

1. **Targeted Line Range**: View only 10–50 lines around the error/symbol using `StartLine` and `EndLine`. Never view entire files.
2. **Diagnostic-Driven Edits**: Leverage `TargetLintErrorIds` and IDE diagnostics directly instead of trial-and-error edits.
3. **Batch Searches**: Combine grep/discovery operations into a single step where possible.
4. **No Loop Polling**: Avoid running status checks in a loop. Await reactive task notifications.

---

## 4. Primary Hardware Deployment Invariants

All pipeline optimizations must target the primary reference profile:

- **Host**: HP Laptop 15-fd1xxx (Windows 11 x64).
- **CPU**: Intel Core Ultra 5 125H (14 Cores: 4P + 8E + 2LPE, 18 Logical Processors) — Primary host for CTranslate2 and application logic. Multi-core AVX2/AVX-VNNI acceleration.
- **GPU**: Intel Arc Graphics (Meteor Lake iGPU, 7 Xe Cores) — Dedicated OpenVINO FP16/INT8 OCR engine (`Runtime/Cache/openvino_model_cache`).
- **NPU**: Intel AI Boost (Meteor Lake NPU) — Probed via `yantra.devices`.
- **CUDA**: **None (0 physical devices)**. Never add or expect CUDA dependencies on primary hardware.

---

## 5. Canonical Architecture Manifest Sync

Sarathi follows `Vedas/architecture.manifest.json` as the authoritative source of topology.
- Every subsystem under `src/sarathi/` must exist in `architecture.manifest.json`.
- When adding or removing modules, update `Vedas/architecture.manifest.json` in the same change.
- Verify manifest conformance:
  ```powershell
  uv run --group dev pytest -q -m architecture
  ```
