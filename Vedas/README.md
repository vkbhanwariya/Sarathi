# Vedas — Sarathi Engineering Guide

`Vedas/` is the canonical engineering documentation for Sarathi. It provides dense, high-signal reference guides for architecture, capabilities, configuration, formats, and developer workflows.

---

## Documentation Index

| Document | Topic |
| :--- | :--- |
| [`Purpose.md`](Purpose.md) | Operational purpose, dual-module architecture, and core office workflows |
| [`Architecture.md`](Architecture.md) | Canonical subsystem ownership, runtime flow, primary hardware profile, and architectural invariants |
| [`CODE_INDEX.md`](CODE_INDEX.md) | Automated dense code index mapping every module to responsibility, compute profile, and key symbols |
| [`Capabilities.md`](Capabilities.md) | Document intelligence capabilities, inputs, outputs, accelerators, and fallbacks |
| [`Configuration.md`](Configuration.md) | Typed Sutra configuration keys, defaults, and cloud settings |
| [`Decisions.md`](Decisions.md) | Canonical UI task hierarchy and workflow mapping |
| [`Development.md`](Development.md) | Environment setup, fast-gate commands, and development ladder |
| [`Troubleshooting.md`](Troubleshooting.md) | Diagnoses and fixes for OCR, translation, OpenVINO, fonts, and network |
| [`Bank_Statement_Mapping_Guide.md`](Bank_Statement_Mapping_Guide.md) | Canonical multi-bank schema mapping, format sniffing, and YAML onboarding guide |
| [`architecture.manifest.json`](architecture.manifest.json) | Machine-readable production package and component topology |

---

## Primary Hardware Profile & Optimization Invariants

Sarathi is engineered, tuned, and validated for this authoritative reference hardware profile first:

| Component | Specification | Deployment Role & Optimization Invariants |
| :--- | :--- | :--- |
| **Host System** | HP Laptop 15-fd1xxx (Windows 11 x64) | Reference production host. |
| **CPU** | Intel Core Ultra 5 125H (14 Cores: 4P + 8E + 2LPE, 18 Threads) | **Primary Translation & Logic Host**: Multi-core x86 AVX2/AVX-VNNI neural acceleration. Parallel inference across P-cores. |
| **GPU** | Intel Graphics (Meteor Lake Arc iGPU, 7 Xe Cores) | **Primary RapidOCR Accelerator**: Dedicated OpenVINO FP16/INT8 OCR inference with persistent shader cache (`Runtime/Cache/openvino_model_cache`). Zero CUDA dependence. |
| **NPU** | Intel AI Boost (Meteor Lake NPU) | Managed via `yantra.devices` for static workloads. |
| **RAM** | 24 GB Physical Memory | Concurrent in-memory OCR models and CTranslate2 weights without swapping. |
| **Network** | Air-gapped / Local Loopback | All processing runs 100% locally over `127.0.0.1`. |

---

## Canonical Subsystem Ownership

| Subsystem | Canonical Ownership | Primary Responsibility |
| :--- | :--- | :--- |
| **Agni** | Composition & Lifecycle | Application bootstrap, subsystem wiring, and process shutdown. |
| **Sankalpa** | Contracts & Models | Shared request, result, artifact, and document data models. |
| **Kosh** | Registry | Capability and plugin declarations (`sarathi.nabhi.kosh`). |
| **Manthan** | Planning | Dynamic requirement resolution and topological plan ordering (`sarathi.nabhi.manthan`). |
| **Pravaha** | Execution | Step-level capability dispatch, retries, and quarantine (`sarathi.nabhi.pravaha`). |
| **Shakti** | Capabilities | Document intelligence capabilities (OCR, Translation, Fonts, Banking, Statutory). |
| **Yantra** | Hardware Concurrency | Generic hardware discovery and device capacity scheduling. |
| **Kavacha** | Security | Fail-closed authorization, path containment, and privacy enforcement. |
| **Smriti** | Result Cache | Optional deterministic cryptographic result caching across runs. |
| **Darpana** | Telemetry | Operational timing (Maruti) and quality observations (Pramana). |
| **Sutra** | Configuration | Immutable, typed TOML runtime settings loading. |
| **Mukha** | Presentation & Web | Loopback ASGI server, SSE event streaming, and single-page cockpit UI. |
| **Dosh** | Error Taxonomy | Standardized failure codes and exception hierarchy. |
