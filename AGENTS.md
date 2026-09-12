# Agent Rules for Sarathi (Simplified)

Sarathi is a local document-processing application. Prefer direct, modular, maintainable code over framework-like internal architecture.

**Authority:** `AGENTS.md`, the current `README.md`, and only the relevant Vedas docs. Nothing else.

## Priorities

1. **Modularity** — small, single-responsibility modules; no duplicate or repeated logic.
2. Correct and accurate user-visible document processing.
3. Performance — backed by measurement, not assumption.
4. Clear ownership and a small mental model.
5. Reliable tests around real behavior.
6. Security and privacy at actual I/O boundaries.
7. Token-efficient execution — the fewest reads, edits, and tool calls that still satisfy priorities 1–6.

## Core Principle

> Central infrastructure has one source of truth. Plan before editing, propagate core changes through every affected boundary, validate at the right scope, and never call unverified work "done." Save tokens and iterations — never correctness, accuracy, or verification.

## Design Principles

**Modularity First**
Modularity is the top design priority — everything else gets easier when it holds.

- One responsibility has one owner, in one small, cohesive module.
- Every capability has one explicit entry, dependency, result, and failure path.
- Split by responsibility, not for abstraction's sake — don't create a module just to have one.
- Broken, dangling, duplicate, bypass, or hidden alternate wiring is rejected.
- Shared infrastructure is implemented once, globally — capabilities never rebuild it locally.
- Superseded managers, contracts, stores, and execution paths are removed in the same change — old and new never coexist.
- Pravaha alone owns failure isolation, quarantine, and retry.

**No Duplicate, No Repetitive Code**

- The same logic is written once. A repeated block is a signal to extract it into a shared, owned function or module — not to copy-paste it again.
- Before writing new logic, check whether an existing module already does it.
- A second near-identical implementation of the same behavior gets refactored, not accepted.

**No Overengineering**
Build only what's needed now — no speculative managers, frameworks, services, or abstraction layers ahead of demonstrated need.

**Modern Tools — Only When ROI Is High**

- Prefer modern, actively maintained languages, libraries, and tools over custom or legacy ones — but only adopt something new when the payoff (correctness, maintainability, performance, security) clearly beats the migration and learning cost.
- Novelty alone is never a reason to rewrite working code.
- When proposing a new dependency or tool, state the concrete ROI as part of the plan: what it replaces, what it saves.

**Tiny Core, Plugin Features**
Nabhi (core kernel) handles plugins, capabilities, lifecycle, and execution. Shakti (plugin ecosystem) holds all document-intelligence logic — OCR, translation, banking, conversion, extraction.

**Where Things Belong**

- Prefer plain modules, functions, dataclasses, and mature libraries. Add a manager/service/registry only when it owns real state or policy.
- Domain behavior stays in the owning Shakti capability.
- Shared contracts live in Sankalpa only when multiple real consumers need them.
- Planning lives in Manthan; execution lives in Pravaha.
- Generic device/concurrency policy lives in Yantra; capability-specific workload behavior stays with the capability.
- HTTP/API translation lives in Mukha — document-processing decisions never move into the web layer.
- Security stays fail-closed at actual I/O/capability boundaries.

## Subsystem Ownership

| Subsystem | Owns |
| --- | --- |
| `agni` | Composition and process lifecycle |
| `sankalpa` | Shared request/result/document contracts |
| `nabhi` | Physical namespace holding Kosh, Manthan, Pravaha, artifact/quarantine support, and deprecated Prana compatibility |
| — Kosh | Declarations and registry storage |
| — Manthan | Initial and continuation planning |
| — Pravaha | Execution of the plan Manthan returns |
| `shakti` | Document-processing capabilities and provider adapters |
| `yantra` | Execution/device resource helpers |
| `kavacha` | Security authorization and path/privacy checks at real boundaries |
| `smriti` | Optional result cache |
| `darpana` | Runtime/quality events and history |
| `sutra` | Runtime settings |
| `mukha` | Presentation, local web transport, frontend state |
| `dosh` | Shared error vocabulary |

`nabhi` is a namespace, not a second decision authority — never add a second registry, planner, execution engine, device-policy owner, or security gateway.

## Canonical Architecture & Manifest

- `Vedas/architecture.manifest.json` declares production topology. Code topology and the manifest change together.
- Every top-level subsystem under `src/sarathi` must be declared in the manifest; its immediate modules/packages must appear as that subsystem's `components`.
- The manifest is not an inventory of private implementation files, assets, CSS, or fixtures.
- A new architectural layer needs a concrete current responsibility — prefer deletion or an existing owner over a new wrapper.
- Architecture tests must fail when production topology and the manifest diverge.

## Core Rules

1. **Plan before touching core code.** Identify the canonical owner, affected contracts, callers, wiring, caches, and tests. Get explicit approval before editing.
2. **One owner, one path.** No parallel managers, registries, caches, retries, or hidden fallbacks. Everything else consumes the core decision — it never reimplements it.
3. **Propagate core changes completely.** A change isn't done until every contract, caller, wiring point, serializer, and test agrees. Delete superseded code in the same change — old and new never coexist.
4. **Preserve state across every path.** Fresh run, cache hit, resume, retry, and serialize/deserialize must all produce the same result. No field silently drops.
5. **Respect subsystem ownership.** Use injected services and Sankalpa contracts. Don't bypass Kosh, Manthan, Pravaha, Yantra, Darpana, Kavacha, or Nabhi when one of them is the declared owner.
6. **Fail safe, stay honest.** Validate inputs before mutating state. Never leak document contents, local paths, secrets, or raw exceptions. Never invent defaults, confidence, or availability — unknown stays unknown.
7. **Tests follow the architecture, not the reverse.** If a test contradicts `AGENTS.md`, the README, or a locked Veda, fix the test — not production behavior.
8. **No fake success.** "Done" means it ran *and* was verified. Partial, skipped, degraded, or uncommitted work is never reported as success.
9. **Stop and ask** when a prerequisite is missing or scope changes — don't improvise around it.
10. **New files or folders need explicit approval first.** No unapproved structural changes.
11. **Before every commit:** compile the changed files, run the targeted tests, `git diff --check`.
12. **Phase large changes:** contract → implementation → wiring → tests → integration. Validate each phase before starting the next.
13. **Before calling anything complete,** confirm: one owner remains, no duplicate paths exist, contracts match implementation, and report the commit hash, files touched, and tests run.

## Change Workflow

- Single main branch. All work happens directly on it — no feature, cleanup, migration, or temporary branches.
- For cross-cutting changes, in order:
  1. Preserve user-visible behavior and public payloads.
  2. Identify the canonical owner.
  3. Make one coherent simplification.
  4. Migrate all callers, tests, configuration, and documentation.
  5. Remove obsolete paths instead of keeping permanent compatibility duplicates.
  6. Update the architecture manifest when topology or ownership changes.
  7. Search globally for stale names, imports, or configuration.
  8. Run targeted checks, then all permanent CI gates.
  9. Commit only when the exact final tree is green.

## Context & Token Discipline

Token efficiency is a standing constraint, not an afterthought — the smallest sufficient context and the smallest sufficient action always wins over a broader default.

- Read only: canonical owner → relevant contract/spec → direct callers → affected tests. Don't reread what's already in context.
- For a specific error or failing test, view ~10 lines around the failing line — not the whole file.
- Never poll task status in a loop; the system resumes reactively.
- Batch related searches instead of repeating round-trips.

## Testing Philosophy

**Test according to impact, not anxiety.**

| Change size | Run |
| --- | --- |
| Local helper, parser, formatter | Its unit test + direct regression test |
| One capability (OCR, translation, bank statements, font conversion, native extraction) | That capability's test suite |
| Shared contract (`Result`, `ExecutionContext`, canonical document, artifact payload) | Owner tests + direct consumers |
| Core runtime (Agni, Manthan, Pravaha, Yantra, Kosh, Prana) | Owner tests + directly affected capability tests |
| Global/cross-cutting contract change | Phased tests per phase — full suite only at the final milestone |

**On failure:** fix the defect → re-run only that test → once it passes, run its file → then its subsystem → then affected integration tests. Never jump straight to the full suite for a focused failure.

**Run the full suite** (`uv run --group dev pytest -q`) only when: a milestone is complete, a contract changed globally, multiple capabilities were intentionally touched, or focused testing revealed unexpected cross-subsystem coupling. Never run it for typo fixes, single-test additions, or local branch logic.

**Report truthfully.** Keep a plain ledger — PASS / NOT RUN / SKIPPED. Never say "all tests passed" or "fully validated" unless the full suite actually ran.

## Validation Bar

- Changed Python must compile, Ruff must stay clean, and targeted tests must pass; milestone work must additionally pass the full permanent CI suite.
- Never report a migration, cleanup, performance improvement, or CI state that wasn't actually verified on the exact tree being promoted.
- Don't optimize based on test-only numbers.
- Never weaken a behavioral test just to push through a cleanup pass.
- Modularity and any new tool/library adoption must never regress measured performance or output accuracy — if a refactor trades either away, it doesn't ship as-is.

## Planning Checklist (before touching code)

- Objective and canonical owner
- Every file expected to change, and why
- Any proposed new file/folder (needs explicit approval)
- Affected functions, contracts, and call paths
- Tests to add, change, or run
- What's explicitly *not* being touched
- Open questions or blockers
