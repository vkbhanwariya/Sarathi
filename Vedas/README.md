# Vedas — Sarathi Engineering Guide

`Vedas/` contains the engineering documentation for Sarathi. It provides the single source of truth for architectural ownership, capabilities, configuration, formats, troubleshooting, and developer workflows.

---

## Documentation Index

| Document | Topic |
| --- | --- |
| [`Architecture.md`](Architecture.md) | Canonical subsystem ownership, runtime flow, and invariants |
| [`Capabilities.md`](Capabilities.md) | Capability specifications, inputs, outputs, fallbacks, and limitations |
| [`Configuration.md`](Configuration.md) | Typed Sutra configuration keys, defaults, and cloud settings |
| [`Formats.md`](Formats.md) | Supported document, spreadsheet, delimited, and font formats |
| [`Troubleshooting.md`](Troubleshooting.md) | Diagnoses and fixes for OCR, OpenVINO, fonts, encodings, and network |
| [`Development.md`](Development.md) | Install, run, and permanent 5-gate CI test commands |
| [`Mukha_Transport.md`](Mukha_Transport.md) | Local ASGI web transport, SSE streaming, and security boundary |
| [`Decisions.md`](Decisions.md) | Canonical UI/UX progressive Home task hierarchy and capability mapping |
| [`Cleanup_Optimization_Plan.md`](Cleanup_Optimization_Plan.md) | Historical record of completed architecture and performance cleanup |
| [`architecture.manifest.json`](architecture.manifest.json) | Machine-readable production package and component topology |
| [`architecture.manifest.schema.json`](architecture.manifest.schema.json) | JSON schema defining production manifest rules |

---

## Canonical Architecture Summary

- **Agni**: Application composition, bootstrap, and process lifecycle.
- **Sankalpa**: Shared request/result contracts and document models.
- **Kosh**: Registry for capability and plugin declarations.
- **Manthan**: Planning authority for resolving requirements and profiles.
- **Pravaha**: Execution engine for executing resolved plans.
- **Shakti**: Document-processing capabilities and provider adapters.
- **Kavacha**: Security authorization, path containment, and privacy enforcement.
- **Smriti**: Optional deterministic result caching.
- **Darpana**: Telemetry, quality observations, and execution history.
- **Sutra**: Runtime settings loading and typed configuration.
- **Mukha**: Local web transport, presentation state, and UI.
- **Dosh**: Shared error taxonomy and failure codes.

`sarathi.nabhi` is a physical namespace containing Kosh, Manthan, Pravaha, and artifact utilities; it is not a separate decision authority.
Generic hardware execution policy belongs to Yantra; domain-specific document behavior stays within the owning Shakti capability.
