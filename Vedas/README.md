# Vedas — Sarathi Engineering Guide

`Vedas/` contains the engineering documentation for Sarathi. It provides the single source of truth for architectural ownership, capabilities, configuration, formats, troubleshooting, and developer workflows.

---

## Documentation Index

| Document | Topic |
| --- | --- |
| [`Architecture.md`](Architecture.md) | Canonical subsystem ownership, runtime flow, primary hardware profile, and invariants |
| [`Capabilities.md`](Capabilities.md) | Capability specifications, inputs, outputs, fallbacks, and limitations |
| [`Configuration.md`](Configuration.md) | Typed Sutra configuration keys, defaults, and cloud settings |
| [`Formats.md`](Formats.md) | Supported document, spreadsheet, delimited, and font formats |
| [`Troubleshooting.md`](Troubleshooting.md) | Diagnoses and fixes for OCR, translation, OpenVINO, fonts, and network |
| [`Development.md`](Development.md) | Environment setup (`tools/scripts/update_sarathi.ps1`), CI gates, and planning rules |
| [`Mukha_Transport.md`](Mukha_Transport.md) | Local ASGI web transport, SSE streaming, and security boundary |
| [`Decisions.md`](Decisions.md) | Canonical UI/UX progressive Home task hierarchy and capability mapping |
| [`Upgrades.md`](Upgrades.md) | Authoritative specifications for planned high-ROI architectural capabilities |
| [`architecture.manifest.json`](architecture.manifest.json) | Machine-readable production package and component topology |
| [`architecture.manifest.schema.json`](architecture.manifest.schema.json) | JSON schema defining production manifest rules |

---

## Primary Hardware Specification & Optimization Target

Sarathi's authoritative reference hardware deployment profile is pinned below.
**Rule (Primary Hardware First):** All system, threading, concurrency, accelerator, and pipeline optimizations MUST be engineered, tuned, and validated for this primary Sarathi Hardware profile first before considering generic fallback hardware.

| Component | Specification | Deployment Role & Optimization Invariants |
| :--- | :--- | :--- |
| **System** | HP Laptop 15-fd1xxx (Windows 11 x64) | Reference production host. |
| **CPU** | Intel(R) Core(TM) Ultra 5 125H (14 Cores: 4P + 8E + 2LPE, 18 Logical Processors) | **Primary Translation & Logic Host**: Tuned for multi-core x86 AVX2/AVX-VNNI neural acceleration. Compute-intensive inference must never artificially choke on single-core serialization when multi-core throughput is available. |
| **GPU** | Intel(R) Graphics (Meteor Lake iGPU, 7 Xe Cores, Driver 32.0.101.8508) | **Primary RapidOCR Accelerator**: Dedicated to OpenVINO FP16/INT8 OCR inference with persistent shader cache (`Runtime/Cache/openvino_model_cache`). Not for CUDA. |
| **NPU** | Intel(R) AI Boost (Meteor Lake NPU) | **OpenVINO NPU Engine**: Probed and managed via `yantra.devices` for static workloads. |
| **Memory** | 24 GB Physical RAM | Ample memory for concurrent in-memory OCR models and CTranslate2 neural weights without swapping. |
| **CUDA** | None (0 physical devices) | Translation and OCR pipelines must never depend on or expect NVIDIA CUDA on primary hardware. |

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
