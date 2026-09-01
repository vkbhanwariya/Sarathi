# Agent Rules for Sarathi

You are implementing Sarathi. `AGENTS.md`, the current `README.md`, and only
the relevant Vedas files are the complete architectural authority.

## Before editing:
- Read `AGENTS.md`, the assigned README/Vedas sections, current source, current
  callers, and current tests.
- Preserve existing approved contracts and tests.
- Map the owner and canonical call path before adding a file or dependency.

## Rules:
- Before starting coding first tell the user what files are you going to change and what these changes made difference and effect of these changes
- One responsibility = one owner.
- Reuse injected global services. Keep the core lightweight; capability
  dependencies remain optional.
- No duplicate managers, parallel services, alternate execution paths, local
  telemetry, local replacement services, generic frameworks, hidden defaults,
  global singletons, compatibility aliases, placeholders, fake metrics, or
  speculative infrastructure.
- Use existing public contracts/services unless the assigned milestone
  explicitly introduces its one canonical contract or owner.
- If a required decision or contract is missing, stop and report it. Do not invent a workaround.

## Scope:
- Implement only the requested milestone and the minimum necessary wiring.
- Do not change unrelated architecture or start the next module.
- Do not edit README/Vedas unless explicitly asked or a locked ownership,
  contract, or wiring decision changes as a direct result of the task.
- Export only intentional public APIs. Keep helpers internal.

## Correctness:
- Validate public inputs before state mutation or work execution.
- Use strict types and validate cross-field consistency.
- Prevent partial mutation on failure.
- Preserve original exceptions unless the task explicitly requires a canonical error boundary.
- Never expose secrets, credentials, document content, raw paths, payloads, or raw exception text in errors, logs, telemetry, or context.
- Do not fabricate metrics, confidence, accuracy, hardware facts, or runtime defaults.
- Unknown facts remain unavailable.

## Testing:
- Add focused happy-path and adversarial tests.
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
