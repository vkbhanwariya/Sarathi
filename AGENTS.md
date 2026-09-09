# Sarathi Development Rules

Sarathi is a local document-processing application. Prefer simple, direct code over framework-like internal architecture.

## Priorities

1. Correct user-visible document processing.
2. Clear code and small mental model.
3. Reliable tests around real behavior.
4. Security and privacy at actual I/O boundaries.
5. Performance only where measurement shows it matters.

## Architecture Rules

- Prefer plain modules, functions, and dataclasses. Add a manager/service/registry only when it owns real state or policy that cannot be simpler.
- Do not create an abstraction only to preserve symmetry, naming, or a future possibility.
- Reuse mature libraries for generic infrastructure (HTTP, routing, serialization, concurrency) unless Sarathi has a demonstrated requirement they cannot satisfy.
- Capability packages may use shared public helpers. Cross-capability imports are allowed when they represent a stable reusable utility; avoid importing another capability's private implementation.
- Keep one decision authority where conflicting decisions would be dangerous, but do not interpret this as "only one module may touch the concern".
- New files inside an existing subsystem do not require special approval. New top-level architectural layers should have a concrete present-day reason.
- Backward-compatibility shims are temporary. Remove them when no active caller requires them.
- File size is not an architectural rule. Split by cohesion and responsibility, not byte count.

## Current Runtime Boundaries

These are practical responsibilities, not isolated pseudo-domains:

- `agni`: application composition/startup.
- `sankalpa`: shared request/result/document contracts.
- `nabhi`: pipeline execution and capability resolution.
- `shakti`: document-processing capabilities and provider adapters.
- `sutra`: settings.
- `kavacha`: security authorization and path/privacy checks.
- `darpana`: lightweight runtime/quality events and history.
- `smriti`: optional result cache.
- `yantra`: execution/device helpers.
- `mukha`: user interface.
- `dosh`: shared error vocabulary.

Prefer collapsing these boundaries when doing so removes indirection without changing behavior.

## Change Workflow

Before editing, understand the direct behavior, callers, and tests affected. For ordinary implementation work, proceed without ceremony. Ask for user approval only when the requested outcome is ambiguous, an irreversible user-data operation is involved, or a materially different product/architecture direction is being introduced.

For cross-cutting refactors:
1. preserve behavior,
2. make one coherent simplification,
3. migrate callers,
4. remove obsolete paths,
5. validate the affected behavior.

Do not keep old and new architecture permanently in parallel.

## Testing

Test according to impact:

- local helper change -> direct unit/regression tests;
- capability change -> that capability's tests;
- shared contract/runtime change -> direct consumers plus focused integration tests;
- global milestone -> full suite once.

Useful final checks:

```powershell
uv run --group dev python -m compileall -q <changed-python-paths>
uv run --group dev pytest -q <targeted-tests>
git diff --check
```

Run the full suite only for genuinely cross-cutting changes or final global validation.

Tests protect product behavior and stable public contracts. They must not force arbitrary architecture such as file-size ceilings, package symmetry, or unnecessary isolation.

## Safety and Truthfulness

- Validate public inputs before destructive or persistent mutation.
- Do not expose secrets, raw document contents, or private paths through telemetry/errors.
- Do not fabricate confidence, readiness, success, or dependency availability.
- Preserve the primary exception when cleanup also fails.
- Never report completion or validation that was not actually performed.

## Simplicity Check

Before adding infrastructure, ask:

1. Does current product behavior require it?
2. Is there a simpler standard-library or mature-library solution?
3. Will this reduce total code/coupling rather than move it?
4. Does it have at least one concrete current consumer?
5. Can a future need be added later without blocking today's implementation?

If the simple solution works, use it.
