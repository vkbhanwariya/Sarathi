# Sarathi Architecture

## Purpose

Sarathi is a local-first document intelligence system. Its architecture separates composition, planning, execution, document capabilities, resource policy, security, state, and presentation so each important decision has one clear owner.

## Runtime flow

```text
input paths / browser request
          |
          v
       Mukha or CLI
          |
          v
         Agni
    composition/lifecycle
          |
          v
Kosh declarations + Manthan planning
          |
          v
       Pravaha
    pipeline execution
          |
          v
       Shakti
 document capabilities
          |
          v
staged -> validated -> committed artifacts
```

Kavacha, Yantra, Smriti, and Darpana support this flow without taking over planning or domain decisions.

## Ownership table

| Owner | Responsibility | Must not become |
| --- | --- | --- |
| Agni | Application composition, bootstrap, lifecycle | A second planner or capability implementation layer |
| Kosh | Plugin/capability declarations and registry validation | An execution engine |
| Manthan | Requirement resolution, dependencies, profiles, continuation planning | A runtime worker pool |
| Pravaha | Execute Manthan's plan; cancellation/retry/handoff execution flow | A competing planner |
| Shakti | Native extraction, OCR, translation, conversion, bank/document capabilities, provider adapters | Generic application orchestration |
| Yantra | Device inventory/allocation and generic execution-resource policy | Capability-specific OCR strategy |
| Kavacha | Authorization, path safety, privacy/network policy at real boundaries | Credential vault, HTTP proxy, or synthetic gateway |
| Smriti | Optional reusable result cache | Source of truth for active execution |
| Darpana | Runtime/quality events and retained history | A parallel application state model |
| Mukha | Presentation state, local HTTP/SSE transport, frontend integration | Document-processing/planning authority |
| Sankalpa | Shared request/result/document/cancellation contracts | Business logic owner |
| Sutra | Runtime settings loading/contracts | Policy duplication |
| Dosh | Shared error vocabulary | Control-flow framework |

## Physical namespace versus decision ownership

`src/sarathi/nabhi/` contains Kosh, Manthan, Pravaha, and artifact/quarantine support. This package layout is physical organization only. Architectural authority remains split by responsibility: Kosh declares, Manthan plans, Pravaha executes.

## Security boundary

Sarathi is local-first. Mukha binds only to loopback. Kavacha validates path access and authorizes capability/provider declarations before sensitive execution. Provider-specific clients own their actual outbound HTTP requests and credential-value lookup. Security documentation must match the code path where data can actually leave the machine.

## Artifact boundary

Final outputs must not appear as successful artifacts until processing has completed and the output path is authorized. Temporary/staged writes, finalization, containment validation, and run/artifact identity protect against partial or cross-run access.

## Architecture invariants

- One planning authority: Manthan.
- One plan execution authority: Pravaha.
- One declaration registry: Kosh.
- Generic device/concurrency policy belongs to Yantra.
- Capability-specific processing strategy belongs to the capability.
- HTTP routing and response translation belong to Mukha/Starlette.
- Security stays fail-closed at real boundaries.
- Removed architecture is deleted rather than maintained in parallel.
- Performance changes require a measured baseline and post-change measurement.
- Production topology and `architecture.manifest.json` must agree.

## Machine-readable topology

`architecture.manifest.json` lists top-level production modules and their immediate components. `tests/architecture/manifest_validator.py` and architecture tests enforce the manifest against `src/sarathi`.
