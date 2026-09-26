# Agent Rules for Sarathi (Streamlined & Authoritative)

Sarathi is a local document-processing application. Prefer direct, modular, maintainable code over framework-like internal architecture.
**Authority:** `AGENTS.md`, `README.md`, and active Vedas docs. Nothing else.

## Priorities
1. **Modularity** — single responsibility per module; zero duplicate or repeated logic.
2. Correct and accurate user-visible document processing.
3. Performance — backed by measurement, not assumption.
4. Clear ownership and a small mental model.
5. Reliable focused minimal tests around real behavior; no over-testing or audit dumping grounds.
6. Token & tool efficiency — minimal reads, edits, and tool round-trips satisfying priorities 1–5.

## Primary Hardware Invariants
- **Profile**: Intel Core Ultra 5 125H (CTranslate2 host) + Arc iGPU (OpenVINO OCR, `Runtime/Cache/openvino_model_cache`), 24GB RAM, 0 CUDA. Full specs: `Vedas/README.md`.
- **Invariants**: (1) Maximize CPU & Arc iGPU throughput first. (2) Clean CPU/CUDA fallback on generic hardware. (3) Zero CUDA dependency on primary host.

## Subsystem Ownership
`agni` (composition/lifecycle), `sankalpa` (contracts), `nabhi` (namespace: Kosh registry, Manthan planner, Pravaha executor, quarantine), `shakti` (capabilities: OCR, translation, banking, fonts, extraction), `yantra` (execution/accelerators), `kavacha` (security/paths), `smriti` (cache), `darpana` (telemetry/history), `sutra` (config), `mukha` (presentation/web), `dosh` (errors).
*Rule:* `nabhi` is a physical namespace, not a second decision authority. Never duplicate shared infrastructure.

## Canonical Architecture & Manifest
- `Vedas/architecture.manifest.json` defines production topology. Code topology and manifest change together.
- Every top-level subsystem under `src/sarathi` must be in the manifest; its immediate modules appear as `components`.
- Manifest tests (`pytest -q -m architecture`) must fail if code topology and manifest diverge.

## Core Rules
1. **Task-Scoped Approval Gate.**
   - Present the structured **Planning Checklist** before starting a task.
   - Once explicit approval is given for a task (e.g., "Proceed", "Approved"), work continuously to complete the task end-to-end, including any necessary downstream edits, bug fixes, or test alignments within task scope. Do NOT ask for repeated approval on intermediate steps or fixes required to finish the approved task.
   - Ask for re-approval ONLY if a major scope change occurs (e.g., touching unrelated subsystems, introducing new architectural components or external dependencies outside the original task scope).
2. **Pragmatic ROI & Dependency Discipline.** Direct implementations over framework bloat.
   - *Allowed*: Battle-tested, high-performance C/Rust accelerators (`rapidfuzz`, `openvino`, `ctranslate2`) where standard Python is slow/brittle.
   - *Disallowed*: Redundant wrappers, speculative frameworks (LangChain, heavy ORMs), or micro-libraries for tasks standard library (`re`, `unicodedata`, `xml.etree`, `pathlib`) handles in ~10–20 lines.
   - *Check*: Any dependency proposal must prove packaging footprint, memory impact, and concrete ROI.
3. **One owner, one path.** Single canonical implementation. Delete superseded code in the same change — old and new never coexist.
4. **Propagate completely.** A change is incomplete until contracts, callers, wiring, serializers, and tests agree.
5. **Preserve state across paths.** Fresh run, cache hit, retry, and serialize/deserialize must yield identical results.
6. **Respect subsystem ownership.** Plan in Manthan, execute in Pravaha, manage resources in Yantra, authorize in Kavacha, record in Darpana.
7. **Fail safe, stay honest.** Validate inputs fail-closed. Never leak content, paths, or secrets. Never invent fake defaults, confidence, or availability.
8. **Tests follow architecture, not the reverse.** Fix tests contradicting architecture; never weaken production invariants.
9. **No fake success.** "Done" requires actual execution and verification.
10. **Communication & Language Invariant.** Communicate in Simple English or Hinglish (Latin alphabet). Strictly avoid Devanagari script in chat/commit messages (applies to agent dialogue only — never restricts code, test fixtures, translation dictionaries, or document content). Be specific, crisp, and concise — avoid conversational verbosity, filler, or boilerplate.

## Fast Validation & Tool Efficiency
### 1. Compound Pre-Commit Fast Gate
Execute in a single tool turn before every commit:
```powershell
uv run python -m compileall -q src tests tools; uv run ruff check .; git diff --check; git diff --cached --check
```

### 2. Test Execution Ladder ("Test Impact, Not Anxiety")
Run scoped tests with `-qq --tb=line` to prevent context token bloat:
- **Focused unit / fix**: `uv run --group dev pytest <path> -x -qq --tb=line`
- **Subsystem**: `uv run --group dev pytest tests/<subsystem>/ -qq --tb=line`
- **Architecture Gate**: `uv run --group dev pytest -q -m architecture --tb=line`
- **Milestone / Full Suite**: `uv run --group dev pytest -qq --tb=line`
- **Heavy Model Pipelines**: `uv run --group dev pytest -m real_model -qq --tb=line`
- **On failure**: Fix defect → re-run with `-x` → run file → run subsystem. Never create catch-all audit dump files (e.g. `test_*_resilience.py`).

### 3. Context & Tool Output Discipline
- **Tight File Views**: View only target lines (10–30 lines around error/symbol). Never view whole files.
- **Localized Edits**: Modify only targeted line chunks. Never rewrite whole files.
- **Discovery Searches**: Use non-verbose / name-only searches when locating files; target exact identifiers.
- **Compact Git Checks & Commits**: Use `git status -s` and `git diff --stat`; write concise single-line commits.
- **Output Suppression & Script Truncation**: Cap noisy commands (e.g. `git log -n 5`, `Select-Object -First 20`); slice diagnostic script output (`[:5]`), never dump full dicts.
- **Zero Debug Prints & Execution Chatter**: Never add debug `print()` statements in code; report outcomes directly without step narration or conversational filler.
- **Zero-Artifact Discipline**: Deliver plans and updates directly in chat; never create redundant markdown files.
- **Batch Operations**: Run parallel discovery calls in a single turn.
- **Zero Polling**: Await reactive task notifications; never poll status in a loop.
- **Editor & Session Hygiene**: Keep unused IDE tabs closed to avoid implicit context bloat; use `/compact` on long chats.
- **New Files**: Require explicit user approval before adding files not in the approved plan.

## Planning Checklist & Approval Gate
### Mandatory Checklist
Every implementation plan presented to the user MUST contain:
1. **Objective**: Problem statement and intent in short.
2. **Overengineering & ROI Assessment**: Direct vs. speculative check in crisp, simple language.
3. **Files to Touch**: Explicit list of files to change, add, or delete in brief.
4. **Scoped Test Plan**: Concrete test command(s) to verify the change.

### Approval & Execution Flow
- After presenting the checklist, STOP and wait for initial task approval (e.g., "Proceed", "Approved").
- Once approved, proceed with full end-to-end execution, bug fixes, and verification until the task is complete. No repeated approvals needed for changes within task scope.
- Ask for re-approval only if a change is major and goes outside the approved task scope.
