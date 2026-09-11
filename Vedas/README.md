# Vedas — Sarathi Engineering Guide

`Vedas/` is the current engineering documentation for Sarathi. It explains the architecture that exists now, the responsibilities of each subsystem, the supported capability families, the local web transport, and the ordered cleanup roadmap.

## Start here

| Document | Use it for |
| --- | --- |
| [`Architecture.md`](Architecture.md) | Runtime flow, subsystem ownership, boundaries, and invariants |
| [`Capabilities.md`](Capabilities.md) | Current document-processing capability families and provider model |
| [`Mukha_Transport.md`](Mukha_Transport.md) | Local web server, HTTP/SSE ownership, and security boundary |
| [`Cleanup_Optimization_Plan.md`](Cleanup_Optimization_Plan.md) | Ordered cleanup phases and acceptance gates |
| [`architecture.manifest.json`](architecture.manifest.json) | Machine-readable production topology |
| [`architecture.manifest.schema.json`](architecture.manifest.schema.json) | Schema for the architecture manifest |

## Source-of-truth rule

Current code, tests, configuration, and Vedas must agree. The manifest is authoritative for production package topology; the prose documents explain responsibilities and behavior. If implementation and prose diverge, fix the disagreement in the same change rather than preserving contradictory guidance.

Historical generation-specific specifications are not active requirements. Git history preserves provenance; the Vedas tree contains only current operating documentation.

## Architecture in one paragraph

Agni composes the application. Kosh stores capability/plugin declarations. Manthan resolves requested work into an executable plan. Pravaha executes that plan. Shakti implements document capabilities. Yantra provides execution/device resources. Kavacha authorizes security/privacy-sensitive boundaries. Smriti is optional cache state. Darpana records runtime/quality history. Mukha presents the application through a local-only web/API layer. Sankalpa, Sutra, and Dosh provide contracts, settings, and errors.

The `sarathi.nabhi` package is a physical namespace for Kosh, Manthan, Pravaha, and artifacts/quarantine. It does not replace those ownership boundaries.

## Documentation standard

A document is current only when a new maintainer can use it without reading Git history to discover which statements still apply. Avoid speculative components, obsolete module inventories, migration-only instructions, and historical product labels in current docs.
