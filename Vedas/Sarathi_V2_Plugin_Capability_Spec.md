# Sarathi V2 — Shakti — Plugin & Capability Specification

**Specification Updated:** 10-09-2026 (Asia/Kolkata)

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

To eliminate duplicated wiring and keep the core runtime generic, every plugin exposes a canonical `PluginProvider`.

```text
                     PluginProvider
                    /       |       \
                   /        |        \
          declarations   readiness   factory
               ↓            ↓          ↓
              Kosh       runtime      Agni
               │          status        ↓
               │            │      executables
               └────────────┼───────────┘
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
- **Agni (Composition Root):** Selects the active provider set, constructs global services in topological order, calls `provider.create_capabilities(services)`, and binds executables to Pravaha.
- **Kosh (Registry):** Validates and atomically registers `PluginInfo` and `CapabilityDeclaration` metadata supplied by Agni. It does not discover, import, instantiate, or execute plugins.
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
    MistralProvider(),
    GeminiProvider(),
    AzureProvider(),
    BhashiniProvider(),
)
```

Additive plugins may be supplied to the composition root via `Agni(extra_plugin_providers=...)`.

### Cloud security boundary

Cloud plugins declare their security-sensitive privileges in `PluginInfo.security`.
Before Pravaha delegates a cloud capability to Yantra, Kavacha authorizes that
owning plugin declaration against the active `SecurityPolicy`. A denied network,
external-processing, PII, or secret-name requirement therefore fails before the
cloud capability executes.

Kavacha is not an HTTP interceptor or credential vault. Cloud clients own their
provider-specific REST transport and resolve credential values from supported
runtime configuration, while Kavacha owns permission to use the declared
privileges and credential names. Secret values must never be logged or committed
to project configuration.

### 3.1 Mistral AI Cloud Plugin (`sarathi.shakti.mistral`)

The Mistral AI plugin provides cloud-based OCR (`mistral-ocr-latest`) and Translation (`mistral-large-latest`) capabilities via direct HTTP REST calls:
- **Capabilities:**
  - `mistral_ocr`: Cloud OCR supporting document markdown, layout bounding boxes, and tabular extraction into canonical `PageData` and `TableData`.
  - `mistral_translation`: Cloud-based high-accuracy multilingual document translation into canonical `CanonicalDocument`.
- **Security Declaration:**
  Declares `SecurityDeclaration(pii_access=True, local_processing_only=False, network_access=True, external_processing=True, required_secrets=("MISTRAL_API_KEY",))` and is authorized by Kavacha at the capability-execution boundary.
- **Zero-Leak Transport:**
  Direct REST client (`httpx` with `urllib` fallback) without vendor SDK telemetry. HTTP 401/429/5xx status codes and error responses sanitize raw tokens, file paths, and private payloads.

### 3.2 Google Gemini Cloud Plugin (`sarathi.shakti.gemini`)

The Google Gemini plugin provides multimodal cloud OCR (`gemini-2.5-flash`) and Translation capabilities via Google's REST API:
- **Capabilities:**
  - `gemini_ocr`: Multimodal vision OCR generating structured page content, tables, and document layout into canonical `PageData` and `TableData`.
  - `gemini_translation`: Multilingual document translation preserving canonical layout and structure.
- **Security Declaration:**
  Declares `SecurityDeclaration(pii_access=True, local_processing_only=False, network_access=True, external_processing=True, required_secrets=("GEMINI_API_KEY",))` and is authorized by Kavacha at the capability-execution boundary.
- **Zero-Leak Transport:**
  Direct REST client via `httpx` to Google Generative Language endpoints without google-genai telemetry SDKs.

### 3.3 Microsoft Azure Cloud Plugin (`sarathi.shakti.azure`)

The Microsoft Azure plugin provides Azure AI Document Intelligence layout OCR (`documentModels/prebuilt-layout`) and Azure AI Translator REST capabilities:
- **Capabilities:**
  - `azure_ocr`: Prebuilt layout document intelligence extracting word-level confidences, polygon spans, paragraphs, and tables into canonical `PageData` and `TableData`.
  - `azure_translation`: Direct Azure Translator API multilingual document translation.
- **Security Declaration:**
  Declares `SecurityDeclaration(pii_access=True, local_processing_only=False, network_access=True, external_processing=True, required_secrets=("AZURE_API_KEY", "AZURE_ENDPOINT"))` and is authorized by Kavacha at the capability-execution boundary.
- **Zero-Leak Transport:**
  Direct REST client via `httpx` targeting customer-configured regional cognitive endpoints without heavy Azure SDKs.

### 3.4 Bhashini Cloud Plugin (`sarathi.shakti.bhashini`)

The Bhashini plugin integrates Government of India's National Language Translation Mission (AI4Bharat) pipeline services:
- **Capabilities:**
  - `bhashini_ocr`: Chitrakshar Indic OCR supporting 22 scheduled Indian languages, complex Devnagari and regional scripts into canonical `PageData`.
  - `bhashini_translation`: IndicTrans2 neural machine translation across all official Indian languages and English.
- **Security Declaration:**
  Declares `SecurityDeclaration(pii_access=True, local_processing_only=False, network_access=True, external_processing=True, required_secrets=("BHASHINI_API_KEY", "BHASHINI_INFERENCE_KEY", "BHASHINI_USER_ID"))` and is authorized by Kavacha at the capability-execution boundary.
- **Zero-Leak Transport:**
  Direct REST client via `httpx` targeting MeitY/ULCA pipeline and compute inference endpoints.

### 3.5 Standardized Cloud Confidence Matrix & Pramana Telemetry

All cloud OCR providers (`mistral_ocr`, `gemini_ocr`, `azure_ocr`, `bhashini_ocr`) conform to Sarathi's canonical verification matrix:
1. **Multi-Tier Confidence Values:**
   - Word/span level: bounding polygon and token confidence where supported by provider API.
   - Page level: `min_confidence`, `max_confidence`, `confidence` (mean) recorded in `PageData.metadata`.
   - Document level: aggregate `ConfidenceValue(score, method="<provider>_mean")` attached to the top-level `Result.confidence`.
2. **Darpana Telemetry Integration:**
   - Emits `PramanaRecord` to the telemetry bus containing `overall_score`, `page_count`, `min_confidence`, `max_confidence`, and latency metrics for UI presentation in Mukha.

---

## 4. Bootstrap-Time Consistency Validation

Agni enforces fail-fast bootstrap consistency validation (`_validate_bootstrap_consistency`) during startup before any request can be dispatched:
1. **1-to-1 Parity:** Every capability declaration registered in `Kosh` must have an executable binding in runtime capabilities, and every executable capability must have a registered declaration in `Kosh`.
2. **Declaration Match:** The executable's declaration must strictly equal the declaration registered in `Kosh`.
3. **No Duplicates:** Duplicate plugin IDs or duplicate capability IDs across providers are rejected at bootstrap with `DoshError(FailureCode.VALIDATION_FAILED)`.
4. **Replacement Composition:** When `Agni(capabilities=...)` is passed for testing or micro-runtimes, Agni selects only providers corresponding to the supplied replacement capabilities and Kosh registers only those declarations, preserving 1-to-1 consistency without phantom registry entries.

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
| **Darshana — Identify** | Defined in Section 7 of this specification | `DarshanaProvider` |
| **Shruti — Read / Native Extraction** | [Native Extraction Specification](Sarathi_V2_Native_Extraction_Spec.md) | `NativeExtractionProvider` |
| **OCR** | [OCR Specification](Sarathi_V2_OCR_Spec.md) | `OCRProvider` |
| **Roopa — Convert / Font Conversion** | [Font Conversion Specification](Sarathi_V2_Font_Conversion_Spec.md) | `FontConversionProvider` |
| **Translation** | [Translation Specification](Sarathi_V2_Translation_Spec.md) | `TranslationProvider` |
| **Bank Statement Consolidation** | [Bank Statement Consolidation Specification](Sarathi_V2_Bank_Statement_Spec.md) | `BankStatementsProvider` |
| **Mistral Cloud (OCR & Translation)** | Defined in Section 3.1 of this specification | `MistralProvider` |
| **Google Gemini (OCR & Translation)** | Defined in Section 3.2 of this specification | `GeminiProvider` |
| **Microsoft Azure (Layout OCR & Translation)** | Defined in Section 3.3 of this specification | `AzureProvider` |
| **Bhashini Indic AI (OCR & Translation)** | Defined in Section 3.4 of this specification | `BhashiniProvider` |
