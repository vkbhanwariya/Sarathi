# Sarathi V2 — Core Runtime Specification

**Specification Updated:** 02-09-2026, 12:30 AM IST (Asia/Kolkata)

This file contains the detailed canonical specification for Agni, Sankalpa, Nabhi, Pravaha, and Yantra.
The main [Sarathi V2 README](../README.md) retains only stable architecture, ownership, and document routing.

## Agni --- Runtime Bootstrap

**Agni --- Runtime Bootstrap** is the composition root.

Startup:

``` text
Arambha.bat
    ↓
src/sarathi/__main__.py
    ↓
Agni — Runtime Bootstrap
    ↓
Start bounded Darpana bootstrap observation
    ↓
Load Sutra — Configuration
    ↓
Resolve and validate Input / Output / Runtime roots
    ↓
Apply configured Darpana recording and logging policy
    ↓
Create global shared services
    ↓
Initialize Nabhi — Core Kernel
    ↓
Discover and register plugins
    ↓
Start Mukha — Console & Presentation
    ↓
SARATHI READY
```

`Arambha.bat` is only the click-to-start launcher. It contains no
business logic.

`Agni — Runtime Bootstrap` creates and wires services. It does not
become another workflow engine.

**Maruti — Runtime, Logging & Performance Telemetry** begins before the
rest of system initialization so startup, configuration, warm-up, normal
execution, failure, retry, cancellation, quarantine, and shutdown can be
correlated as one run. Before configuration is available, Darpana uses a
bounded in-memory bootstrap path; configuration then attaches the one
approved logging/export path without creating a second telemetry system.

------------------------------------------------------------------------

## Sankalpa --- Canonical Contracts

**Sankalpa --- Canonical Contracts** defines the small common language
used by the entire system.

Canonical concepts:

``` text
Plugin
Capability
Request
Result
Context
Document
Input Reference
Artifact Reference
Execution Profile
```

Plugin/capability declarations also carry reviewable security
requirements. **Sankalpa --- Canonical Contracts** defines their shape;
**Kavacha --- Security & Privacy** alone evaluates and enforces them.

### Result

A common result can carry:

``` text
Result
├── data
├── artifacts
├── confidence
├── warnings
├── provenance
└── metadata
```

Confidence is common as a result concept, but each capability remains
responsible for calculating confidence according to its own semantics.

**Confidence integrity is mandatory.** Confidence must never be a
hard-coded success default or fabricated fallback value. It is stored on a
canonical ratio scale (`0.0 <= score <= 1.0`); percentage formats are presentation-only.
If confidence is reported, `ConfidenceValue` requires a non-empty calculation `method`
and a non-empty `evidence` mapping. If meaningful confidence cannot be computed, report it
as unavailable (`None`) rather than inventing a number.

``` text
Confidence reported
      ↓
Actual computation + non-empty evidence exist?
   ├── NO  → confidence unavailable (None)
   └── YES → method + evidence recorded in provenance
```

Provenance should make important output traceable to its source
document, page/region where applicable, stage, plugin, relevant
execution information, and confidence evidence where reported.

Document/result metadata may carry script, font, and layout/style information;
capabilities preserve that metadata without defining competing presentation
defaults.

### Input and Artifact Contracts

An input selection is a typed collection of normalized `InputRef` values, not
an implied scan of a capability-specific folder. An `InputRef` carries stable
identity, the selected source reference, safe display information, and measured
file facts. **Darshana --- Identify** validates actual content after selection.

An `ArtifactRef` identifies each artifact that actually exists, including its
role, media type, source/run lineage, completeness, size, checksum when
required, and committed path. A result carries zero or more artifact
references; the V1-style single `output_path` is not the canonical V2 model.

Inputs are read-only by default. Capabilities return data and typed ArtifactPayloads, where each ArtifactPayload contains an ArtifactIntent plus exact serialized bytes;
they do not hard-code output roots, create private output stores, or choose
final collision policy.

### Execution Profile

The common processing modes are:

1.  **Instant** --- fastest viable path, normally one pass and minimum
    unnecessary fallback.
2.  **Accurate** --- accuracy priority, validation, targeted
    fallback/reprocessing, and multiple passes where useful.
3.  **Layout Preserving** --- Accurate behavior plus preservation of
    meaningful document layout/structure.
4.  **Custom** --- caller explicitly selects supported strategy/options.

A plugin advertises which modes it supports. Modes are not implemented
as duplicated functions such as `ocr_fast()` and `ocr_accurate()`.

### Contract Evolution

A canonical contract has one active definition. When its shape changes, the
existing contract and all producers, consumers, tests, fixtures, and
documentation are migrated in the same change; an internal `V2`/`New` parallel
contract is not kept as a compatibility path. Explicit schema versioning is
introduced only when a real external persistence or compatibility boundary
requires simultaneous schemas.

------------------------------------------------------------------------

## Nabhi --- Core Kernel

**Nabhi --- Core Kernel** coordinates the system without knowing
document domains.

### Dvara --- Plugin Discovery

Finds available plugins.

-   Built-in plugins are explicitly known.
-   External plugins may be auto-discovered.
-   Discovery does not execute business logic.

### Kosh --- Plugin & Capability Registry

Maintains the canonical runtime registry.

It answers questions such as:

-   Which plugins are available?
-   Which capabilities do they provide?
-   Which execution modes and devices do they support?
-   Is a plugin healthy and available?

### Prana --- Lifecycle Manager

Coordinates initialization and shutdown.

It does not own resource scheduling, telemetry, or plugin-specific
initialization logic.

### Manthan --- Capability Resolver

Selects the valid capability route for a request.

Conceptually:

``` text
Document + User Requirement + Available Capabilities
                       ↓
             Manthan — Resolver
                       ↓
              Valid Capability Plan
```

It uses declared capability information and runtime availability. It
does not contain OCR-specific or bank-specific branches.

### Pravaha --- Dynamic Pipeline Engine

Executes the resolved capability plan.

Responsibilities:

-   pass canonical requests/context/results between capabilities
-   invoke capabilities in the required order
-   propagate failures and warnings correctly
-   maintain execution lineage
-   own document/capability failure isolation and the quarantine/retry
    lifecycle
-   cooperate with shared services

### Canonical Input, Workspace, and Output Lifecycle

Sarathi supports arbitrary files, native multi-select, pasted paths, and folder
selection. The project-level `Input/` directory is an optional convenience
inbox, never the only accepted source and never split into hard-coded
capability folders.

``` text
Selected files / folder / optional Input inbox
                    ↓
Normalize + deduplicate + verify existence
                    ↓
Darshana — Identify validates actual content
                    ↓
Runtime/Work/<run-id>/ stages generated data
                    ↓
Nabhi artifact boundary atomically commits completed artifacts
                    ↓
Output/<requirement>/Run-<timestamp>-<short-id>/
                    ├── committed artifacts
                    ├── partial/ only when explicitly preserved
                    └── run-manifest.json written last
```

Canonical rules:

- **Sutra --- Configuration** supplies default `Input`, `Output`, and `Runtime`
  roots; the request may carry an explicitly selected output root.
- **Kavacha --- Security & Privacy** validates path access, safe names, root
  escape attempts, and unsafe source/destination overlap.
- Input sources are not modified, moved, deleted, or copied unless a separate
  explicit export/audit request requires copying.
- Folder discovery excludes active Output and Runtime roots, ignores hidden
  temporary files, filters supported candidates, and recurses only when the
  request explicitly enables recursion.
- Final writes use a unique temporary file in the destination filesystem and
  atomic replacement/rename; collision handling exists once globally.
- A failed or cancelled run still has a terminal result. Completed artifacts
  remain valid; incomplete data appears under `partial/` only when policy
  preserves it and is never presented as final.
- Successful commits remove their staging data. On failure or cancellation,
  uncommitted temporary data is removed unless explicit partial-preservation or
  quarantine policy moves it to its canonical destination.
- `<requirement>` is a validated safe stable requirement/capability identifier
  (lowercase letters, digits, `_` and `-` only; matching `^[a-z0-9_-]+$`), not
  raw user-entered text or paths; the run suffix prevents normal cross-run collisions.
- Capabilities produce data + typed `ArtifactPayload`s (combining `ArtifactIntent` with exact serialized bytes).
- Nabhi alone manages staging, collision handling, and atomic commit of payload bytes.
- Canonical final `Result.artifacts` contains confirmed `ArtifactRef`s only; `artifact_payloads` is returned empty.
- `run-manifest.json` records only confirmed artifacts and safe provenance. It
  never invents confidence/quality values or exposes raw sensitive source paths.
- `Runtime/Quarantine`, `Runtime/Telemetry`, and `Runtime/Cache` retain their
  existing canonical owners; they are not user-output folders.
- **Maruti --- Runtime, Logging & Performance Telemetry** measures selection,
  read, staging, serialization, commit, failure, and cleanup spans but never
  selects paths or writes artifacts.

No plugin or capability creates its own resolver, writer, output directory,
manifest store, or alternate commit path.

### Quarantine and Failure Isolation

**Pravaha --- Dynamic Pipeline Engine** owns quarantine as part of
pipeline failure handling. Quarantine is not a second manager or
execution subsystem.

``` text
Capability / Pipeline Failure
        ↓
Dosh — Error System
classifies the failure
        ↓
Pravaha — Dynamic Pipeline Engine
decides failure handling
        │
        ├── normal failure → explicit Result / Error
        │
        └── isolatable or retryable failure
                    ↓
                Quarantine
                    ↓
            Hashed Failure Manifest
            ├── input/document identity hash
            ├── request / trace identity
            ├── failed capability / plugin
            ├── failure classification
            ├── execution profile/context
            ├── retry count / status
            └── provenance
                    ↓
              isolated safely
                    ↓
              Retry lifecycle
            ├── retry approved → Yantra executes
            ├── retry succeeds → release
            └── exhausted/permanent → remain quarantined
```

The hash identifies the failed input for integrity, deduplication, and
traceability; it does not replace the actual source/reference required
for a retry. Sensitive document content and raw secrets are not dumped
into the manifest.

Ownership remains explicit:

``` text
Dosh      → classify / represent the failure
Pravaha   → isolate, quarantine, and control retry lifecycle
Sutra     → provide quarantine / retry policy configuration
Kavacha   → protect sensitive quarantined artifacts and access
Yantra    → execute an approved retry
Maruti    → record failure, quarantine, release, and retry history
Smriti    → remains the reusable-result cache; quarantine is not cache state
```

It does not implement OCR, translation, font conversion, bank mapping,
hardware scheduling, security policy, or telemetry storage.

------------------------------------------------------------------------

## Yantra --- Resource & Execution Manager

**Yantra --- Resource & Execution Manager** is the single global owner
of hardware and execution policy.

No plugin creates its own global worker pool, device manager, GPU
selector, NPU selector, thread policy, or competing scheduler.

### Hardware Capability First

Yantra does not treat CPU, GPU, and NPU as interchangeable workers.

At startup/runtime it establishes available hardware and execution
backends, then maintains a capability profile.

``` text
Hardware Discovery
       ↓
CPU / GPU / NPU
       ↓
Supported runtimes and capabilities
       ↓
Measured suitability
       ↓
Execution capability profile
```

Typical tendencies may be used as initial candidates:

-   CPU: parsing, branching/control-heavy work, lightweight transforms,
    validation, orchestration-supporting work
-   GPU: parallel image/tensor workloads and high-throughput supported
    inference
-   NPU: supported neural inference where it provides a useful
    efficiency/performance path

These are not permanent hard-coded truths. Actual backend/model support
and measured performance decide the final preference.

### Best-Fit Allocation

A capability declares execution requirements rather than selecting
hardware itself.

Conceptually:

``` text
preferred_devices
supported_devices
parallelizable
memory_requirement
priority
```

Yantra then performs:

``` text
Task
 ↓
Workload requirements
 ↓
Best compatible device
 ↓
Primary allocation
 ↓
Execution
```

### Global Utilization and Spillover

Best-fit allocation comes first, but compatible resources should not
remain unnecessarily idle.

``` text
Preferred worker/device available?
        │
        ├── YES → execute there
        │
        └── NO
             ↓
Compatible free resource available?
        │
        ├── YES → spill over when policy permits
        │
        └── NO  → queue for appropriate resource
```

The objective is:

**best capability use first → utilization optimization second → safe
fallback third.**

This policy applies globally to OCR, native extraction, font conversion,
translation, bank processing, and future plugins.

### Runtime Selection

Inference runtime/device selection also belongs to **Yantra --- Resource & Execution Manager**.

Each capability declares tested compatible runtime/device bindings. Yantra selects
an available compatible device without changing the capability's chosen engine
or processing profile.

``` text
Capability execution request
       ↓
Yantra — Resource & Execution Manager
       ↓
Compatible device candidates
├── GPU
├── NPU
└── CPU
```

Selection is based on declared compatibility, measured speed, stability, current
load, and fallback availability. Engine/runtime direction remains in the owning
capability specification.

### Global Measurement Boundary

``` text
Yantra executes
     ↓
Maruti records factual runtime and performance
```

Yantra remains the execution authority. **Darpana --- Telemetry & Tracing**
observes execution; neither Darpana nor capability-owned Anubhava data
selects devices, schedules work, initiates fallback, or changes execution
strategy.

------------------------------------------------------------------------
