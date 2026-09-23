# Agent Rules for Sarathi (Streamlined & Authoritative)

Sarathi is a local document-processing application. Prefer direct, modular, maintainable code over framework-like internal architecture.

**Authority:** `AGENTS.md`, `README.md`, and active Vedas docs. Nothing else.

## Priorities

1. **Modularity** — single responsibility per module; zero duplicate or repeated logic.
2. Correct and accurate user-visible document processing.
3. Performance — backed by measurement, not assumption.
4. Clear ownership and a small mental model.
5. Reliable focused minimal tests around real behavior; no over testing or audit dumping grounds.
6. Token & tool efficiency — minimal reads, edits, and tool round-trips satisfying priorities 1–5.

## Primary Hardware Specification & Optimization Target

Sarathi's authoritative reference hardware deployment profile is pinned below.
**Rule (Primary Hardware First):** All system, threading, concurrency, accelerator, and pipeline optimizations MUST be engineered, tuned, and validated for this primary Sarathi Hardware profile first before considering generic fallback hardware.

| Component | Specification | Deployment Role & Optimization Invariants |
| :--- | :--- | :--- |
| **System** | HP Laptop 15-fd1xxx (Windows 11 x64) | Reference production host. |
| **CPU** | Intel(R) Core(TM) Ultra 5 125H (14 Cores: 4P + 8E + 2LPE, 18 Logical Processors) | **Primary Translation & Logic Host**: Tuned for multi-core x86 AVX2/AVX-VNNI neural acceleration. Compute-intensive inference must never artificially choke on single-core serialization when multi-core throughput is available. |
| **GPU** | Intel(R) Graphics (Meteor Lake iGPU, 7 Xe Cores, Driver 32.0.101.8508) | **Primary RapidOCR Accelerator**: Dedicated to OpenVINO FP16/INT8 OCR inference with persistent shader cache (`Runtime/Cache/openvino_model_cache`). Not for CUDA. |
| **NPU** | Intel(R) AI Boost (Meteor Lake NPU) | **OpenVINO NPU Engine**: Probed and managed via `yantra.devices` for static workloads. |
| **Memory** | 24 GB Physical RAM | Ample memory for concurrent in-memory OCR models and CTranslate2 neural weights without swapping. |
| **CUDA** | None (0 physical devices) | Translation and OCR pipelines must never depend on or expect NVIDIA CUDA on primary hardware. |

### Optimization Priority Invariants:
1. **Primary Hardware First**: Maximize throughput across the 14-core Core Ultra 5 125H CPU and Intel Arc iGPU (OpenVINO).
2. **Generic Hardware Second**: Provide clean fallbacks (e.g. CUDA on external GPU, pure CPU without iGPU) without degrading primary hardware execution.

## Subsystem Ownership

| Subsystem | Canonical Ownership |
| --- | --- |
| `agni` | Composition and process lifecycle |
| `sankalpa` | Shared request/result/document contracts |
| `nabhi` | Physical namespace for Kosh (registry), Manthan (planner), Pravaha (executor), artifact/quarantine |
| `shakti` | Document-processing capabilities and provider adapters (OCR, translation, banking, font conversion, native extraction) |
| `yantra` | Execution and device/accelerator resource helpers |
| `kavacha` | Security authorization and path/privacy checks at real boundaries |
| `smriti` | Optional result cache |
| `darpana` | Runtime/quality telemetry events and history |
| `sutra` | Runtime configuration |
| `mukha` | Presentation, local web transport, and frontend state |
| `dosh` | Shared error vocabulary |

*Rule:* `nabhi` is a namespace, not a second decision authority. Never create duplicate registries, planners, execution engines, or device policies.

## Canonical Architecture & Manifest

- `Vedas/architecture.manifest.json` defines production topology. Code topology and manifest change together.
- Every top-level subsystem under `src/sarathi` must be in the manifest; its immediate modules appear as `components`.
- Manifest tests (`pytest -q -m architecture`) must fail if code topology and manifest diverge.

## Core Rules

1. **Plan before editing.** Identify canonical owner, contracts, callers, wiring, caches, and tests. Get explicit approval before editing.
2. **Pragmatic ROI & Dependency Discipline.** Prefer direct implementations over framework bloat, but do not reinvent the wheel where specialized libraries provide decisive value:
   - **Allowed / Encouraged**: Battle-tested, high-performance, mature libraries (e.g. C/Rust-backed accelerators like `rapidfuzz`, `openvino`, `ctranslate2`, or complex domain parsers) where hand-rolling in pure Python would be slow, brittle, or bug-prone.
   - **Disallowed**: Redundant wrappers, speculative frameworks (e.g. LangChain, heavy ORMs), or micro-libraries for tasks the Python standard library (`re`, `unicodedata`, `xml.etree`, `pathlib`) accomplishes cleanly in ~10–20 lines.
   - **Check**: Proposals introducing a dependency must show:
     - What it introduces vs. replaces (dependency footprint, packaging impact on Windows, memory).
     - Concrete ROI: measurable correctness gain, significant speedup, or elimination of severe maintenance burdens.
3. **One owner, one path.** Single canonical implementation. Delete superseded managers, contracts, stores, and execution paths in the same change — old and new never coexist.
4. **Propagate completely.** A change is incomplete until contracts, callers, wiring, serializers, and tests agree.
5. **Preserve state across paths.** Fresh run, cache hit, retry, and serialize/deserialize must yield identical results.
6. **Respect subsystem ownership.** Plan in Manthan, execute in Pravaha, manage resources in Yantra, authorize in Kavacha, record in Darpana. Capabilities never duplicate shared infrastructure.
7. **Fail safe, stay honest.** Validate inputs fail-closed. Never leak document content, paths, or secrets. Never invent fake defaults, confidence, or availability.
8. **Tests follow architecture, not the reverse.** Fix tests contradicting architecture, never weaken production invariants.
9. **No fake success.** "Done" requires actual execution and verification.


## Fast Validation & Tool Efficiency

### 1. Compound Pre-Commit Fast Gate
Before every commit, execute the compound check to validate compilation, lint, and formatting in a single tool turn:
```powershell
uv run python -m compileall -q src tests tools; uv run ruff check .; git diff --check; git diff --cached --check
```

### 2. Test Execution Ladder ("Test Impact, Not Anxiety")
Run scoped tests during development; full suite only at milestones:

| Scope of Change | Command |
| :--- | :--- |
| **Focused fix / unit** | `uv run --group dev pytest <path> -x -q` (fail fast on first error) |
| **Subsystem / Capability** | `uv run --group dev pytest tests/<subsystem>/ -q` |
| **Architecture Gate** | `uv run --group dev pytest -q -m architecture` (instant ~1.4s) |
| **Milestone / Full Suite** | `uv run --group dev pytest` (fast deterministic suite, ~44s; or ~25s excluding architecture) |
| **Heavy Model Pipelines** | `uv run --group dev pytest -m real_model` (run only when changing neural OCR/models) |

- **On failure:** Fix defect → re-run failing test with `-x` → run file → run subsystem → full suite at milestone.
- **Anti-overtesting:** Never create catch-all audit dump files (`test_*_resilience.py`, `test_*_integrity.py`). All tests belong to their canonical subsystem owner.
- **Reporting:** Keep a plain ledger: PASS / NOT RUN / SKIPPED. Never claim "all tests passed" unless verified on the exact tree.

### 3. Context & Token Discipline
- View target lines (~10–50 lines around error/symbol), never whole large files.
- Batch search and discovery tool calls.
- Never poll task status in a loop; resume reactively from notifications.
- New files/folders require explicit approval first.

## Planning Checklist
Before modifying code:
- Objective and canonical owner
- Mandatory Overengineering & ROI Assessment
- Files to change / delete / add (new files need approval)
- Affected contracts, callers, and call paths
- Scoped test plan
- Explicitly excluded scope
