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
8. **Test According to Scope & Pre-Commit Validation:** During development iteration, run only the smallest directly affected target (test case → test class → test file). Before committing, run syntax error checks and targeted tests:

   ```powershell
   uv run --group dev python -m compileall -q src
   uv run --group dev pytest -q <targeted-test-path>
   git diff --check
   ```

   Run an optional capability's explicit extra test command too. Run full required integration suite before final completion of shared or global core changes.
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
