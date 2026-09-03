# Agent Rules for Sarathi

You are implementing Sarathi. `AGENTS.md`, the current `README.md`, and only the relevant Vedas specifications are the complete architectural authority.


## Core Principle

> **Central infrastructure must provide one consistent source of truth. Plan before editing, propagate core changes through every affected boundary, validate according to scope, and never treat incomplete or unverified work as success. Optimize tokens and iteration effort without reducing correctness, architectural consistency, or verification quality.**


## Core System Consistency Rules

1. **Plan Impact Before Editing:** Before changing core code, identify: canonical owner, affected contracts, callers, wiring, persistence/cache boundaries, and affected tests. Present the plan and obtain explicit user approval before modifying code, config, docs, or tests.
2. **One Owner, One Canonical Path:** Every shared responsibility must have one canonical owner and one canonical execution path. Do not create parallel managers, registries, lifecycle paths, caches, retry logic, telemetry, validation owners, or hidden fallbacks. Presentation, plugins, and capabilities consume core decisions; they never reimplement them or import private implementation details.
3. **Core Changes Must Propagate Completely:** A core change is incomplete until all affected contracts, registration, wiring, callers, serializers, caches, lifecycle paths, and tests remain consistent. Never change one core layer while leaving another canonical path on old behavior. Delete superseded code in the same change — never leave old and new coexisting.
4. **Preserve Complete Canonical State & Equivalent Paths:** When a core contract or dataclass changes, inspect every place that reconstructs, serializes, deserializes, caches, copies, or exports it. No meaningful field may disappear during round-trip processing. The same input must produce the same canonical result across: fresh execution and cache hit, L1 and L2 cache, direct and resumed execution, normal and retry execution, and serialization/deserialization.
5. **Subsystem Boundaries & Single Lifecycle Owner:** Use injected services and canonical Sankalpa contracts. Do not bypass Kosh, Manthan, Prana, Yantra, Pravaha, Darpana, Kavacha, or Nabhi when they are the declared owner. Startup, shutdown, retry, quarantine, allocation, release, cache, and artifact lifecycle must each have one responsible owner. Preserve the primary exception when secondary cleanup fails.
6. **Zero Leaks, Input Safety & Truthful State:** Validate public inputs before state mutation. Public errors, telemetry, manifests, logs, and presentation must not expose document contents, raw local paths, secrets, or raw exception messages. Core infrastructure must never invent defaults, confidence, capability availability, dependency availability, state, or fallback behavior — unknown stays unknown.
7. **Tests Follow Architectural Authority:** Tests must verify approved contracts; they must not redefine them. If a test conflicts with `AGENTS.md`, `README.md`, or a locked Veda, identify and correct the stale test rather than altering production behavior merely to satisfy it. Add focused positive, negative, and adversarial tests for every changed boundary (malformed, duplicate, missing, foreign, and boundary inputs).
8. **Test According to Scope & Pre-Commit Validation:** Test according to impact, not anxiety. Do not run the full test suite after every edit. During development iteration, run only the smallest directly affected target (test case → test class → test file). Before committing, run syntax error checks and targeted tests:

   ```powershell
   uv run --group dev python -m compileall -q <changed_python_paths>
   uv run --group dev pytest -q <targeted-test-path>
   git diff --check
   ```

   Run an optional capability's explicit extra test command too when relevant. Run full required integration suite only before final completion of shared or global core changes. Strictly adhere to the **Targeted Testing & Validation Optimization** rules below.
9. **Large Core Work Must Be Phased:** For cross-cutting work, execute in bounded phases: (1) contract and owner, (2) core implementation, (3) wiring and callers, (4) regression tests, (5) integration and global validation. Complete and validate one phase before expanding. Change only the approved milestone and minimum wiring it requires.
10. **No Fake Success:** Never report or return `SUCCESS`, `COMPLETED`, `READY`, `VALID`, or equivalent unless the required operation actually completed and required validation passed. A capability existing on disk, a function returning, or an artifact path created is not proof of success. Partial, skipped, degraded, fallback, unverified, failed, cancelled, quarantined, or uncommitted work must never be promoted to success. If a required stage fails, the overall operation fails.
11. **Stop & Report:** Stop and report genuine missing prerequisites, contracts, dependencies, or blockers instead of inventing data, default behavior, or another architectural layer. If discovery alters approved scope, get re-approval.
12. **Final Core Drift Check, Commit & Push:** Before completion, verify: one canonical owner remains, no alternate execution paths exist, contracts and implementation agree, registration and wiring are complete, callers use canonical owner, round-trips preserve semantics, lifecycle is singular, no stale code remains, and terminal success is factually proven. Commit one coherent milestone, push immediately when available, and report: purpose, commit hash, branch pushed, files changed, wiring affected, and tests executed.


## Operational Optimization (Tokens & Limits)

- **Smallest Sufficient Context:** Read only canonical owner → relevant contract/Veda section → direct callers → affected tests. Do not reread files already in context.
- **Targeted Line Slicing for Errors:** When inspecting a warning, error, or test failure, read ONLY the precise localized slice (e.g. `StartLine = line - 5`, `EndLine = line + 5`) via `view_file`. Never read entire files or broad 50+ line blocks for localized issues.
- **Zero Polling:** Never poll `manage_task(Action="status")` in a loop while background tasks run. The system resumes execution reactively upon task completion; polling wastes rate limits and tokens.
- **Batching:** Batch related searches and inspections to eliminate redundant roundtrips.


## Planning Checklist

Before touching code, present a plan covering:
- Objective and canonical owner;
- Every file expected to change, and why;
- Exact fix/behavior per file;
- Affected functions, classes, contracts, registrations, and call paths;
- Impact on other modules and compatibility/behavioral risks;
- Targeted tests to add, change, or run;
- Files explicitly not being touched;
- Any unresolved prerequisite or ambiguity.


## Targeted Testing & Validation Optimization

### Core Principle

> **Test according to impact, not anxiety.**
>
> small edit → smallest relevant tests
> subsystem change → subsystem tests
> cross-subsystem boundary change → affected integration tests
> completed global milestone → full project validation once

Do NOT run the full test suite after every edit. The full suite is a final validation tool for cross-cutting work, not the default feedback loop for small changes.


### 1. Change Classification Matrix

Before running tests after an edit, classify the change into one of these levels:

| Level | Classification | Examples | Allowed Test Scope | Prohibited Test Scope |
|---|---|---|---|---|
| **Level A** | Pure Local / Internal | Helper function, parser, detector, converter, formatter, validation rule, private utility, capability-internal branch | Direct unit test file + direct regression test | Full suite, unrelated capabilities, all integration tests |
| **Level B** | Capability Local | OCR, Translation, Font Conversion, Bank Statements, Native Extraction capability logic | Changed component unit tests + capability tests + capability focused E2E | All other Shakti capability suites |
| **Level C** | Shared Boundary | `Result`, `ExecutionContext`, `CanonicalDocument`, `ArtifactPayload`, shared DOCX exporter, Sutra shared data root, Smriti serialization | Direct owner tests + direct consumer tests + focused boundary integration | Full repository suite (unless scope dictates) |
| **Level D** | Core Runtime | Agni, Manthan, Pravaha, Yantra, Prana, Kosh, Dvara, Smriti core behavior, ArtifactBoundary | Owner unit tests + kernel/runtime integration + directly affected capability tests | Full suite after every small internal edit |
| **Level E** | Global / Cross-Cutting | `ExecutionContext` or `Result` contract change, global scheduling, hardware binding, concurrency, cache semantics, artifact commit, lifecycle | Phased focused tests per phase | Full suite after individual file modifications |


### 2. Canonical Change-to-Test Mapping

Inspect `git diff --name-only` and group changed files by canonical owner:

- **Sankalpa (`src/sarathi/sankalpa/*`):**
  - Start with: `uv run --group dev pytest -q tests/sankalpa`
  - If runtime execution affected: add `tests/kernel tests/yantra tests/agni`
  - If consumed by specific capability: add only that capability's tests (e.g. `tests/ocr` or `tests/translation`).
- **Yantra (`src/sarathi/yantra/*`):**
  - Start with: `uv run --group dev pytest -q tests/yantra`
  - If execution behavior changed: add `tests/kernel`
  - If OCR hardware binding changed: `uv run --group dev --extra ocr pytest -q tests/ocr tests/yantra`
  - If Translation hardware binding changed: `uv run --group dev --extra translation pytest -q tests/translation tests/yantra`
  - Do not run Bank/Font tests unless execution contract changed.
- **Pravaha / Manthan / Kernel (`src/sarathi/nabhi/pravaha.py`, `src/sarathi/nabhi/manthan.py`):**
  - Run: `uv run --group dev pytest -q tests/kernel`
  - Add the smallest capability integration test for affected path (e.g. OCR continuation → `tests/kernel` + OCR continuation/E2E; font_conversion resume_self → `tests/kernel` + font_conversion E2E).
  - Do not run unrelated document-domain suites.
- **Prana / Agni (`src/sarathi/nabhi/prana.py`, `src/sarathi/agni/*`):**
  - Run: `uv run --group dev pytest -q tests/agni tests/kernel`
  - Add `tests/yantra` only if lifecycle/resource execution changed.
- **Smriti (`src/sarathi/smriti/*`):**
  - Run: `uv run --group dev pytest -q tests/smriti`
  - For cache-key/serialization changes: add `uv run --group dev pytest -q tests/kernel -k "cache or smriti"`
  - Add capability suite only if cached canonical type is directly affected.
- **Artifact Boundary (`src/sarathi/nabhi/artifacts.py`):**
  - Run: `uv run --group dev pytest -q tests/kernel -k "artifact"` and dedicated artifact tests.
- **OCR (`src/sarathi/shakti/ocr/*`):**
  - Progressive testing: `uv run --group dev --extra ocr pytest -q tests/ocr/<direct_test_file>.py` then `tests/ocr`.
  - Add `tests/kernel` only if continuation, profile propagation, Yantra binding, or runtime behavior changed.
- **Translation (`src/sarathi/shakti/translation/*`):**
  - Progressive testing: `uv run --group dev --extra translation pytest -q tests/translation/<direct_test_file>.py` then `tests/translation`.
  - Add `tests/kernel` only for handoff, resume, profile, execution binding, or Result contract changes.
- **Font Conversion (`src/sarathi/shakti/font_conversion/*`):**
  - Run: `uv run --group dev pytest -q tests/font_conversion`.
  - Add DOCX exporter tests if formatting/output changed; add kernel tests only for continuation/resume changes.
- **Bank Statements (`src/sarathi/shakti/bank_statements/*`):**
  - Run smallest relevant group (e.g. `deduplicator.py` → dedup tests; `mapper.py` → header mapping; `validator.py` → validator; `consolidator.py` → consolidation/export; `capability.py` → bank capability/E2E).
  - Run `tests/bank_statements` only after local component tests pass.
- **Native Extraction (`src/sarathi/shakti/native_extraction/*`):**
  - Run: `uv run --group dev pytest -q tests/native_extraction`.
  - Add OCR continuation tests only if empty content, parse failure, or OCR handoff changed.
- **Shared DOCX Exporter (`src/sarathi/shakti/docx_exporter.py`):**
  - Run: `uv run --group dev pytest -q tests/shakti/test_docx_exporter.py`.
  - Run direct consumers only (e.g. OCR/Translation/Font DOCX tests; do not run Bank tests).
- **Sutra / Configuration (`src/sarathi/sutra/*`, `config/*`):**
  - Run: `uv run --group dev pytest -q tests/configuration`, then direct consumers only.
- **Mukha (`src/sarathi/mukha/*`):**
  - Run: `uv run --group dev pytest -q tests/mukha`.


### 3. Progressive Test Selection & Failure Expansion

- **Exact Selection First:** Prefer exact test cases or keyword expressions over whole directories:
  - Exact test: `uv run --group dev pytest -q tests/yantra/test_allocation.py::TestResourceAllocation::test_preferred_device_allocated_first`
  - Keyword filter: `uv run --group dev pytest -q tests/yantra/test_allocation.py -k "spillover or capacity"`
  - Kernel filter: `uv run --group dev pytest -q tests/kernel -k "resume_self"`
- **Strict Progression Order:**
  `single failing test` → `related test file` → `subsystem suite` → `affected integration tests` → `full suite only when required`
- **Failure Expansion Rule:** If a focused test fails:
  1. Fix the direct defect.
  2. Re-run only that failed test.
  3. When it passes, run the containing test file/group.
  4. Expand outward only when that group passes. Never respond to a focused failure by running the full suite.


### 4. Group Related Edits Before Testing

Do not run tests after every single line or file edit. Complete coherent mini-phases first:
`contract` + `owner implementation` + `direct caller` + `regression test`
Run the focused test group once the mini-phase is coherent.


### 5. Static Checks & Optional Extras Scope

- **Scoped Static Checks:** During local iteration, compile only the affected paths:
  `uv run python -m compileall -q <changed_python_paths>`
  Run full `uv run python -m compileall -q src tests` and `git diff --check` only during milestone/final validation.
- **Scoped Optional Extras:**
  - OCR changes: `--extra ocr`
  - Translation changes: `--extra translation`
  - Core changes: no optional extras unless testing affected integrations.


### 6. Strict Full-Suite Trigger Conditions

Run `uv run --group dev pytest -q` ONLY when at least one condition is met:
- [ ] Approved milestone is complete.
- [ ] Sankalpa public contract changed globally.
- [ ] Pravaha global pipeline semantics changed.
- [ ] Yantra global execution semantics changed.
- [ ] Lifecycle semantics changed globally.
- [ ] Smriti cache representation changed globally.
- [ ] Artifact commit contract changed globally.
- [ ] Multiple capabilities were intentionally modified.
- [ ] Focused testing reveals unexpected cross-subsystem coupling.
- [ ] Preparing final validated commit for a Global/Cross-Cutting change.

NEVER run the full suite for local helpers, single test additions, local parsers, condition adjustments, internal capability branches, or typo fixes.


### 7. Validation Ledger & Truthful State

- Maintain an accurate mental/reported ledger of test execution states (`PASS`, `NOT RUN`, `SKIPPED`).
- Never claim "all tests passed" or "project validated" unless the full suite actually executed.
- Distinguish clearly: *focused tests passed*, *subsystem tests passed*, *integration tests passed*, *full suite passed*, or *not executed*.


### 8. Final Validation Matrix

#### Local Change
Final validation:
- direct regression tests
- affected subsystem tests
- appropriate static check (`uv run python -m compileall -q <changed_python_paths>`)

*No full repository suite unless evidence requires it.*

#### Subsystem Change
Final validation:
- subsystem tests
- affected integration tests
- compile affected packages
- `git diff --check`

#### Global / Cross-Cutting Change
During development:
- phase-specific focused tests

At final milestone only:
```powershell
uv run --group dev pytest -q
uv run python -m compileall -q src tests
git diff --check
```
Then optional-extra full/focused suites relevant to the change.


### 9. Phase-Based Testing Rule

For large implementation work, divide testing by approved phase.

*Example (Yantra performance work):*
- **Phase 1 — Execution Binding:** Run Sankalpa context tests, Yantra binding tests, focused kernel execution tests. Do NOT run OCR/Translation yet unless changed in this phase.
- **Phase 2 — Hardware Discovery:** Run Yantra device inventory/discovery tests, Agni wiring tests, configuration tests.
- **Phase 3 — OCR Hardware Binding:** Run Yantra focused tests, OCR engine/capability tests, OCR binding integration.
- **Phase 4 — Translation Hardware Binding:** Run Yantra focused tests, Translation tests, Translation binding integration.
- **Phase 5 — Queue/Concurrency:** Run Yantra scheduler tests, kernel concurrency tests, cancellation/lifecycle tests.
- **Final Completed Milestone:** Only now run `uv run --group dev pytest -q`, `uv run python -m compileall -q src tests`, `git diff --check`, plus relevant optional extras.


### 10. Test Result Reuse & Validation Ledger

Once a test group passes for code that has not changed since that execution, do not run it again unnecessarily. Re-run a previously passing group only when:
- its owner changed
- its dependency changed
- its canonical contract changed
- a failing integration test implicates it
- final full validation requires it

Keep an internal validation ledger during the task:
```text
Test Group                       Last relevant code state       Result
----------------------------------------------------------------------
Yantra allocation                current phase                 PASS
Sankalpa context                 current phase                 PASS
OCR preprocessing               unchanged since pass          PASS
Translation                     not touched                   NOT RUN
Bank                            unrelated                     NOT RUN
```
Do not claim `PASS` unless it actually ran. `NOT RUN` is valid and preferable to fabricated validation.


### 11. No Fake Validation

Never say:
- "all tests passed"
- "project validated"
- "fully tested"
- "regression-free"

unless the stated tests actually executed successfully. Distinguish clearly:
- focused tests passed
- subsystem tests passed
- integration tests passed
- full suite passed
- not executed
- skipped due optional dependency

A passing focused test is not proof that the entire repository passed.


### 12. Antigravity Execution Rule

Before each pytest invocation:
1. Inspect the changed files since the last successful test run.
2. Identify the canonical owner.
3. Identify direct affected tests.
4. Select the smallest meaningful test group.
5. Explain internally why broader tests are or are not necessary.
6. Run only that group.
7. Expand test scope only after the focused level passes or evidence shows broader impact.

Do not reflexively execute `uv run --group dev pytest -q` after each edit.

> **Test according to impact, not anxiety.**
>
> Local edit $\rightarrow$ local test
> Capability edit $\rightarrow$ capability suite
> Shared boundary $\rightarrow$ owner + direct consumers
> Core runtime $\rightarrow$ core + affected integrations
> Completed global milestone $\rightarrow$ full suite
>
> **The full suite is a final validation tool for cross-cutting work, not the default feedback loop for every small change.**
