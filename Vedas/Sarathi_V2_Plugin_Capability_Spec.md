# Sarathi V2 — Shakti — Plugin & Capability Specification

**Specification Updated:** 05-09-2026, 11:22 PM IST (Asia/Kolkata)

This file owns shared plugin rules, **PluginProvider** integration contracts, **Darshana — Identify**, capability readiness architecture, operator enablement policies, and capability specification routing. Capability-local behavior lives only in its owning file.

---

## 1. Shakti --- Plugin Ecosystem

**Shakti --- Plugin Ecosystem** contains document and business capabilities.

```text
Plugin owns:
    domain/capability behavior
    capability-specific preprocessing
    capability-specific confidence and validation
    engine adapters where required
    validation and use of its approved Anubhava data
    operational readiness probing

Plugin does not own:
    worker pools or hardware allocation (owned by Yantra)
    global cache or runtime state (owned by Smriti)
    telemetry or logging infrastructure (owned by Darpana)
    presentation framework (owned by Mukha)
    global configuration (owned by Sutra)
    security authorization (owned by Kavacha)
    pipeline execution and step transitions (owned by Pravaha)
    registry state (owned by Kosh)
```

A plugin uses canonical contracts and shared services through their public boundaries. Its `plugin.py` remains a thin declaration/integration boundary, not a local service container.

---

## 2. Canonical PluginProvider & PluginServices Boundary

To eliminate duplicated wiring, decouple engines from metadata discovery, and keep core runtime generic, every plugin exposes a canonical `PluginProvider`.

```text
                     PluginProvider
                    /       |       \
                   /        |        \
          declarations   readiness   factory
               ↓            ↓          ↓
             Dvara       runtime      Agni
               ↓          status        ↓
              Kosh          │      executables
                \           │          /
                 \          ▼         /
                  └────── Mukha      /
                         │          /
                         └─────────┘
                            ↓
                          Manthan
                            ↓
                         Pravaha
                            ↓
                        Capability
```

### 2.1 PluginProvider Protocol (`sarathi.sankalpa.plugin`)
Every Shakti plugin provider satisfies:
- `plugin_info`: Returns `PluginInfo` metadata and declared capability IDs.
- `declarations`: Returns tuple of `CapabilityDeclaration` instances describing capabilities provided.
- `create_capabilities(services)`: Constructs executable `Capability` instances using approved shared services (`PluginServices`).
- `readiness(services)`: Audits operational readiness of declared capabilities and returns `Mapping[str, CapabilityReadiness]`.

### 2.2 PluginServices Contract (`sarathi.sankalpa.plugin`)
Immutable dataclass providing canonical injected shared dependencies to providers:
- `yantra`: Hardware execution manager.
- `darpana`: Telemetry and timing service.
- `kavacha`: Security and policy service.
- `settings`: Active runtime settings.
- `data_root`: Canonical data directory root.

### 2.3 Strict Ownership Separation
- **Dvara (Nabhi):** Discovers plugin metadata and registers `PluginInfo` and `CapabilityDeclaration` into `Kosh`. Dvara receives providers; it never imports or instantiates execution engines.
- **Agni (Kernel):** Composition root and lifecycle manager. Constructs global services in topological order, calls `provider.create_capabilities(services)` on active providers, and binds executables to Pravaha.
- **Mukha (Presentation):** Consumes presentation facts only. Has zero direct imports of OCR engines, bank detectors, font JSON globbing, or translation dependencies. Probes readiness solely via `Agni.audit_readiness()`.

---

## 3. Canonical Built-In Provider Catalog

The built-in Shakti capability plugins are declared in a canonical catalog in `sarathi.shakti.providers`:

```python
BUILTIN_PLUGIN_PROVIDERS: tuple[PluginProvider, ...] = (
    DarshanaProvider(),
    NativeExtractionProvider(),
    OCRProvider(),
    BankStatementsProvider(),
    FontConversionProvider(),
    TranslationProvider(),
)
```

Additive plugins may be supplied to the composition root via `Agni(extra_plugin_providers=...)`.

---

## 4. Bootstrap-Time Consistency Validation

Agni enforces fail-fast bootstrap consistency validation (`_validate_bootstrap_consistency`) during startup before any request can be dispatched:
1. **1-to-1 Parity:** Every capability declaration registered in `Kosh` must have an executable binding in runtime capabilities, and every executable capability must have a registered declaration in `Kosh`.
2. **Declaration Match:** The executable's declaration must strictly equal the declaration registered in `Kosh`.
3. **No Duplicates:** Duplicate plugin IDs or duplicate capability IDs across providers are rejected at bootstrap with `DoshError(FailureCode.VALIDATION_FAILED)`.
4. **Replacement Composition:** When `Agni(capabilities=...)` is passed for testing or micro-runtimes, Dvara registers only the providers corresponding to the supplied replacement capabilities, preserving 1-to-1 consistency without lingering phantom declarations in Kosh.

---

## 5. Capability Readiness Model

Operational readiness is kept separate from capability execution:
- **`ReadinessStatus`:** Enum classifying readiness state:
  - `READY`: Fully operational.
  - `DISABLED`: Disabled by operator configuration.
  - `INVALID_CONFIGURATION`: Missing or invalid configuration.
  - `DEPENDENCY_UNAVAILABLE`: Missing optional extra dependencies or model assets.
  - `INCOMPATIBLE`: Hardware or environment incompatibility.
- **`CapabilityReadiness`:** Immutable dataclass (`ready: bool`, `status: ReadinessStatus`, `reason: str`, `failure_code: FailureCode | None`).
- **`Agni.audit_readiness(force_refresh: bool = False)`:** Thread-safe memoized readiness audit across active providers, returning `MappingProxyType[str, CapabilityReadiness]`.

---

## 6. Operator Enablement vs. Kavacha Security Authorization

Sarathi maintains a strict separation between operator enablement, readiness, and security authorization:

```text
Enablement:
    Should this plugin participate in this runtime?
    (Controlled by operator via Sutra settings: [plugins] disabled = [...])

Readiness:
    Can this plugin operate with current configuration/dependencies?
    (Audited by PluginProvider via readiness probes)

Authorization:
    May this plugin perform its declared security-sensitive operation?
    (Enforced at runtime by Kavacha against SecurityDeclaration)
```

Operator disablement is configured via Sutra:
```toml
[plugins]
disabled = ["shakti.translation"]
```
When a plugin is disabled:
1. It is excluded from active providers during default Agni composition.
2. It is omitted from Kosh registration and executable capability construction.
3. `Agni.audit_readiness()` reports its declared capabilities with `ReadinessStatus.DISABLED`.
4. Kavacha security declarations remain untouched; disablement is never implemented by mutating security rules.

---

## 7. Darshana --- Identify

**Darshana --- Identify** determines what the input is. It may report media or
document type, structural characteristics, likely document family, and other
evidence required for capability resolution.

```text
Document
    ↓
Darshana — Identify
    ↓
Document characteristics
```

The core does not identify PDFs, bank statements, scans, or other domain types.

---

## 8. Capability Specifications

| Capability | Canonical local specification | Owning Provider |
|---|---|---|
| **Shruti — Read / Native Extraction** | [Native Extraction Specification](Sarathi_V2_Native_Extraction_Spec.md) | `NativeExtractionProvider` |
| **OCR** | [OCR Specification](Sarathi_V2_OCR_Spec.md) | `OCRProvider` |
| **Roopa — Convert / Font Conversion** | [Font Conversion Specification](Sarathi_V2_Font_Conversion_Spec.md) | `FontConversionProvider` |
| **Translation** | [Translation Specification](Sarathi_V2_Translation_Spec.md) | `TranslationProvider` |
| **Bank Statement Consolidation** | [Bank Statement Consolidation Specification](Sarathi_V2_Bank_Statement_Spec.md) | `BankStatementsProvider` |
