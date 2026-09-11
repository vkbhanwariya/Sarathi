# Sarathi Development Rules

Sarathi is a local document-processing application. Prefer direct, maintainable code over framework-like internal architecture.

## Priorities

1. Correct user-visible document processing.
2. Clear ownership and a small mental model.
3. Reliable tests around real behavior.
4. Security and privacy at actual I/O boundaries.
5. Performance changes backed by measurement.

## Canonical architecture

`Vedas/architecture.manifest.json` declares the production topology. Production code topology and the manifest must change together.

- Every top-level production subsystem under `src/sarathi` must be declared in the manifest.
- Immediate Python modules/packages inside a declared subsystem must be represented by that subsystem's `components`.
- Do not turn the manifest into an inventory of private implementation files, assets, CSS, or fixtures.
- New architectural layers require a concrete current responsibility.
- Prefer deletion or an existing owner over moving code sideways into a new wrapper.
- Architecture tests must fail when production topology and the manifest diverge.

## Current ownership

- `agni`: composition and process lifecycle.
- `sankalpa`: shared request/result/document contracts.
- `nabhi`: physical namespace containing Kosh, Manthan, Pravaha, and artifact/quarantine support.
- Kosh: declarations and registry storage.
- Manthan: initial and continuation planning.
- Pravaha: execution of the plan returned by Manthan.
- `shakti`: document-processing capabilities and provider adapters.
- `yantra`: execution/device resource helpers.
- `kavacha`: security authorization and path/privacy checks at real boundaries.
- `smriti`: optional result cache.
- `darpana`: runtime/quality events and history.
- `sutra`: runtime settings.
- `mukha`: presentation, local web transport, and frontend state.
- `dosh`: shared error vocabulary.

`nabhi` is a namespace, not an additional decision authority. Do not add a second registry, planner, execution engine, device-policy owner, or security gateway.

## Change workflow

The repository has two working branches:

- `development`: active development;
- `main`: stable and validated.

Do not create routine feature, cleanup, migration, or temporary branches. For cross-cutting changes:

1. preserve user-visible behavior and public payloads;
2. identify the canonical owner;
3. make one coherent simplification;
4. migrate all callers, tests, configuration, and documentation;
5. remove obsolete paths instead of keeping permanent compatibility duplicates;
6. update the architecture manifest when topology or ownership changes;
7. search globally for stale names/imports/configuration;
8. run targeted checks, then all permanent CI gates;
9. promote only when the exact final tree is green.

## Design rules

- Prefer plain modules, functions, dataclasses, and mature libraries.
- Add a manager/service/registry only when it owns real state or policy.
- Keep domain behavior in the owning Shakti capability.
- Keep shared contracts in Sankalpa only when multiple real consumers need them.
- Keep planning in Manthan and execution in Pravaha.
- Keep generic device/concurrency policy in Yantra; capability-specific workload behavior stays with the capability.
- Keep HTTP/API translation in Mukha; do not move document-processing decisions into the web layer.
- Keep security fail-closed at actual I/O/capability boundaries.
- Do not optimize based on test-only numbers.
- Never weaken a behavioral test merely to make a cleanup pass.

## Validation and truthfulness

Validate according to impact. At a minimum, changed Python should compile, Ruff should remain clean, targeted tests should pass, and milestone work must pass the permanent CI suite.

Never report a migration, cleanup, performance improvement, or CI state that was not actually verified on the exact tree being promoted.
