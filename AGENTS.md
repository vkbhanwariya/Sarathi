# Agent Rules for Sarathi

You are implementing Sarathi. `AGENTS.md`, the current `README.md`, and only
the relevant Vedas files are the complete architectural authority.

## Before editing:
- Read `AGENTS.md`, the assigned README/Vedas sections, current source, current
  callers, and current tests.
- Preserve existing approved contracts and tests.
- Map the owner and canonical call path before adding a file or dependency.
- Before starting coding, first tell the user what files you are going to change and what these changes make difference and effect of these changes.

## Ownership & Architecture:
- One responsibility = one owner.
- Reuse injected global services. Keep the core lightweight; capability
  dependencies remain optional.
- Minimize code, not just duplication. Before adding code, search for an
  existing Sarathi contract/service/helper that already provides the behavior
  and reuse it.
- Prefer existing owner APIs over new abstractions. Do not create parallel
  helpers, wrappers, duplicate managers, replacement services, alternate
  execution paths, generic frameworks, hidden defaults, global singletons,
  compatibility aliases, placeholders, fake metrics, or speculative infrastructure.
- If a required decision or contract is missing, stop and report it. Do not invent a workaround.

## Scope & Code Quality:
- Implement only the requested milestone and the minimum necessary wiring.
- Do not change unrelated architecture or start the next module.
- Do not edit README/Vedas unless explicitly asked or a locked ownership,
  contract, or wiring decision changes as a direct result of the task.
- Export only intentional public APIs. Keep helpers internal.
- Prefer modern, idiomatic Python 3.13+ stdlib and concise language features
  where they genuinely simplify implementation (e.g. `match/case`, comprehensions,
  assignment expressions, `contextlib`, dataclasses, enums, mappings/dispatch
  tables, focused helpers, and standard-library APIs).
- Prefer one focused helper over repeated branches. Reduce repetitive
  `if/elif/else` chains, duplicated blocks, and boilerplate.
- Avoid files becoming monolithic; split only by genuine responsibility, not
  arbitrary line count.
- Do not expand a production module by hundreds of lines unless the task
  genuinely introduces that much new responsibility. If a change appears to
  require >~250–300 new production LOC, first reconsider whether existing
  Sarathi components can supply the behavior.
- No "defensive code explosion." Every added block must implement a concrete
  Veda/task requirement or necessary regression.
- Delete superseded code instead of layering new code beside it.
- Preserve readability, canonical ownership, behavior, validation order,
  exception semantics, and tests. Do not introduce abstraction or cleverness purely for style.

## Correctness & Safety:
- Validate public inputs before state mutation or work execution.
- Use strict types and validate cross-field consistency.
- Prevent partial mutation on failure.
- Preserve original exceptions unless the task explicitly requires a canonical error boundary.
- Never expose secrets, credentials, document content, raw paths, payloads, or raw exception text in errors, logs, telemetry, or context.
- Do not fabricate metrics, confidence, accuracy, hardware facts, or runtime defaults.
- Unknown facts remain unavailable.

## Testing:
- Add focused happy-path and adversarial tests.
- Prefer parameterized/table-driven tests over copied test bodies.
- Cover malformed, duplicate, missing, tampered, foreign, double-use, and partial-mutation cases where relevant.
- Verify immutable snapshots do not expose mutable internal state.

## Before commit:
```bash
uv run --group dev pytest -q
uv run --group dev python -m compileall -q src
git diff --check
```

- For an optional capability, also run its explicit extra test command.
- Commit one coherent milestone only after all required checks pass.

## Final report:
- commit hash;
- files changed;
- behavior implemented;
- owner and canonical call path affected;
- explicitly deferred items;
- test count;
- blockers.
