# Sarathi Architecture

Sarathi is an offline-first, local document and financial intelligence system. Its architecture enforces strict single-responsibility boundaries across composition, planning, execution, security, hardware scheduling, telemetry, and presentation.

---

## Canonical Subsystem Ownership

| Subsystem | Namespace | Primary Responsibility | Architectural Invariant |
| :--- | :--- | :--- | :--- |
| **Agni** | `sarathi.agni` | Composition root, subsystem wiring, process lifecycle. | Sole application composition root. Never plans or executes capabilities. |
| **Sankalpa** | `sarathi.sankalpa` | Shared request, result, artifact, and document data models. | Pure contracts and types. Contains zero business logic or I/O. |
| **Kosh** | `sarathi.nabhi.kosh` | Capability and plugin declaration registry. | Sole registry authority. Never executes plans. |
| **Manthan** | `sarathi.nabhi.manthan` | Dependency ordering and execution planning. | Sole planning authority. Never executes steps. |
| **Pravaha** | `sarathi.nabhi.pravaha` | Sequential pipeline step execution, retries, and quarantine. | Sole execution authority. Never creates plans. |
| **Shakti** | `sarathi.shakti` | Domain document capabilities (OCR, Translation, Fonts, Banking). | Self-contained domain capabilities. Never duplicates platform infrastructure. |
| **Yantra** | `sarathi.yantra` | Hardware discovery and device slot concurrency allocation. | Device management only. Workload-specific strategies remain in Shakti. |
| **Kavacha** | `sarathi.kavacha` | Path containment, secret allowlists, and capability authorization. | Fail-closed security gate. Never acts as credential vault or proxy. |
| **Smriti** | `sarathi.smriti` | Cryptographic, deterministic L1/L2 result caching. | Cache only. Never acts as source of truth for active runs. |
| **Darpana** | `sarathi.darpana` | Monotonic timing (Maruti) and quality evidence (Pramana). | Observability only. Never models application state. |
| **Sutra** | `sarathi.sutra` | Typed TOML configuration discovery and immutable settings. | Configuration only. Never enforces policy or modifies state. |
| **Mukha** | `sarathi.mukha` | Loopback ASGI web server, SSE streaming, and cockpit UI state. | Presentation only. Never processes documents directly. |
| **Dosh** | `sarathi.dosh` | Standardized failure codes (`FailureCode`) and `DoshError`. | Error vocabulary only. Never used for control flow. |

*Note:* `sarathi.nabhi` is a physical runtime namespace hosting Kosh, Manthan, Pravaha, and artifact utilities; it is not a competing decision authority.

---

## Runtime Execution Dataflow

```text
       Browser / CLI Request
                 │
                 ▼
       Mukha (Web API & UI)
                 │
                 ▼
       Agni (Composition Root)
                 │
                 ▼
   Kosh (Registry) ──► Manthan (Planner)
                             │
                             ▼
                          Pravaha (Execution Engine)
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
     Kavacha (Auth)    Yantra (Slots)   Smriti (Cache)
            │                │                │
            └────────────────┼────────────────┘
                             ▼
                    Shakti (Capabilities)
                    [OCR · Trans · Bank · Font]
                             │
                             ▼
                    Darpana (Telemetry)
                             │
                             ▼
                    Committed Artifacts
```

---

## Primary Hardware Deployment Profile

Sarathi optimizations are engineered, tuned, and validated for this primary hardware profile first before fallback targets:

| Component | Hardware Specification | Deployment Role & Optimization Invariants |
| :--- | :--- | :--- |
| **Host System** | HP Laptop 15-fd1xxx (Windows 11 x64) | Reference production host. |
| **CPU** | Intel Core Ultra 5 125H (14 Cores: 4P + 8E + 2LPE, 18 Threads) | **Primary Translation & Logic Host**: Multi-core x86 AVX2/AVX-VNNI neural acceleration. Parallel inference across all 4 P-cores (`intra_threads=4`). |
| **GPU** | Intel Graphics (Meteor Lake Arc iGPU, 7 Xe Cores) | **Primary RapidOCR Accelerator**: Dedicated OpenVINO FP16 OCR inference with persistent shader cache (`Runtime/Cache/openvino_model_cache`). No CUDA dependency. |
| **NPU** | Intel AI Boost (Meteor Lake NPU) | Managed via `yantra.devices` for static workloads. |
| **RAM** | 24 GB Physical RAM | Ample memory for concurrent in-memory OCR models and CTranslate2 weights without swapping. |
| **Network** | Air-Gapped / Loopback Only | All processing strictly runs on `127.0.0.1`. Cloud adapters require explicit configuration. |

---

## Architectural Invariants

1. **Single Owner, Single Path**: One canonical implementation per concern. Superseded implementations are deleted, never coexisting.
2. **Fail-Closed Security**: Kavacha validates path containment and authorizes capabilities before any filesystem or network access.
3. **Deterministic State Preservation**: Fresh runs, cache hits, retries, and deserializations yield identical results.
4. **Primary Hardware First**: Maximize throughput across the 14-core CPU and Arc iGPU before considering generic fallback hardware.
5. **Telemetry Separation**:
   - **Maruti** records operational metrics: monotonic durations, timestamps, spans, and device facts.
   - **Pramana** records evidence-backed quality observations: confidence metrics, region validations, and accuracy scores. Confidence is never relabeled as accuracy.

---

## Component & Code Inventory

For the dense, automated module-by-module reference listing all ~100 components, their compute profiles, and key exported symbols, refer to:
- [`CODE_INDEX.md`](CODE_INDEX.md) — Dense code and optimization index.
- [`architecture.manifest.json`](architecture.manifest.json) — Machine-readable production package and component topology.
