# Agent Rules for Sarathi

You are implementing Sarathi. `AGENTS.md`, the current `README.md`, and only
the relevant Vedas files are the complete architectural authority.


## 1. Plan First — Then Get Explicit Approval

- Do not touch production code, tests, config, or docs before a plan is approved.
- Read only what's needed to understand the change: `AGENTS.md`, the assigned
  README/Vedas sections, the canonical owner, current source, direct callers,
  and current tests. Expand investigation only when evidence shows another
  module, contract, or boundary is affected.
- Present a plan stating:
  - the objective and the canonical owner of the behavior;
  - every file expected to change, and why;
  - the exact fix/behavior per file;
  - affected functions, classes, contracts, registrations, call paths;
  - impact on other modules and existing behavior;
  - compatibility/behavioral risks;
  - tests to add, change, or run;
  - files explicitly **not** being touched;
  - any unresolved prerequisite or ambiguity.
- **Do not start coding until the user explicitly approves the plan.**
- If investigation after approval reveals a material change to scope,
  architecture, affected files, or behavior — stop and get re-approval.
  Minor implementation details that don't change approved scope/behavior
  don't need re-approval.

## 2. Ownership & Architecture

- One responsibility = one canonical owner.
- Before adding code, search for an existing Sarathi contract, service, or
  helper that already provides the behavior, and extend that owner.
- Never create: duplicate managers/services, parallel helpers, alternate
  execution paths or registries, hidden fallbacks/defaults, compatibility
  layers without an explicit requirement, global singletons, speculative
  frameworks/abstractions, placeholders, or fake metrics.
- Remove superseded code in the same change — never leave old and new
  implementations coexisting.
- A change is incomplete if implementation, contracts, registration, wiring,
  callers, tests, and architectural docs disagree with each other.
- If a required decision or contract is missing, **stop and report it** —
  do not invent a workaround.

## 3. Scope & Code Quality

- Implement only the approved milestone and its minimum necessary wiring.
  No unrelated cleanup, no starting the next module.
- Edit README/Vedas only if explicitly asked, or if a locked ownership/
  contract/wiring decision changes as a direct result of this task.
- Export only intentional public APIs; keep helpers internal.
- Use modern, idiomatic Python 3.13+ stdlib features where they genuinely
  simplify things (`match/case`, comprehensions, `:=`, `contextlib`,
  dataclasses, enums, dispatch tables).
- Prefer one focused helper over repeated `if/elif` chains or duplicated blocks.
- Split files only by genuine responsibility — never by line count alone.
- If a change looks like it needs >~250–300 new production LOC, stop and
  reconsider whether an existing Sarathi component already supplies the behavior.
- No defensive-code explosion: every added block must map to a concrete
  Veda/task requirement or a demonstrated failure case.
- Preserve readability, ownership, behavior, validation order, and exception
  semantics. No abstraction or cleverness purely for style.

## 4. Correctness & Safety

- Validate public inputs before any state mutation or work execution.
- Use strict types; validate cross-field and cross-contract consistency.
- Prevent partial mutation on failure.
- Preserve the original exception unless the task explicitly requires a
  canonical error boundary.
- Never expose secrets, credentials, document/payload contents, raw local
  paths, or raw exception text in errors, logs, telemetry, or context.
- Never fabricate data, metrics, confidence, accuracy, hardware facts,
  dependency availability, or runtime defaults. Unknown facts stay unknown.

## 5. Token & Context Efficiency

- Start with the smallest sufficient context: canonical owner → relevant
  contract/architecture section → direct callers → affected tests.
- Search for symbols/imports/references/registrations before opening large
  files; read only the relevant sections of large files.
- When inspecting an error, failure, or warning, read ONLY the precise line of
  code where the warning or error came (e.g. `StartLine = line - 5`, `EndLine = line + 5`)
  via `view_file`. Never read entire files or broad 50+ line blocks for a localized error.
- Never poll `manage_task(Action="status")` in a loop while background tasks run.
  The agent framework notifies reactively upon task completion; polling wastes
  significant token quota and rate limits.
- Don't reread files already available in context, or restate established
  architectural facts.
- Batch related searches/inspections to avoid redundant tool calls.
- Efficiency never skips a required contract, caller, architectural check,
  safety check, regression test, or correctness analysis.

## 6. Phased Execution (larger tasks)

For work spanning many files or architectural boundaries, use bounded phases,
each with one objective and its own validation — don't load or change the
whole scope at once:

1. **Discovery** — owner, contracts, callers, wiring, tests, scope.
2. **Core implementation** — canonical owner/contract.
3. **Wiring** — registration, composition, callers.
4. **Regression coverage** — focused positive + adversarial tests.
5. **Integration validation** — affected modules together.
6. **Repository validation** — broader checks, when justified by scope.
7. **Commit & push.**

Carry conclusions from completed phases forward instead of rebuilding
context. If a later phase disproves an earlier assumption, fix the root
cause — don't add compensating code downstream.

## 7. Testing

- Add focused happy-path and adversarial tests for every changed boundary.
  Prefer parameterized/table-driven tests over copied test bodies.
- Cover malformed, duplicate, missing, tampered, foreign, double-use, and
  partial-mutation cases where relevant.
- Verify immutable snapshots don't expose mutable internal state.
- After a local/minor change, run only the smallest sufficient target, in
  order of preference: specific test case → test class → test file →
  module/package tests. Don't run the full suite for every small edit.
- Run full validation only when the change touches a shared contract,
  canonical runtime wiring, dependency resolution, registration, shared
  infrastructure, or system-wide behavior (error handling, telemetry,
  caching, security, artifacts, lifecycle):

  ```bash
  uv run --group dev pytest -q --tb=short --show-capture=no
  uv run --group dev python -m compileall -q src
  git diff --check
  ```

- For an optional capability, also run its explicit extra test command.
- Don't rerun broad validation unless a subsequent change could invalidate
  its result.

## 8. Commit & Push

- Commit only after the approved implementation passes all required tests
  and validation — one coherent milestone, never mixed with unrelated changes.
- Review the final diff before committing; write a clear message describing
  the implemented behavior.
- Don't claim a commit succeeded unless it actually did.
- Push the committed branch after a successful commit, when push access is available.
- Never force-push, rewrite shared history, or push directly to a protected
  branch, unless the user explicitly requests it and repo policy allows it.
- If push fails (permissions, auth, branch protection, remote state):
  preserve the local commit, don't invent a workaround, and report the exact
  blocker and commit hash.

## 9. Stop Conditions

Stop and report — never invent a substitute — on:

- a missing contract, architectural decision, dependency, credential, or permission;
- a repository state that blocks the approved plan;
- any other genuine prerequisite gap.

If the gap changes the approved plan, get re-approval before continuing.

## 10. Final Report

- Purpose of the change
- Commit hash & branch pushed
- Files changed
- Behavior implemented
- Canonical owner & call path affected
- Wiring affected
- Tests added/changed, and test count
- Tests executed & result; broader validation run, if any
- Explicitly deferred items
- Blockers, if any

Don't reproduce large diffs, full source files, or long logs unless asked.

---

**Primary rule:** Investigate minimally but sufficiently → plan → get
explicit user approval → implement only the approved scope → validate
proportionally (focused for local changes, broad for cross-cutting ones) →
commit → push → report concisely. Preserve canonical ownership and
architectural consistency throughout.
