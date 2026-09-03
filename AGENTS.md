# Agent Rules for Sarathi

You are implementing Sarathi. `AGENTS.md`, the current `README.md`, and only the relevant Vedas specifications are the complete architectural authority.


## Operating Protocol — The 10 Rules

1. **Plan & Read First:** Read `AGENTS.md`, the relevant README/Veda section, existing source, and affected tests. Present a concise plan and obtain explicit user approval before modifying code, config, docs, or tests.
2. **Canonical Ownership:** Map owner and call path before adding code. Extend an existing owner when it already owns the concern; never create duplicate managers, parallel helpers, or compatibility layers.
3. **Milestone Focus & Clean Replacement:** Change only the approved milestone and the minimum wiring it requires. Delete superseded code in the same change — never leave old and new implementations coexisting.
4. **No Local Re-implementations:** Do not add local telemetry, local caches, local retry logic, alternate registries, global singletons, placeholder data, fake metrics, or generic frameworks.
5. **Respect Subsystem Boundaries:** Use injected services and canonical Sankalpa contracts. Do not bypass Kosh, Manthan, Prana, Yantra, Pravaha, Darpana, Kavacha, or Nabhi when they are the declared owner.
6. **Zero Leaks & Input Safety:** Validate public inputs before state mutation; preserve original exceptions; never expose document contents, raw local paths, secrets, or raw exception messages in public errors, logs, manifests, or telemetry. Never fabricate data or metrics.
7. **Focused Testing:** Add focused positive, negative, and adversarial tests for every changed boundary (malformed, duplicate, missing, foreign, and boundary inputs). Update a Veda only when locked ownership, contracts, or wiring decisions changed.
8. **Pre-Commit Syntax & Targeted Tests:** Run before committing:

   ```powershell
   uv run --group dev python -m compileall -q src
   uv run --group dev pytest -q <targeted-test-path>
   git diff --check
   ```

   Run an optional capability's explicit extra test command too.
9. **Commit, Push & Report:** Commit one coherent milestone only after all checks pass. Push immediately when available. Report: purpose, commit hash, branch pushed, files changed, wiring affected, and tests executed.
10. **Stop & Report:** Stop and report genuine missing prerequisites or blockers instead of inventing data, default behavior, or another architectural layer. If discovery alters approved scope, get re-approval.


## Operational Optimization (Tokens & Limits)

- **Smallest Sufficient Context:** Read only canonical owner → relevant contract/Veda section → direct callers → affected tests. Do not reread files already in context.
- **Targeted Line Slicing for Errors:** When inspecting a warning, error, or test failure, read ONLY the precise localized slice (e.g. `StartLine = line - 5`, `EndLine = line + 5`) via `view_file`. Never read entire files or broad 50+ line blocks for localized issues.
- **Zero Polling:** Never poll `manage_task(Action="status")` in a loop while background tasks run. The system resumes execution reactively upon task completion; polling wastes rate limits and tokens.
- **Batching:** Batch related searches and inspections to eliminate redundant roundtrips.
- **Targeted Testing:** Run only the smallest relevant test target during development (test case → test class → test file).


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
