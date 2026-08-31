# Sarathi V2 — Shared Services Specification

**Specification Updated:** 31-08-2026, 06:59 PM IST (Asia/Kolkata)

This file contains the detailed canonical specification for Darpana, Smriti, Anubhava, Mukha, Sutra, Kavacha, and Dosh.
The main [Sarathi V2 README](../README.md) retains only stable architecture, ownership, and document routing.

## Darpana --- Telemetry & Tracing

**Darpana --- Telemetry & Tracing** is one global observation service
with one typed recording path and two distinct telemetry domains:

``` text
Darpana — Telemetry & Tracing
├── Maruti — Runtime, Logging & Performance Telemetry
└── Pramana — Confidence & Accuracy Telemetry
```

This is an internal responsibility split, not two telemetry systems.
Plugins and capabilities do not create local profilers, telemetry stores,
logging handlers, report managers, bridges, or alternate schemas.

### Maruti --- Runtime, Logging & Performance Telemetry

**Maruti --- Runtime, Logging & Performance Telemetry** records every run
from its earliest observable startup boundary to its terminal end,
regardless of success, failure, cancellation, retry, or quarantine.

It measures every meaningful process boundary actually executed,
including system initialization, configuration, dependency/model loading,
warm-up, input reading, queue/wait time, preprocessing, capability and
backend execution, validation, persistence, finalization, and shutdown.
Nested spans preserve parent/child relationships so their durations are
not incorrectly added twice.

Maruti owns factual runtime observation:

-   monotonic elapsed-time measurement and UTC occurrence timestamps;
-   run/request/trace/span correlation;
-   structured diagnostic logging through one Agni-configured path;
-   success/failure status and Dosh error classification references;
-   retry, fallback, cache, quarantine, backend, device, and resource facts;
-   factual aggregates such as counts, totals, throughput, and percentiles.

Unknown or unmeasured values remain unavailable; they are never replaced
with fabricated zeros or sample metrics. Maruti records what happened but
does not schedule, retry, allocate resources, quarantine, or decide policy.

### Pramana --- Confidence & Accuracy Telemetry

**Pramana --- Confidence & Accuracy Telemetry** records the evidence used
to evaluate output quality across capabilities. Confidence is a
capability-produced, evidence-backed assessment. Accuracy is recorded only
when verified truth, an approved reference, or validated human correction
exists; confidence is never relabelled as accuracy.

Pramana correlates quality evidence with the same request/trace/span path
used by Maruti. It may record confidence components, validation outcomes,
fallback comparisons, disagreement, accepted corrections, reference
identity, and evaluation results. It observes quality; it does not choose
the winning result, approve a correction, or alter capability behavior.

### Canonical Recording and Access

``` text
Runtime and capability facts
          ↓
One typed Darpana record path
          ├── bounded live state for approved consumers
          ├── JSONL sequential export
          └── SQLite searchable history when configured
```

**Mukha --- Console & Presentation** consumes only Darpana's public typed
state/events. Exporter failure normally degrades observability rather than
changing the document-processing outcome. Retention, exporters, logging,
and measurement policy come from **Sutra --- Configuration**; sensitive
values are filtered under **Kavacha --- Security & Privacy**.

Suggested responsibility-driven structure:

``` text
darpana/
├── service.py
├── records.py
├── tracer.py
├── maruti.py
├── pramana.py
├── recorder.py
└── exporters/
    ├── jsonl.py
    └── sqlite.py
```

A file is created only when its responsibility is implemented. OpenTelemetry
or larger analytical infrastructure may be added later only as an exporter
after demonstrated need; it does not replace Darpana's canonical model.

------------------------------------------------------------------------

## Smriti --- Cache & Runtime State

**Smriti --- Cache & Runtime State** is the single canonical general
cache owner.

``` text
Smriti
├── key.py
├── memory.py
├── store.py
└── policy.py
```

### Canonical cache flow

``` text
Plugin execution request
        ↓
Canonical Cache Key
        ↓
L1 Memory
   ├── hit → result
   └── miss
        ↓
L2 SQLite
   ├── hit → promote to L1 → result
   └── miss
        ↓
Execute capability
        ↓
Store reusable result
```

The cache key must be based on the inputs that can change result
validity, such as input identity, capability, plugin/model version, and
relevant configuration.

There is one canonical general key algorithm rather than multiple
unrelated cache-key implementations.

Specialized compiled-model caching, such as an OpenVINO compiled-model
cache, may remain an internal **Yantra --- Resource & Execution
Manager** implementation detail because it caches execution artifacts
rather than document results.

Workflow resumability/checkpointing is not mixed into Smriti unless a
demonstrated requirement later justifies a separate minimal mechanism.

Telemetry history belongs to **Darpana --- Telemetry & Tracing** and approved
experience overlays belong to their capabilities. Neither is stored as
Smriti result-cache state.

------------------------------------------------------------------------

## Anubhava --- Validated Experience Data

**Anubhava --- Validated Experience Data** is a capability-owned
declarative data convention. It is not a Python module, shared service,
plugin, database, optimizer, manager, loader framework, or execution path.

Each applicable capability may keep its own approved reusable knowledge at:

``` text
data/<capability>/anubhava.toml
```

Phase 1 locations, created only when needed, are:

``` text
data/ocr/anubhava.toml
data/font_conversion/anubhava.toml
data/translation/anubhava.toml
data/bank_statements/anubhava.toml
```

Examples include validated OCR corrections, font mappings, approved
translation/legal corrections, and consolidation mappings. A capability
uses its existing data-loading and validation path to read this file; no
separate Anubhava loader or runtime is introduced.

### Activation rule

``` text
New or unresolved case
        ↓
Pramana records quality evidence
        ↓
Capability or authorized human validates/approves correction
        ↓
Explicitly curate data/<capability>/anubhava.toml
        ↓
Owning capability revalidates and may use it in future runs
```

A correction becomes active only after validation/approval and an explicit
curated TOML change. Runtime execution never auto-writes or auto-promotes a
candidate into active Anubhava data. Rejected or unresolved candidates do
not affect future runs.

The TOML contains data only: no callbacks, algorithms, executable
conditions, policy decisions, or hidden workflow. It cannot silently
override canonical baseline mappings; precedence and conflicts are explicit
and revalidated by the owning capability. Raw documents, PII, secrets, and
unapproved content are prohibited under **Kavacha --- Security & Privacy**.

An `anubhava.toml` file is created only when that capability has demonstrated,
validated knowledge worth preserving. Empty files are not created merely for
structural symmetry.

------------------------------------------------------------------------

## Mukha --- Console & Presentation

**Mukha --- Console & Presentation** is the single presentation owner. It
consumes canonical runtime state and Darpana telemetry; it does not execute
capabilities, decide runtime policy, or fabricate metrics.

Detailed screens, progress visibility, file/page/worker presentation,
review and summary behavior, typed UI state, synchronization, and acceptance
rules are maintained in the separate
[Sarathi V2 --- Mukha Screen Specification](Sarathi_V2_Mukha_Screen_Spec.md).

------------------------------------------------------------------------

## Sutra --- Configuration

**Sutra --- Configuration** is the common configuration access layer.

Responsibilities:

-   load project/runtime configuration
-   validate settings
-   expose consistent settings to the runtime
-   load external declarative definitions where appropriate
-   expose Darpana retention, exporter, logging, and measurement policy
-   expose canonical data roots without owning capability data semantics

Plugins should not independently invent competing configuration-loading
mechanisms.

------------------------------------------------------------------------

## Kavacha --- Security & Privacy

**Kavacha --- Security & Privacy** is the single global owner for
security and privacy enforcement.

Plugins do not implement private PII scanners, credential vaults,
network policy, cloud guards, or local/external processing rules. They
declare what they require; Kavacha decides and enforces globally.

### Canonical Wiring

``` text
Plugin / Capability
      ↓
Security Declaration / Request
      ↓
Kavacha — Security & Privacy
      ↓
Security Decision
├── PII access policy
├── local vs external processing
├── network permission
├── outbound PII verification
└── authorized secret access
      ↓
Yantra — Resource & Execution Manager
      ↓
Approved Plugin Execution
      ↓
Darpana — Telemetry & Tracing
      ↓
Audit metadata only — never raw secrets
```

Canonical rule:

``` text
Plugin declares
      ↓
Kavacha decides and enforces
      ↓
Yantra executes approved work
      ↓
Darpana audits safely
```

### Plugin Security Declaration

Security requirements are reviewable plugin/capability metadata in
**Sankalpa --- Canonical Contracts**:

``` text
pii_access
local_processing
network_access
external_processing
required_secrets
```

**Dvara --- Plugin Discovery** and **Kosh --- Plugin & Capability
Registry** register declarations; they do not decide policy.

### Mandatory Outbound Gate

Every external/cloud call passes through Kavacha independently of any
earlier masking.

``` text
External processing requested
        ↓
Kavacha — Security & Privacy
        ↓
Network / external-processing policy
        ↓
Independent PII / sensitive-data verification
        ↓
Allowed?
   ├── NO  → block with explicit error
   └── YES
          ↓
Authorized secret access if required
          ↓
External call may execute
```

Masking and outbound verification are separate defense-in-depth steps.
Masking never bypasses the final outbound verification gate.

### Secrets and Credentials

Plugins request secrets by logical name. Raw credentials are not stored
in plugin code or ordinary configuration files.

**Sutra --- Configuration** owns non-secret settings and policy
configuration. **Kavacha --- Security & Privacy** owns the secure
credential boundary and authorized secret access.

### Minimal Physical Shape

``` text
kavacha/
├── service.py
├── policy.py
├── verifier.py
└── vault.py
```

`service.py` is the single public security interface. `policy.py` owns
permission decisions. `verifier.py` owns PII/sensitive-content
verification. `vault.py` owns the secure secret boundary.

No separate PII Manager, Network Manager, Cloud Guard, Credential
Manager, or plugin-local security subsystem is created.

------------------------------------------------------------------------

## Dosh --- Error System

**Dosh --- Error System** defines the small common failure vocabulary
required across the system.

It should distinguish failures that matter operationally, such as:

-   unsupported capability/input
-   unavailable dependency/backend
-   execution failure
-   invalid configuration
-   validation failure
-   resource unavailability
-   security/policy denial

It must remain small. Domain-specific failure details can remain in
plugin metadata/warnings rather than creating a huge exception
hierarchy.

Failures must not disappear through silent exception swallowing.

**Dosh --- Error System** classifies and represents failures; it does
not own document isolation, quarantine storage, or retry orchestration.
Those lifecycle decisions belong to **Pravaha --- Dynamic Pipeline
Engine**.

------------------------------------------------------------------------
