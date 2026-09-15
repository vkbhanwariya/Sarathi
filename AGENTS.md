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
2. **Overengineering & ROI Check.** Never introduce speculative abstractions, redundant wrappers, or unvetted dependencies. Implementation proposals MUST show:
   - What it replaces vs. introduces (dependency footprint, memory, maintenance).
   - Concrete ROI: measurable correctness, speed, security, or maintainability gain.
   - Simpler alternatives explored and why repository tools are insufficient.
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
uv run python -m compileall -q src tests tools; uv run ruff check .; git diff --check
```

### 2. Test Execution Ladder ("Test Impact, Not Anxiety")
Run scoped tests during development; full suite only at milestones:

| Scope of Change | Command |
| :--- | :--- |
| **Focused fix / unit** | `uv run --group dev pytest <path> -x -q` (fail fast on first error) |
| **Subsystem / Capability** | `uv run --group dev pytest tests/<subsystem>/ -q` |
| **Architecture Gate** | `uv run --group dev pytest -q -m architecture` (instant ~1.4s) |
| **Milestone / Full Suite** | `uv run --group dev pytest` (fast deterministic suite, ~44s) |
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
