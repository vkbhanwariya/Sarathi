# Sarathi V2 — Implementation Guide

**Specification Updated:** 06-09-2026, 09:45 PM IST (Asia/Kolkata)

This file contains the detailed canonical specification for implementation order, physical structure, wiring, testing, dependencies, and architecture status.
The main [Sarathi V2 README](../README.md) retains only stable architecture, ownership, and document routing.

## Development Baseline

Sarathi V2 targets:

-   Windows 11 x64
-   Python 3.13.15
-   uv 0.12.7
-   Windows PowerShell 5.1 or newer PowerShell; no exact PowerShell version pin
-   `src/` package layout
-   local `.venv`
-   `pyproject.toml` as the dependency declaration source of truth
-   `uv.lock` as the exact resolved dependency lock

Primary development hardware:

-   Intel Core Ultra 5 125H
-   14 physical / 18 logical CPU cores
-   Intel integrated GPU
-   Intel AI Boost NPU
-   24 GB DDR5-5600 RAM
-   approximately 1 TB NVMe SSD

Sarathi is editor-agnostic. No runtime behavior depends on a specific IDE.

## Core Capabilities and Implementation Order

Sarathi delivers the canonical user-facing requirement set:

1.  Different-bank / different-format Bank Statement Consolidation
2.  **Shruti --- Read / Native Extraction**
3.  OCR
4.  **Roopa --- Convert / Font Conversion**
5.  Translation

Dependency locking follows the technical dependency chain rather than the user-facing priority:

``` text
Shruti — Read / Native Extraction
→ OCR
→ Roopa — Convert / Font Conversion
→ Translation
→ Bank Statement Consolidation
```

Core/runtime implementation order:

``` text
Sankalpa — Canonical Contracts
→ Dosh — Error System
→ Sutra — Configuration
→ Kavacha — Security & Privacy
→ Yantra — Resource & Execution Manager
→ Darpana — Telemetry & Tracing
→ Smriti — Cache & Runtime State
→ Nabhi — Core Kernel, including Pravaha
→ Agni — Runtime Bootstrap
→ Mukha — Console & Presentation
→ Shakti — Core capabilities
```

**Anubhava --- Validated Experience Data** has no runtime implementation
step. An owning capability adds its TOML only after approved reusable
knowledge actually exists.

Dependency acceptance priority remains:

``` text
Python 3.13.15 compatibility
→ Windows 11 x64 compatibility
→ speed
→ accuracy
→ stability
→ demonstrated legacy compatibility
→ dependency weight
```

Legacy compatibility is not hypothetical for the bank/native ingestion path: true `.xls`, HTML-disguised `.xls`, mixed encodings, and other historical formats are demonstrated inputs. Targeted fallbacks are therefore justified where the representative corpus requires them.

------------------------------------------------------------------------
## Primary, Fallback and External Engine Strategy

A capability starts with one strong local primary path and adds only proven fallback paths.

``` text
Input
→ Primary local engine/path
   ├── sufficient → Result
   └── unsupported / failed / insufficient evidence
        ↓
   Targeted local fallback
        ↓
   Validation
        ↓
   External/cloud fallback only when genuinely needed
        ↓
   Kavacha — Security & Privacy approval
```

Fallback should target the weak page, region, row, or segment where possible instead of blindly rerunning an entire document. A third local engine is not added merely for theoretical redundancy.

------------------------------------------------------------------------
## Code, Data and Documentation Separation

``` text
Code describes behavior.
Data describes mappings, configuration, profiles, and reference knowledge.
README describes stable architecture, ownership, contracts, and conventions.
pyproject.toml / uv.lock describe the current dependency set and exact resolution.
```

Preferred representations:

``` text
Bank generic/profile aliases      → YAML / JSON
Font glyph mappings               → JSON
Translation glossaries            → JSON / CSV
Language aliases                  → YAML / JSON
Regex/reference catalogs          → data/config where appropriate
Runtime settings                  → TOML / YAML
Processing profiles               → TOML
Validated experience overlays     → `data/<capability>/anubhava.toml`
Large analytical tabular data     → Parquet
Cache/searchable runtime history  → SQLite only where that specific service needs it
Algorithms and decisions          → Python
```

Human-editable data is loaded and validated into a prepared runtime representation for fast repeated use. YAML/TOML must not become a pseudo-programming language. Anubhava TOML is read using the owning capability's existing data path and the standard-library `tomllib`; it adds no runtime package or generic manager.

### Dynamic-update rule

Mutable inventories must have one source of truth. The README therefore does not maintain exhaustive lists of every bank profile, font profile, OCR profile/calibration asset, translation glossary, model version, or package version when those are already discoverable from `data/`, `pyproject.toml`, or `uv.lock`.

Adding validated capability data updates its owning data source and tests. A
capability specification changes only when its behavior, schema, dependency
direction, or acceptance boundary changes. The main README changes only when
architecture, ownership, or documentation routing changes.

------------------------------------------------------------------------
## Canonical Project Structure

``` text
Sarathi/
├── arambha.bat
├── pyproject.toml
├── uv.lock
├── .python-version
├── README.md
│
├── scripts/
│   ├── Initialize-SarathiArchitecture.ps1
│   ├── Setup-OCRModels.ps1
│   └── Setup-SarathiEnvironment.ps1
│
├── src/
│   └── sarathi/
│       ├── __init__.py
│       ├── __main__.py
│       ├── agni/
│       │   ├── __init__.py
│       │   ├── bootstrap.py
│       │   ├── dispatcher.py
│       │   ├── preflight.py
│       │   ├── readiness.py
│       │   └── wiring.py
│       ├── sankalpa/
│       │   ├── plugin.py
│       │   ├── capability.py
│       │   ├── readiness.py
│       │   ├── request.py
│       │   ├── result.py
│       │   ├── artifact.py
│       │   ├── context.py
│       │   ├── document.py
│       │   ├── cancellation.py
│       │   └── execution_profile.py
│       ├── nabhi/
│       │   ├── __init__.py
│       │   ├── dvara.py
│       │   ├── kosh.py
│       │   ├── prana.py
│       │   ├── manthan.py
│       │   ├── quarantine.py
│       │   ├── pravaha/
│       │   │   ├── __init__.py
│       │   │   ├── common.py
│       │   │   ├── engine.py
│       │   │   ├── lifecycle.py
│       │   │   └── pipeline.py
│       │   └── artifacts/
│       │       ├── __init__.py
│       │       ├── atomic_io.py
│       │       ├── boundary.py
│       │       ├── finalization.py
│       │       ├── manifest.py
│       │       ├── paths.py
│       │       ├── promotion.py
│       │       └── workspace.py
│       ├── yantra/
│       │   ├── manager.py
│       │   ├── devices.py
│       │   └── resources.py
│       ├── darpana/
│       │   ├── service.py
│       │   ├── maruti.py
│       │   ├── pramana.py
│       │   └── history.py
│       ├── mukha/
│       │   ├── intake.py
│       │   ├── presenter.py
│       │   ├── state.py
│       │   └── web/
│       │       ├── app.css
│       │       ├── app.html
│       │       ├── app.js
│       │       ├── http_handler.py
│       │       ├── native_picker.py
│       │       ├── runner.py
│       │       ├── server.py
│       │       └── state_builder.py
│       ├── smriti/
│       │   ├── key.py
│       │   ├── memory.py
│       │   ├── store.py
│       │   ├── policy.py
│       │   └── serialization.py
│       ├── kavacha/
│       │   ├── service.py
│       │   └── policy.py
│       ├── sutra/
│       │   ├── loader.py
│       │   └── settings.py
│       ├── dosh/
│       │   └── errors.py
│       └── shakti/
│           ├── artifact_naming.py
│           ├── docx_exporter/
│           │   ├── __init__.py
│           │   ├── exporter.py
│           │   ├── helpers.py
│           │   ├── section_builder.py
│           │   ├── styles.py
│           │   └── table_builder.py
│           ├── providers.py
│           ├── text/
│           │   ├── legacy_detection.py
│           │   └── span_protection.py
│           ├── darshana/
│           │   ├── capability.py
│           │   ├── facts.py
│           │   ├── identifier.py
│           │   ├── plugin.py
│           │   └── provider.py
│           ├── native_extraction/
│           │   ├── __init__.py
│           │   ├── capability.py
│           │   ├── detector.py
│           │   ├── plugin.py
│           │   ├── provider.py
│           │   └── readers/
│           │       ├── __init__.py
│           │       ├── common.py
│           │       ├── delimited.py
│           │       ├── docx.py
│           │       ├── html.py
│           │       ├── pdf.py
│           │       └── spreadsheet.py
│           ├── ocr/
│           │   ├── __init__.py
│           │   ├── capability.py
│           │   ├── plugin.py
│           │   ├── provider.py
│           │   ├── typography.py
│           │   └── engine/
│           │       ├── __init__.py
│           │       ├── common.py
│           │       ├── coordinator.py
│           │       ├── factory.py
│           │       ├── openvino.py
│           │       ├── parser.py
│           │       ├── preprocessing.py
│           │       ├── rasterize.py
│           │       ├── readiness.py
│           │       └── tesseract.py
│           ├── font_conversion/
│           │   ├── akshara.py
│           │   ├── capability.py
│           │   ├── converter.py
│           │   ├── detector.py
│           │   ├── font_size_normalizer.py
│           │   ├── models.py
│           │   ├── plugin.py
│           │   ├── protector.py
│           │   ├── provider.py
│           │   └── validator.py
│           ├── translation/
│           │   ├── capability.py
│           │   ├── detector.py
│           │   ├── engine.py
│           │   ├── glossary.py
│           │   ├── models.py
│           │   ├── plugin.py
│           │   ├── protector.py
│           │   ├── provider.py
│           │   └── typography.py
│           └── bank_statements/
│               ├── capability.py
│               ├── consolidator.py
│               ├── converter.py
│               ├── deduplicator.py
│               ├── detector.py
│               ├── mapper.py
│               ├── models.py
│               ├── plugin.py
│               ├── provider.py
│               ├── row_classifier.py
│               ├── table_locator.py
│               └── validator.py
│
├── data/
│   ├── banks/
│   ├── fonts/
│   ├── ocr/
│   │   └── anubhava.toml         # only after validated OCR knowledge exists
│   ├── font_conversion/
│   │   └── anubhava.toml         # only after validated mapping knowledge exists
│   ├── translation/
│   │   └── anubhava.toml         # only after approved corrections exist
│   └── bank_statements/
│       └── anubhava.toml         # only after validated consolidation knowledge exists
├── config/
│   └── settings.toml             # canonical starter runtime settings
├── Input/                         # optional convenience inbox
├── Output/                        # committed user artifacts by requirement/run
├── Runtime/
│   ├── Work/                      # per-run staging
│   ├── Quarantine/                # Pravaha-owned isolation state
│   ├── Telemetry/                 # Darpana history
│   └── Cache/                     # Smriti reusable-result state
├── tests/
│   ├── agni/
│   ├── architecture/
│   ├── bank_statements/
│   ├── cancellation/
│   ├── capabilities/
│   ├── configuration/
│   ├── contracts/
│   ├── dosh/
│   ├── font_conversion/
│   ├── intake/
│   ├── integration/
│   ├── kernel/
│   ├── mukha/
│   ├── native_extraction/
│   ├── ocr/
│   ├── security/
│   ├── shakti/
│   ├── smriti/
│   ├── telemetry/
│   ├── translation/
│   └── yantra/
└── Vedas/
    ├── architecture.manifest.json
    ├── architecture.manifest.schema.json
    ├── Sarathi_V2_Core_Runtime_Spec.md
    ├── Sarathi_V2_Shared_Services_Spec.md
    ├── Sarathi_V2_Mukha_Screen_Spec.md
    ├── Sarathi_V2_Plugin_Capability_Spec.md
    ├── Sarathi_V2_Native_Extraction_Spec.md
    ├── Sarathi_V2_OCR_Spec.md
    ├── Sarathi_V2_Font_Conversion_Spec.md
    ├── Sarathi_V2_Translation_Spec.md
    ├── Sarathi_V2_Bank_Statement_Spec.md
    └── Sarathi_V2_Implementation_Guide.md
```

This section defines the physical project layout only. Detailed Python ownership
is defined once in **Python File Responsibilities** below. Tests follow the
canonical owner/boundary they verify; capability-local acceptance tests remain
under the relevant capability area. Dynamic data directories are intentionally
shown as directories rather than exhaustive inventories. The shown `anubhava.toml`
paths are conventions, not a requirement to create empty files.

------------------------------------------------------------------------
## Python File Responsibilities

This is the single authoritative map for Python-file ownership. Capability sections define behavior and flow; this section defines where that behavior is implemented. A file is created only when its listed responsibility is needed.

### Project Automation

- `scripts/Initialize-SarathiArchitecture.ps1` — idempotently creates the canonical directory/package scaffold and minimal project metadata without overwriting existing work or creating capability implementations.
- `scripts/Setup-OCRModels.ps1` — provisions and verifies declared RapidOCR ONNX model assets against `data/ocr/manifest.json` checksums under strict network isolation.
- `scripts/Setup-SarathiEnvironment.ps1` — verifies the locked uv/Python baseline, creates `.venv`, validates or creates `uv.lock`, and installs only dependencies declared by `pyproject.toml`/`uv.lock`.

### Package and Startup

- `src/sarathi/__init__.py` — package metadata and minimal package-level exports only; no runtime initialization.
- `src/sarathi/__main__.py` — minimal Python application entry point; hands startup to **Agni — Runtime Bootstrap**.
- `src/sarathi/agni/bootstrap.py` — composition root class (`Agni`); coordinates preflight checks, dependency wiring, readiness probes, and request dispatching without absorbing subsystem logic.
- `src/sarathi/agni/preflight.py` — isolated filesystem root creation, access validation, and preflight sanity checks.
- `src/sarathi/agni/wiring.py` — topological dependency wiring and subsystem instantiation.
- `src/sarathi/agni/readiness.py` — system-wide capability readiness auditing and probe dispatch.
- `src/sarathi/agni/dispatcher.py` — presentation-to-kernel request preparation, validation, and execution dispatch.

### Sankalpa — Canonical Contracts

- `sankalpa/plugin.py` — one canonical plugin contract plus reviewable security declarations. Enforcement remains with **Kavacha — Security & Privacy**.
- `sankalpa/capability.py` — capability declaration, support information, execution modes, and execution/device requirements.
- `sankalpa/readiness.py` — canonical capability readiness probe declarations (`ReadinessStatus`, `CapabilityReadiness`).
- `sankalpa/request.py` — canonical processing request.
- `sankalpa/result.py` — canonical `Result`: data, artifact references, confidence, warnings, provenance, and metadata. Result may carry an optional `next_requirement` for direct runtime continuation.
- `sankalpa/artifact.py` — typed `InputRef`, `ArtifactIntent`, and confirmed `ArtifactRef` contracts; no file I/O.
- `sankalpa/context.py` — request/trace identity and controlled shared-runtime access; not a global mutable state bucket.
- `sankalpa/document.py` — canonical document/data representation exchanged across capabilities without teaching the core individual file formats.
- `sankalpa/cancellation.py` — cooperative cancellation token contract (CancellationToken) for responsive aborts without state corruption.
- `sankalpa/execution_profile.py` — common Instant, Accurate, Layout Preserving, and Custom processing-profile contract.

### Nabhi — Core Kernel

- `nabhi/dvara.py` — **Dvara — Plugin Discovery**; discovers built-ins/external plugins according to the discovery policy.
- `nabhi/kosh.py` — **Kosh — Plugin & Capability Registry**; stores registered plugin/capability declarations and lookup metadata.
- `nabhi/prana.py` — **Prana — Lifecycle Manager**; coordinates startup/shutdown lifecycle of registered runtime components.
- `nabhi/manthan.py` — **Manthan — Capability Resolver**; resolves the capabilities required by a request/document without implementing them.
- `nabhi/quarantine.py` — focused Pravaha-owned quarantine persistence/state: hashed failure manifests, isolation state, retry status, release, and terminal quarantine. It is not a second manager/orchestrator.
- `nabhi/pravaha/` — **Pravaha — Dynamic Pipeline Engine** subpackage:
  - `engine.py`: Canonical `Pravaha` coordinator managing plan execution, quarantine, and recovery.
  - `pipeline.py`: Plan execution loop, capability dependency sequencing, and step hand-off.
  - `lifecycle.py`: Retry lifecycle coordination, exception handling, and quarantine storage.
  - `common.py`: Pipeline execution state, step records, and shared internal contracts.
- `nabhi/artifacts/` — global path-resolution, staging, collision, atomic-commit, and run-manifest subpackage:
  - `boundary.py`: Canonical `ArtifactBoundary` coordinator resolving roots, staging paths, and commits.
  - `workspace.py`: Per-run staging directory lifecycle (`RunWorkspace`).
  - `promotion.py`: Safe atomic promotion of staged artifacts to confirmed output destinations.
  - `finalization.py`: Collision handling, relative path translation, and run-manifest emission.
  - `atomic_io.py`: SHA-256 computation and collision-safe atomic file writing.
  - `manifest.py`: Cryptographically validated run manifest serialization.
  - `paths.py`: Canonical path normalization, sanitization, and containment checks.

### Yantra — Resource & Execution Manager

- `yantra/manager.py` — public Yantra coordinator for allocation, release, and approved capability execution.
- `yantra/devices.py` — factual CPU/GPU/NPU/backend inventory and device information.
- `yantra/resources.py` — allocation state, compatibility, limits, and resource decisions.
- `yantra/executor.py` (optional/future) — globally managed execution worker facility; create only if a genuinely separate execution responsibility emerges.

### Darpana — Telemetry & Tracing

- `darpana/service.py` — one public Darpana service, bounded thread-safe telemetry snapshots/emission, and timing boundary.
- `darpana/maruti.py` — **Maruti — Runtime, Logging & Performance Telemetry** measurement and factual record contracts.
- `darpana/pramana.py` — **Pramana — Confidence & Accuracy Telemetry** evidence recording and quality record contracts.
- `darpana/history.py` — sequential and persistent SQLite/JSONL run history storage.

### Mukha — Console & Presentation

- `mukha/presenter.py` — factual projection of canonical runtime/telemetry state into typed presentation views; no execution/lifecycle/security decisions.
- `mukha/state.py` — typed immutable presentation/view-state contracts.
- `mukha/intake.py` — input discovery, normalization, validation, and safe path intake.
- `mukha/web/server.py` — loopback Local Web dashboard HTTP/SSE server coordinating runner threads and HTTP handlers.
- `mukha/web/runner.py` — background run thread execution, progress observation, and cancellation supervision.
- `mukha/web/state_builder.py` — presentation projection builder transforming Agni runtime state into web DTOs.
- `mukha/web/http_handler.py` — HTTP/1.1 REST & SSE request handler serving UI assets and endpoints (`/api/state`, `/api/events`, `/api/run`, `/api/cancel`, `/api/action`, `/api/browse`, `/api/history`, `/api/review`, `/api/artifact`).
- `mukha/web/native_picker.py` — controlled native Windows file and folder picker dialog integration.

### Smriti — Cache & Runtime State

- `smriti/key.py` — deterministic canonical cache-key computation across requests, profiles, capabilities, and settings hashes.
- `smriti/memory.py` — bounded thread-safe in-memory L1 cache tier with synchronized LRU eviction.
- `smriti/store.py` — persistent SQLite L2 cache store with traversal-safe key names and unified two-tier `SmritiCache` service.
- `smriti/policy.py` — TTL, capacity, and cache validity policy enforcement.
- `smriti/serialization.py` — deterministic lossless binary serialization for `CanonicalDocument` and artifact payloads with magic header validation.

### Anubhava — Validated Experience Data

Anubhava owns no Python files. Each applicable capability validates and reads
its own `data/<capability>/anubhava.toml` through its existing data path.
No generic Anubhava service, plugin, loader, writer, database, or optimizer
is permitted.

### Kavacha — Security & Privacy

- `kavacha/service.py` — public Kavacha authorization and path/security validation boundary currently implemented.
- `kavacha/policy.py` — security policy evaluation and typed policy decisions.
- `kavacha/verifier.py` (optional/future) — PII/sensitive-content verification and outbound gate; create only when that distinct responsibility is implemented.
- `kavacha/vault.py` (optional/future) — secure local secret/credential boundary; create only when that distinct responsibility is implemented.

### Sutra — Configuration

- `sutra/loader.py` — loads project/runtime configuration and declarative external definitions.
- `sutra/settings.py` — validates and exposes runtime settings.
  Default Input, Output, and Runtime roots are settings; Sutra performs no
  scanning, writing, or artifact commit.

### Dosh — Error System

- `dosh/errors.py` — small shared error vocabulary used across core and capabilities. Classification/representation lives here; pipeline recovery decisions remain with Pravaha.

### Shakti — Capability & Shared Ecosystem Files

Capability `plugin.py` and `provider.py` files are thin boundaries: declaration, supported modes/inputs, dependency hand-off, readiness auditing, and canonical request/result integration. They do not become local service containers.

#### Shared Shakti Infrastructure

- `shakti/providers.py` — canonical catalog of built-in `PluginProvider` instances (`BUILTIN_PLUGIN_PROVIDERS`).
- `shakti/artifact_naming.py` — deterministic canonical naming generator for Shakti artifact outputs.
- `shakti/docx_exporter/` — shared multi-capability Word document exporter preserving style hierarchy, cell borders, dynamic visual scaling, and script segmentation:
  - `exporter.py`: High-level `DocxExporter` facade and artifact transformation entry points (`build_docx_payload`, `transform_docx_artifact`).
  - `styles.py`: XML-level style resolver (`DocxStyleResolver`) traversing `rPr` -> `rStyle` -> `pStyle` -> `basedOn` -> `docDefaults`.
  - `table_builder.py`: Cell border styling, table grid management, and cell text population.
  - `section_builder.py`: Document body population, paragraph styling, and run construction.
  - `helpers.py`: XML namespace constants (`_W_NS`, `_A_NS`) and safe run stitching utilities.
- `shakti/text/legacy_detection.py` — shared heuristics for legacy font and script detection.
- `shakti/text/span_protection.py` — shared tokenization and placeholder restoration for protected spans.

#### Darshana — Identify

- `shakti/darshana/plugin.py` — plugin registration and capability declaration metadata.
- `shakti/darshana/provider.py` — `DarshanaProvider` constructing executable capability and auditing readiness.
- `shakti/darshana/capability.py` — executable document identification capability implementing `Capability`.
- `shakti/darshana/identifier.py` — multi-signal document family, media type, and content identification engine.
- `shakti/darshana/facts.py` — measured physical file and stream facts extractor.

#### Shruti — Read / Native Extraction

- `shakti/native_extraction/plugin.py` — plugin registration and capability declaration metadata.
- `shakti/native_extraction/provider.py` — `NativeExtractionProvider` constructing executable capability and auditing readiness.
- `shakti/native_extraction/capability.py` — executable native extraction capability implementing `Capability`.
- `shakti/native_extraction/detector.py` — byte-signature and content format detection.
- `shakti/native_extraction/readers/` — format-specific native reader subpackage:
  - `pdf.py`: PDF native text, layout, and table extraction via PyMuPDF.
  - `spreadsheet.py`: Excel (`.xlsx`, `.xlsm`, legacy `.xls`, `.xml`) extraction via Calamine/OpenPyXL/xlrd.
  - `html.py`: HTML table and structured document parsing via BeautifulSoup.
  - `docx.py`: Native Word document paragraph, table, and run extraction.
  - `delimited.py`: Robust CSV, TSV, and plain text extraction with encoding detection.
  - `common.py`: Shared reader abstractions, table conversion helpers, and cell normalization.
- `shakti/native_extraction/__init__.py` — public package exports.

#### OCR

- `shakti/ocr/plugin.py` — plugin registration and capability declaration metadata.
- `shakti/ocr/provider.py` — `OCRProvider` constructing executable capability and auditing dependency readiness.
- `shakti/ocr/capability.py` — executable OCR capability and input/prior-result integration.
- `shakti/ocr/typography.py` — line-height font size inference and Devanagari/English font standardization.
- `shakti/ocr/engine/` — modular OCR execution engine subpackage:
  - `coordinator.py`: High-level engine coordinator managing inference execution, device fallback, and memory release.
  - `rapidocr.py`: RapidOCR + OpenVINO primary engine adapter.
  - `tesseract.py`: Tesseract fallback adapter and executable locator.
  - `factory.py`: Engine instance lifecycle, backend instantiation, and device parameter binding.
  - `parser.py`: OCR bounding box and text line parsing and confidence aggregation.
  - `preprocessing.py`: Image contrast evaluation, thresholding, and binarization.
  - `rasterize.py`: PDF-to-image rasterization and embedded image extraction via PyMuPDF.
  - `readiness.py`: OpenVINO backend verification and Tesseract executable detection probes.
  - `openvino.py`: OpenVINO device resolution and execution provider validation.
  - `common.py`: Shared OCR dataclasses, constants, and stage identifiers.
- `shakti/ocr/__init__.py` — public package exports.

#### Roopa — Convert / Font Conversion

- `shakti/font_conversion/plugin.py` — font-conversion capability boundary.
- `shakti/font_conversion/provider.py` — `FontConversionProvider` constructing executable capability and auditing readiness.
- `shakti/font_conversion/capability.py` — executable font conversion capability with batch escalation and item-scoped telemetry.
- `shakti/font_conversion/models.py` — canonical dataclasses (`LegacyFontProfile`, `FontEvidence`, `LogicalRun`, `ConversionPlan`, `ConversionMetrics`).
- `shakti/font_conversion/akshara.py` — universal Unicode Devanagari cluster synthesis, prefix matra reordering, and reph positioning invariants.
- `shakti/font_conversion/detector.py` — font alias resolution, digraph candidate scoring, and run-level profile decision.
- `shakti/font_conversion/converter.py` — precompiled transducer execution, reverse mapping, and two-tier Anubhava corrections.
- `shakti/font_conversion/protector.py` — protected span detection and byte-for-byte PUA restoration (URLs, dates, Latin terms).
- `shakti/font_conversion/font_size_normalizer.py` — dynamic visual font-size compensation utility scaling legacy 16 pt body text to 12 pt baseline.
- `shakti/font_conversion/validator.py` — mapping coverage calculation and structural Devanagari integrity validation.

#### Translation

- `shakti/translation/plugin.py` — translation plugin registration and capability declaration metadata.
- `shakti/translation/provider.py` — `TranslationProvider` constructing executable capability, Yantra device binding, and model readiness probes.
- `shakti/translation/capability.py` — executable translation capability coordinating sentence processing and escalation.
- `shakti/translation/models.py` — typed translation request, segment, and result dataclasses.
- `shakti/translation/detector.py` — source language identification and Unicode script verification.
- `shakti/translation/protector.py` — legal term, citation, number, date, and reference span protection.
- `shakti/translation/engine.py` — IndicTrans2 distilled 200M + CTranslate2 inference engine with dynamic VRAM batching.
- `shakti/translation/glossary.py` — static terminology dictionary and glossary lookup.
- `shakti/translation/typography.py` — script-aware typography mapping (`Nirmala UI` / `Times New Roman`).

#### Bank Statement Consolidation

- `shakti/bank_statements/plugin.py` — bank-statement capability boundary and orchestration hand-off to canonical pipeline.
- `shakti/bank_statements/provider.py` — `BankStatementsProvider` constructing executable capability and auditing readiness.
- `shakti/bank_statements/capability.py` — executable bank consolidation capability integrating table extraction, row classification, and metadata retention.
- `shakti/bank_statements/models.py` — typed Decimal-based financial models (`BankStatement`, `Transaction`, `AccountIdentity`, `ValidationIssue`).
- `shakti/bank_statements/detector.py` — bank/profile identification plus account/statement clues using multi-signal evidence.
- `shakti/bank_statements/table_locator.py` — classifies extracted tables as transaction, continuation, metadata, EOD/summary, or unrelated.
- `shakti/bank_statements/row_classifier.py` — classifies raw rows as transaction, continuation, opening, closing, EOD, summary, repeated header, or noise.
- `shakti/bank_statements/mapper.py` — maps source headers to canonical fields using bank exact → generic exact → bank fuzzy → generic fuzzy resolution.
- `shakti/bank_statements/converter.py` — converts dates/time, narration, references, dirty monetary values, Debit/Credit direction, balances, and currency into canonical typed values.
- `shakti/bank_statements/validator.py` — transaction invariants, Decimal financial continuity, opening/closing/EOD/source-total reconciliation, and inversion evidence.
- `shakti/bank_statements/deduplicator.py` — overlap candidate evaluation and evidence-based duplicate decisions while retaining provenance.
- `shakti/bank_statements/consolidator.py` — multi-account grouping, safe chronology, cross-statement deduplication within accounts, and lossless Parquet/XLSX export.

------------------------------------------------------------------------

## End-to-End Runtime Wiring

``` text
User selects document(s)/folder + requirement + processing mode + output root
                         ↓
                Mukha / Interface
                         ↓
        Canonical Request + typed InputRefs
                         ↓
             Agni-wired runtime services
                         ↓
               Nabhi — Core Kernel
                         ↓
             Darshana — Identify
                         ↓
          Manthan — Capability Resolver
                         ↓
              resolved dynamic plan
                         ↓
        Pravaha — Dynamic Pipeline Engine
                         ↓
       capability sequence selected for need
       ├── Shruti — Read / Native Extraction
       ├── OCR when native content is insufficient
       ├── Saar — Extract when required
       ├── Setu — Map / Normalize when required
       ├── Roopa — Convert / Font Conversion when required
       ├── Translation when required
       ├── Sangam — Consolidate when required
       └── Viveka — Analyse when requested
                         │
                         ↓
             capability execution request
                         ↓
         Kavacha — Security & Privacy
             policy enforcement
                         ↓ approved
        Yantra — Resource & Execution Manager
                         │
          CPU / GPU / NPU as compatible
                         │
                 ┌───────┴───────┐
                 ▼               ▼
         Darpana records    Smriti reuses
                         │
                         ↓
                 execution outcome
                   ├── success
                   └── failure → Dosh classifies
                                  ↓
                             Pravaha decides
                         failure / quarantine / retry
                                  ↓
                  terminal state + confirmed artifacts
                                  ↓
       Nabhi atomically commits confirmed artifacts
                   ↓
        Output/<requirement>/Run-<timestamp>-<short-id>/
                   ↓
              Canonical Result
                   ↓
          Required Information / persisted canonical dataset
```

During execution, **Pramana --- Confidence & Accuracy Telemetry** records
quality evidence but does not modify active capability data. If a new case
later produces a validated/approved reusable correction, it is explicitly
curated into that capability's `data/<capability>/anubhava.toml` and becomes
eligible only for future runs.

Bank repeated-analysis path after successful ingestion:

``` text
Raw statements → canonical consolidation → Parquet
                                      ↓
                              Viveka — Analyse
                                      ↓
                         reports / summaries / patterns

XLSX is generated only when human review/export is required.
```

This is the one canonical wiring path. Capabilities may depend on other capabilities through **Pravaha --- Dynamic Pipeline Engine**, but they do not directly instantiate each other or recreate shared infrastructure.

------------------------------------------------------------------------
### Domain Intelligence & Data Assets

Sarathi keeps reusable domain knowledge separate from runtime architecture.
Validated mappings, aliases, profiles, glossaries, and representative fixtures
are first-class V2 assets; their origin is irrelevant to runtime behavior.

``` text
Domain asset
    ↓
Validate
    ↓
Normalize into canonical V2 data/ownership
    ↓
Regression-test on representative inputs
    ↓
Activate
```

Examples include legacy-font mappings, bank synonyms/profiles, Decimal-safe
financial rules, OCR calibration data, and translation glossaries. Declarative
knowledge lives in the appropriate `data/` or `config/` source of truth;
algorithms remain Python. Adding or updating a data-driven profile does not require a README inventory update; the owning loader discovers validated profile data dynamically.

------------------------------------------------------------------------
## Testing Direction

Tests protect behavior, ownership, and financial correctness rather than architectural ceremony.

Architecture-conformance tests verify the three Design Principles at executable boundaries: core/domain separation, single-owner shared services, one active contract/execution path, and removal of superseded wiring. Behavioral safety tests separately verify that confidence is evidence-based, exceptions are explicit, provenance survives capability boundaries, and Kavacha outbound gates cannot be bypassed.

Input/artifact lifecycle tests verify that arbitrary and optional-inbox inputs
normalize into the same request; duplicates are removed; Output/Runtime roots
cannot be recursively re-ingested; source files remain unchanged; path escape
and unsafe overlap are rejected; plugins cannot hard-code/write final output
paths; collision handling and atomic commit use one boundary; multi-artifact
results retain lineage; manifests are written last from confirmed artifacts;
and success, partial, failure, cancellation, and cleanup preserve truthful
terminal state.

**Pravaha — Dynamic Pipeline Engine** quarantine tests are explicit acceptance coverage, not a genericized architecture check. They verify:

- hashed manifest identity and provenance remain tied to the failed input/request/trace;
- retry limits are enforced according to **Sutra — Configuration** policy;
- a successful approved retry releases the quarantined item correctly;
- exhausted or permanent failures remain in terminal quarantine state;
- manifests contain no sensitive document content, PII payloads, raw credentials, tokens, or secrets; and
- quarantine state remains separate from **Smriti — Cache & Runtime State** reusable-result caching.

Capability-local acceptance coverage is defined only in the
[Native Extraction Specification](Sarathi_V2_Native_Extraction_Spec.md),
[OCR Specification](Sarathi_V2_OCR_Spec.md),
[Font Conversion Specification](Sarathi_V2_Font_Conversion_Spec.md),
[Translation Specification](Sarathi_V2_Translation_Spec.md), and
[Bank Statement Consolidation Specification](Sarathi_V2_Bank_Statement_Spec.md).

Anubhava acceptance tests are capability-owned. They verify that absent files
leave baseline behavior unchanged; malformed or unapproved entries are
rejected; approved entries are revalidated before use; baseline conflicts are
explicit; runtime never auto-writes the TOML; and sensitive content is not
stored. Architecture tests also prohibit a generic Anubhava Python module,
plugin, service, database, loader, writer, or optimizer.

The golden/regression corpus must contain representative real formats and edge
cases. Hardware/runtime choices are benchmarked on the same representative
workload rather than assumed from device labels.

------------------------------------------------------------------------
## Dependency Ownership and Technical Direction

Core dependencies remain light. Heavy dependencies belong to the capability that actually requires them; plugin-specific OCR/AI packages do not become mandatory for unrelated functionality.

Exact versions live in `pyproject.toml` and `uv.lock`, not as a second mutable version table in this README.

Capability-local dependency direction lives only in the owning capability
specification linked under **Testing Direction**. **Anubhava — Validated
Experience Data** uses the standard-library `tomllib` read path and introduces
no runtime package.

Before a new dependency is locked, verify target Python/Windows compatibility, benchmark where performance matters, test representative real inputs, and then resolve/pin through uv. A package is added only when the current capability requires it and the dependency acceptance criteria are satisfied.

------------------------------------------------------------------------
## Architecture Status

**Status:** The canonical architecture and behavior baseline is locked by this specification. Detailed decisions live in their owning sections; this section intentionally does not restate them.

**V2 Modular Subpackage Architecture (Completed 06-09-2026):**
- Zero files exceeding 30 KB remain across the entire production codebase (`src/sarathi`).
- All 7 former monoliths decomposed into cohesive single-responsibility subpackages:
  - `sarathi.shakti.native_extraction.readers`
  - `sarathi.shakti.ocr.engine`
  - `sarathi.nabhi.artifacts`
  - `sarathi.shakti.docx_exporter`
  - `sarathi.agni`
  - `sarathi.nabhi.pravaha`
  - `sarathi.mukha.web`
- Declarative architectural governance enforced via `Vedas/architecture.manifest.json`, `import-linter` contracts, and AST-level fitness tests (`tests/architecture/`).
- 100% backward compatibility maintained via root package re-exports (`__all__`).

**Anubhava — Validated Experience Data** is locked as a capability-owned TOML convention. It has no Python module, runtime service, plugin, or database. A capability creates its file only after validated/approved reusable knowledge exists; autonomous learning and automatic promotion are not active paths.

**Deferred until demonstrated need:** database-backed transaction storage, partitioned Parquet, ML bank classification, automatic profile generation, OLAP dashboards, pipeline DSLs, and other speculative infrastructure.

Mutable inventories remain with their actual owners: exact dependency versions
in `pyproject.toml` / `uv.lock`, capability knowledge including approved
Anubhava overlays in `data/`, runtime policy in `config/`, and implementation
behavior in the Python files mapped under **Python File Responsibilities**.

The default physical lifecycle is `Input/` as an optional inbox,
`Runtime/Work/<run-id>/` for staging, and
`Output/<requirement>/Run-<timestamp>-<short-id>/` for confirmed user-facing
artifacts. Capability-local Input/Output roots and direct final writes are
prohibited.

When a locked decision changes, its owning section is edited in place and the superseded path is removed rather than documented beside its replacement.
