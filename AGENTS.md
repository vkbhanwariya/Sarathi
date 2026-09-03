# Agent Rules for Sarathi

You are implementing Sarathi. `AGENTS.md`, the current `README.md`, and only the relevant Vedas specifications are the complete architectural authority.


## Operating Protocol — Apply to Every Task

1. Read `AGENTS.md`, the relevant README/Veda section, existing source, and affected tests before editing.
2. Map the owner and call path before adding a file. Extend an existing owner when it already owns the concern.
3. Change only the named milestone and the minimum wiring it requires.
4. Do not add local telemetry, local caches, local retry logic, alternate registries, global singletons, placeholder data, fake metrics, or generic frameworks.
5. Use injected services and canonical Sankalpa contracts. Do not bypass Kosh, Manthan, Prana, Yantra, Pravaha, Darpana, Kavacha, or Nabhi when they are the declared owner.
6. Public errors, telemetry, manifests, logs, and presentation must not expose document contents, raw local paths, secrets, or raw exception messages.
7. Add focused positive and negative tests for every changed boundary. Update a Veda only when a locked ownership, contract, or wiring decision changed.
8. Run before committing:

   ```powershell
   uv run --group dev pytest -q
   uv run --group dev python -m compileall -q src
   git diff --check
   ```

   Run an optional capability's explicit extra test command too.
9. Commit one coherent milestone only after all checks pass. Report: purpose, changed files, wiring affected, tests run, and commit hash.
10. Stop and report a genuine missing prerequisite instead of inventing data, default behavior, or another architectural layer.


## 1. Plan First — Then Get Explicit Approval

- Do not touch production code, tests, config, or docs before a plan is approved.
- Present a concise plan stating:
  - Objective and canonical owner;
  - Every file expected to change, and why;
  - Exact fix/behavior per file;
  - Affected functions, classes, contracts, registrations, and call paths;
  - Impact on other modules and compatibility/behavioral risks;
  - Tests to add, change, or run;
  - Files explicitly not being touched;
  - Any unresolved prerequisite or ambiguity.
- **Do not start coding until the user explicitly approves the plan.**
- If discovery reveals a material scope or architectural change, stop and get re-approval.


## 2. Ownership & Anti-Pileup

- **One responsibility = one canonical owner.**
- Before adding code, search for an existing Sarathi contract, service, or helper and extend that owner.
- Never create duplicate managers, parallel helpers, alternate execution paths/registries, hidden fallbacks, compatibility layers without explicit requirements, global singletons, or speculative frameworks.
- Delete superseded code in the same change — never leave old and new implementations coexisting.
- A change is incomplete if code, contracts, registration, callers, tests, and Vedas disagree.


## 3. Token & Usage Limit Optimization

- **Smallest sufficient context:** Canonical owner → relevant contract/Veda section → direct callers → affected tests. Do not reread files already in context.
- **Targeted line slicing for errors:** When inspecting a warning, error, or test failure, read ONLY the precise localized slice (e.g. `StartLine = line - 5`, `EndLine = line + 5`) via `view_file`. Never read entire files or broad 50+ line blocks for localized issues.
- **Zero polling:** Never poll `manage_task(Action="status")` in a loop while background tasks run. The system resumes execution reactively upon task completion; polling wastes rate limits and tokens.
- **Batching:** Batch related searches and tool inspections to eliminate redundant roundtrips.
- **Proportional testing:** Run only the smallest relevant test target during development (test case → test class → test file). Run full repository validation only before final commit.


## 4. Correctness, Safety & Zero Leaks

- **Validate public inputs** before any state mutation or execution; prevent partial mutation on failure.
- **Strict typing:** Validate cross-field and cross-contract consistency. Use Python 3.13+ idiomatic stdlib features (`match/case`, comprehensions, `:=`, `contextlib`, dataclasses, enums).
- **Preserve original exceptions** unless an explicit canonical error boundary is required.
- **Zero leaks:** Never expose secrets, credentials, document/payload text, raw local filesystem paths, or raw exception messages in errors, logs, telemetry, manifests, or context.
- **No fabrication:** Never fabricate data, metrics, confidence, accuracy, hardware facts, dependency availability, or runtime defaults. Unknown facts stay unknown.


## 5. Testing Policy

- Add focused happy-path and adversarial tests for every changed boundary (malformed, duplicate, missing, foreign, and boundary inputs). Prefer parameterized/table-driven tests.
- Verify immutable snapshots do not expose mutable internal state.
- Before committing, always run the full canonical validation:

  ```powershell
  uv run --group dev pytest -q
  uv run --group dev python -m compileall -q src
  git diff --check
  ```


## 6. Commit, Push & Final Report

- Commit only after the approved implementation passes all required tests — one coherent milestone per commit, never mixed with unrelated changes.
- Push the committed branch immediately when push access is available. Never force-push or rewrite shared history.
- If push fails (permissions, auth, branch protection), preserve the local commit and report the exact blocker.
- **Final Report Structure:**
  - Purpose of the change;
  - Commit hash & branch pushed;
  - Files changed & behaviors implemented;
  - Canonical owner, call paths, and wiring affected;
  - Tests added/changed, tests executed, and results;
  - Blockers or deferred items, if any.
