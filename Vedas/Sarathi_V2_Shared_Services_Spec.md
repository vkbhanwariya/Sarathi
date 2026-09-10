# Sarathi V2 — Shared Services Specification

**Specification Updated:** 10-09-2026 (Asia/Kolkata)

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
          ├── bounded in-memory live buffer for active run consumers (Mukha)
          ├── real-time active in-flight span registry (active_spans())
          └── TerminalRunSummary history persistence (JSONL or SQLite) under Runtime/Telemetry
```

`LiveTelemetryBuffer` stores in-memory ring buffers of `MarutiRecord` and `PramanaRecord` for live presentation (Mukha) and active run inspection. In addition, `DarpanaService` maintains a thread-safe `active_spans()` registry tracking in-flight execution spans in real time during `time_scope` measurement. `TerminalRunHistoryStore` persists sanitized, schema-validated `TerminalRunSummary` records across runs upon run finalization (under `Runtime/Telemetry/history.jsonl` or SQLite `history.db`).

**Mukha --- Console & Presentation** consumes only Darpana's public typed
state/events. Exporter failure normally degrades observability rather than
changing the document-processing outcome. Retention, exporters, logging,
and measurement policy come from **Sutra --- Configuration**; sensitive
values are filtered under **Kavacha --- Security & Privacy**.

Canonical file structure:

``` text
darpana/
├── service.py
├── maruti.py
├── pramana.py
└── history.py
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
├── policy.py
└── serialization.py
```

### Canonical cache flow

``` text
Plugin execution request
        ↓
Canonical Cache Key
        ↓
L1 Memory (Synchronized LRU)
   ├── hit → result
   └── miss
        ↓
L2 SQLite (Bounded Runtime/Cache Store)
   ├── hit → promote to L1 → result
   └── miss
        ↓
Execute capability
        ↓
Store reusable result (Lossless Binary Serialization)
```

The canonical cache key is computed by `smriti.key.compute_cache_key()` as a SHA-256 composite hash factoring in:
- input document bytes or stable source identifier
- target capability ID and capability version
- execution profile ID and profile version
- canonical configuration options hash

This strict composite key prevents stale cache hits when pipeline models or capability configurations are upgraded.

There is one canonical general key algorithm rather than multiple unrelated cache-key implementations.

#### Cache Security and Lossless Serialization
- **Store Safety**: `smriti.store.SQLiteStore` validates all cache keys against directory traversal and root escape attacks, ensuring cached records remain safely bounded within `Runtime/Cache/`.
- **Lossless Binary Serialization**: `smriti.serialization` provides deterministic binary serialization for `CanonicalDocument` and typed artifact payloads. Every serialized stream includes a magic header check and length validation, raising explicit `DeserializationError` upon detecting corrupted or truncated payloads.

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

Standard capability locations, created only when needed, are:

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

**Kavacha --- Security & Privacy** is the runtime authorization boundary for
security-sensitive capability execution and filesystem source/destination
safety.

Plugins declare the security-sensitive privileges they require. Kavacha checks
those declarations against the active `SecurityPolicy` before Pravaha delegates
execution to Yantra. Kavacha does not become a network proxy, credential vault,
PII scanner, HTTP client, secret store, or second cloud runtime.

### Canonical Runtime Gate

``` text
PluginInfo.security
       ↓
Kavacha.authorize(SecurityDeclaration)
       ↓
SecurityPolicy
├── PII access permitted?
├── network access permitted?
├── external processing permitted?
└── declared secret names permitted?
       ↓
Approved capability execution
       ↓
Yantra / Shakti
```

The gate is capability-execution authorization, not per-HTTP-request transport
interception. A cloud plugin that declares network/external access is denied
before its capability executes when operator policy does not permit those
privileges.

### Plugin Security Declaration

Security requirements are reviewable plugin metadata in
**Sankalpa --- Canonical Contracts**:

``` text
pii_access
local_processing_only
network_access
external_processing
required_secrets
```

**Agni** selects providers and **Kosh** stores their declarations. Neither Agni
nor Kosh decides security policy. Pravaha looks up the owning plugin declaration
and asks Kavacha to authorize it before execution.

Cloud providers must accurately declare their network, external-processing, PII,
and credential-name requirements. Adding a new network path without updating the
owning plugin declaration is an architecture/security defect.

### Secrets and Credentials

`required_secrets` contains logical credential names required by a plugin.
`SecurityPolicy.allowed_secrets` authorizes which declared names a runtime may
use; it does not contain or retrieve secret values.

Credential values are resolved by the owning provider/client from its supported
runtime configuration boundary, normally process environment or explicitly
injected configuration. Secret values must not be committed to project settings,
logged, placed in telemetry, or included in error messages.

Kavacha intentionally does not expose `get_secret`, vault, verifier, or outbound
request APIs. If a future concrete requirement needs centralized credential
storage or content scanning, that feature must be justified and implemented
before architecture documents claim it exists.

### Filesystem Safety

Kavacha also validates source/destination overlap for canonical runtime paths.
This is a local authorization/safety check; artifact staging and commit ownership
remain with Nabhi's artifact boundary.

### Physical Shape

``` text
kavacha/
├── service.py
└── policy.py
```

`service.py` exposes declaration authorization and path-overlap validation.
`policy.py` owns immutable policy evaluation. No parallel PII Manager, Network
Manager, Cloud Guard, Credential Manager, outbound gateway, verifier, or vault
is created without demonstrated need.

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
