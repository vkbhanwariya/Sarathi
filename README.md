# Sarathi V2

**README Updated:** 01-09-2026, 11:45 PM IST (Asia/Kolkata)

Sarathi V2 is a local, plugin-first document intelligence system for
identifying documents, extracting and transforming their content, and
producing the information required by the user.

This README is the compact canonical architecture index. Detailed behavior is
owned by the linked specifications; it is not repeated here.

------------------------------------------------------------------------

## 1. Design Principles

### No Pileup — No Broken Wiring

-   one responsibility has one owner;
-   every capability has one explicit entry, dependency, result, and failure path;
-   broken, dangling, duplicate, bypass, or hidden alternate wiring is rejected;
-   the same behavior is not implemented twice;
-   shared infrastructure is implemented once globally;
-   capabilities do not recreate shared infrastructure locally;
-   superseded managers, contracts, stores, and execution paths are removed in
    the same change;
-   distinct responsibilities are split into small cohesive Python modules;
-   splitting is responsibility-driven, not abstraction-driven;
-   **Pravaha --- Dynamic Pipeline Engine** alone owns failure isolation,
    quarantine, and retry lifecycle.

### No Overengineering / No Premature Engineering

Build the smallest complete implementation required by demonstrated needs.
Do not introduce speculative managers, frameworks, services, databases, or
abstraction layers.

### Tiny Core, Plugin Features

**Nabhi --- Core Kernel** coordinates plugins, capabilities, lifecycle,
requests, contexts, results, resolution, and execution. OCR, translation,
banking, conversion, extraction, and other document intelligence remain in
**Shakti --- Plugin Ecosystem**.

### Whole-System Change Propagation

An architecture change is complete only when every affected owner, flow,
structure, test, dependency, status, and linked specification is updated
together. The README timestamp is updated last after validation.

------------------------------------------------------------------------

## 2. Canonical Functional Flow

``` text
Documents
    ↓
Darshana — Identify
    ↓
Manthan — Capability Resolver
    ↓
Pravaha — Dynamic Pipeline Engine
    ├── Read / Extract
    ├── Map / Normalize
    ├── Consolidate
    ├── Convert / Translate
    └── Analyse
    ↓
Required Information
```

Not every document uses every stage. **Manthan --- Capability Resolver**
selects the required capabilities; **Pravaha --- Dynamic Pipeline Engine**
executes the resulting plan.

------------------------------------------------------------------------

## 3. Stable Ownership Map

| Sanskrit name + English function | Canonical ownership |
|---|---|
| **Agni --- Runtime Bootstrap** | Creates, wires, starts, and closes the system |
| **Sankalpa --- Canonical Contracts** | Defines the common request, input, artifact, context, result, profile, and plugin language |
| **Nabhi --- Core Kernel** | Coordinates discovery, registry, lifecycle, resolution, pipelines, and the single artifact-commit boundary |
| **Yantra --- Resource & Execution Manager** | Allocates compatible resources and executes approved work |
| **Darpana --- Telemetry & Tracing** | Observes through **Maruti --- Runtime, Logging & Performance Telemetry** and **Pramana --- Confidence & Accuracy Telemetry** |
| **Mukha --- Console & Presentation** | Presents canonical runtime state and telemetry |
| **Smriti --- Cache & Runtime State** | Owns reusable results and bounded runtime state |
| **Kavacha --- Security & Privacy** | Enforces security, privacy, outbound access, and secrets policy |
| **Sutra --- Configuration** | Loads and validates runtime configuration, including default Input, Output, and Runtime roots |
| **Dosh --- Error System** | Defines structured failures and classifications |
| **Shakti --- Plugin Ecosystem** | Performs document and business work |
| **Anubhava --- Validated Experience Data** | Stores approved reusable experience as capability-owned TOML data; it is not a service, plugin, manager, database, or Python module |
| **Vedas --- Architecture & Knowledge** | Owns canonical documentation and specifications |

Capabilities must not recreate globally owned services or bypass their public
contracts.

------------------------------------------------------------------------

## 4. Modular Canonical Documentation

| Canonical file | Detailed scope |
|---|---|
| [Core Runtime Specification](Vedas/Sarathi_V2_Core_Runtime_Spec.md) | **Agni --- Runtime Bootstrap**, **Sankalpa --- Canonical Contracts**, **Nabhi --- Core Kernel**, canonical Input/Output lifecycle, **Pravaha --- Dynamic Pipeline Engine**, quarantine, and **Yantra --- Resource & Execution Manager** |
| [Shared Services Specification](Vedas/Sarathi_V2_Shared_Services_Spec.md) | **Darpana --- Telemetry & Tracing**, **Smriti --- Cache & Runtime State**, **Anubhava --- Validated Experience Data**, **Mukha --- Console & Presentation**, **Sutra --- Configuration**, **Kavacha --- Security & Privacy**, and **Dosh --- Error System** |
| [Mukha Screen Specification](Vedas/Sarathi_V2_Mukha_Screen_Spec.md) | Screens, progress visibility, file/page/worker presentation, review, summaries, typed UI state, synchronization, and acceptance rules |
| [Shakti Plugin & Capability Specification](Vedas/Sarathi_V2_Plugin_Capability_Spec.md) | Shared plugin rules, **Darshana --- Identify**, and capability-document routing |
| [Native Extraction Specification](Vedas/Sarathi_V2_Native_Extraction_Spec.md) | **Shruti --- Read / Native Extraction** local detection, readers, quality gate, provenance, dependencies, and tests |
| [OCR Specification](Vedas/Sarathi_V2_OCR_Spec.md) | OCR-local engines, fixed profiles, preprocessing, fallback, page evidence, dependencies, and tests |
| [Font Conversion Specification](Vedas/Sarathi_V2_Font_Conversion_Spec.md) | **Roopa --- Convert / Font Conversion** local detection, mapping, protection, normalization, data, dependencies, and tests |
| [Translation Specification](Vedas/Sarathi_V2_Translation_Spec.md) | Translation-local models, protected content, terminology, dependencies, and tests |
| [Bank Statement Consolidation Specification](Vedas/Sarathi_V2_Bank_Statement_Spec.md) | Bank-local pipeline, contracts, normalization, validation, outputs, profiles, and tests |
| [Implementation Guide](Vedas/Sarathi_V2_Implementation_Guide.md) | Development baseline, Phase 1 order, project structure, file ownership, end-to-end wiring, testing policy, dependency policy, and status |

Each detailed rule has one documentation owner. The main README links to that
owner instead of copying its contents.

------------------------------------------------------------------------

## 5. Documentation Authority

1. This README owns stable system boundaries, global ownership, and document
   routing.
2. Each linked specification owns detailed behavior within its declared scope.
3. `pyproject.toml` and `uv.lock` own dependency inventories and exact versions.
4. `config/` owns runtime policy; `data/` owns capability knowledge and approved
   Anubhava overlays; Python files own implementation behavior.
5. Conflicts are fixed at every affected source in one change; no parallel truth
   is retained.

New detail belongs in the relevant specification. A new specification is
created only when an existing owner cannot hold the concern cleanly.

------------------------------------------------------------------------

## 6. Current Direction

-   Windows 11 x64 and Python 3.13.15 remain the target baseline.
-   Phase 1 remains local-first, plugin-first, and dependency-disciplined.
-   Modern, actively maintained dependencies are preferred after compatibility
    and benchmark verification.
-   Optional fallbacks remain disabled unless the primary path fails or an
    explicit profile requests them.
-   Phase 1 implementation proceeds under the locked architecture and
    linked capability specifications.

------------------------------------------------------------------------

## 7. Local Run Command

Sarathi provides a non-interactive CLI entry point and interactive presentation frontend using the canonical Agni runtime bootstrap path:

```bash
# Non-interactive execution via console script entry point
uv run sarathi --input "path/to/document.pdf" --requirement "read_native" --profile "instant"

# Non-interactive execution via Python module entry point
uv run python -m sarathi --input "path/to/document.txt" --requirement "read_native" --output-root "Output"
```
