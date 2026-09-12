# Sarathi Architecture

## Purpose

Sarathi is a local-first document intelligence system. Its architecture separates composition, planning, execution, capabilities, security, caching, telemetry, configuration, errors, and presentation so that each concern has one canonical owner.

---

## Canonical Ownership

| Subsystem | Canonical Ownership | Primary Responsibility | Must Not Become |
| --- | --- | --- | --- |
| **Agni** | Composition & Lifecycle | Application bootstrap, subsystem wiring, and shutdown | A second planner or capability execution engine |
| **Sankalpa** | Contracts & Models | Shared request, result, artifact, and document data models | Business logic or capability orchestration |
| **Kosh** | Registry | Capability and plugin declarations and registry validation | An execution or planning authority |
| **Manthan** | Planning | Requirement resolution, dependency ordering, and execution planning | A worker pool or runtime executor |
| **Pravaha** | Execution | Plan execution, pipeline coordination, retry, and quarantine | A competing planner |
| **Shakti** | Capabilities | Document intelligence capabilities and provider adapters | Generic application orchestrator |
| **Kavacha** | Security | Authorization, path containment, and privacy/network checks | Credential vault or synthetic network proxy |
| **Smriti** | Cache | Optional deterministic result caching across runs | Source of truth for active pipeline execution |
| **Darpana** | Telemetry | Runtime metrics, quality observations, and execution history | A parallel application state model |
| **Sutra** | Configuration | Runtime TOML configuration loading and immutable settings | Policy enforcement or secret authority |
| **Mukha** | UI & API | Local ASGI web server, SSE events, presentation state, and UI | Planning authority or document processing engine |
| **Dosh** | Errors | Shared failure codes and exception hierarchy | Control-flow mechanism |

### Supporting Components

- **Yantra**: Generic execution and device resource helpers (CPU, GPU, NPU thread/device allocation). Capability-specific workload strategies remain within the owning Shakti capability.
- **Nabhi**: Physical runtime namespace package (`sarathi.nabhi`) hosting Kosh, Manthan, Pravaha, and artifact/quarantine utilities. It is not an additional architectural decision layer.

---

## Runtime Flow

```text
       CLI / Browser Request
                 |
                 v
               Mukha (UI / Local Web API)
                 |
                 v
               Agni (Composition & Lifecycle)
                 |
                 v
   Kosh (Registry) ---> Manthan (Planning)
                              |
                              v
                           Pravaha (Execution)
                              |
                              v
                           Shakti (Capabilities)
                              |
                              v
                      Committed Artifacts
```

Cross-cutting support during execution:
- **Kavacha** authorizes capability declarations before execution.
- **Yantra** allocates hardware device execution slots.
- **Smriti** looks up and populates cached capability results.
- **Darpana** collects runtime telemetry and quality observations.
- **Sankalpa** defines the shared request and document contracts.
- **Sutra** supplies immutable runtime configuration.
- **Dosh** classifies any execution failures.

---

## Architectural Invariants

- **Single Planning Authority**: Only Manthan creates execution plans.
- **Single Execution Authority**: Only Pravaha executes plans.
- **Single Registry Authority**: Only Kosh stores capability declarations.
- **Fail-Closed Security**: Kavacha validates path containment and authorizes capabilities before I/O or network operations.
- **Local-First Boundary**: Mukha binds strictly to loopback (`127.0.0.1`). Network access is permitted only when explicitly authorized in configuration.
---

## Confidence & Quality Telemetry Contract

Sarathi enforces strict integrity rules for confidence and quality observations:

- **Maruti vs. Pramana**:
  - **Maruti** records factual operational telemetry: monotonic execution durations, UTC timestamps, run/trace/span correlation, device allocation facts, and failure classification.
  - **Pramana** records evidence-backed quality observations: confidence metrics, region/page validation outcomes, and accuracy measurements when verified reference data exists. Confidence is never relabeled as accuracy.
- **Strict Evidence Requirement**: Every reported `ConfidenceValue` mandates a non-empty calculation `method` and a non-empty `evidence` map.
- **Canonical Scale**: Confidence scores are represented strictly on a ratio scale (`0.0 <= score <= 1.0`); percentage formatting is presentation-only.
- **No Fabricated Defaults**: If a capability cannot compute meaningful confidence, it reports confidence as unavailable (`None`) rather than fabricating arbitrary numbers or default success ratings.

---

## Canonical Code Directory & File Inventory

The production codebase is organized under `src/sarathi/`. Every module and component maps directly to canonical ownership:

### 1. Root Application Package (`src/sarathi/`)
- [`__init__.py`](file:///e:/Sarathi/src/sarathi/__init__.py): Root package initialization and package metadata.
- [`__main__.py`](file:///e:/Sarathi/src/sarathi/__main__.py): Application entry point for CLI and `python -m sarathi`.

### 2. Agni — Composition & Lifecycle (`src/sarathi/agni/`)
- [`bootstrap.py`](file:///e:/Sarathi/src/sarathi/agni/bootstrap.py): Coordinates subsystem initialization and wires the application container.
- [`dispatcher.py`](file:///e:/Sarathi/src/sarathi/agni/dispatcher.py): High-level entry point for executing pipeline runs from CLI or API.
- [`preflight.py`](file:///e:/Sarathi/src/sarathi/agni/preflight.py): Validates storage roots, environment prerequisites, and dependencies before startup.
- [`readiness.py`](file:///e:/Sarathi/src/sarathi/agni/readiness.py): Collects and aggregates readiness status across all registered plugins.
- [`wiring.py`](file:///e:/Sarathi/src/sarathi/agni/wiring.py): Dependency-injection wiring factory for application services.

### 3. Sankalpa — Contracts & Models (`src/sarathi/sankalpa/`)
- [`artifact.py`](file:///e:/Sarathi/src/sarathi/sankalpa/artifact.py): Artifact models (`ArtifactPayload`, `ArtifactIntent`, `ArtifactReference`).
- [`cancellation.py`](file:///e:/Sarathi/src/sarathi/sankalpa/cancellation.py): Cooperative thread-safe cancellation token abstraction.
- [`capability.py`](file:///e:/Sarathi/src/sarathi/sankalpa/capability.py): Capability interfaces, declarations, and execution binding models.
- [`context.py`](file:///e:/Sarathi/src/sarathi/sankalpa/context.py): `ExecutionContext` model tracking run, request, trace, and span IDs.
- [`document.py`](file:///e:/Sarathi/src/sarathi/sankalpa/document.py): Canonical document representations (`CanonicalDocument`, `PageData`, `TextSpan`, `TableData`).
- [`execution_profile.py`](file:///e:/Sarathi/src/sarathi/sankalpa/execution_profile.py): Execution profile enumeration (`INSTANT`, `ACCURATE`, `CUSTOM`).
- [`plugin.py`](file:///e:/Sarathi/src/sarathi/sankalpa/plugin.py): Plugin provider contracts and security declarations (`PluginProvider`, `SecurityDeclaration`).
- [`readiness.py`](file:///e:/Sarathi/src/sarathi/sankalpa/readiness.py): Capability readiness reporting structures and status codes (`CapabilityReadiness`).
- [`request.py`](file:///e:/Sarathi/src/sarathi/sankalpa/request.py): Ingestion request definitions (`Request`, `InputSpec`).
- [`result.py`](file:///e:/Sarathi/src/sarathi/sankalpa/result.py): Unified execution result container (`Result`, `WarningRecord`, `ProvenanceRecord`).

### 4. Dosh — Shared Errors (`src/sarathi/dosh/`)
- [`errors.py`](file:///e:/Sarathi/src/sarathi/dosh/errors.py): Unified exception hierarchy (`DoshError`) and failure classification codes (`FailureCode`).

### 5. Sutra — Configuration (`src/sarathi/sutra/`)
- [`loader.py`](file:///e:/Sarathi/src/sarathi/sutra/loader.py): Parses and validates TOML configuration files into typed objects.
- [`settings.py`](file:///e:/Sarathi/src/sarathi/sutra/settings.py): Immutable, typed configuration container (`Settings`) and canonical defaults.

### 6. Kavacha — Security & Boundaries (`src/sarathi/kavacha/`)
- [`policy.py`](file:///e:/Sarathi/src/sarathi/kavacha/policy.py): Security authorization policy rules (`SecurityPolicy`) and secret name allowlists.
- [`service.py`](file:///e:/Sarathi/src/sarathi/kavacha/service.py): Evaluates capability security declarations and validates filesystem path containment.

### 7. Smriti — Cache (`src/sarathi/smriti/`)
- [`key.py`](file:///e:/Sarathi/src/sarathi/smriti/key.py): Computes deterministic cryptographic cache keys from requests and document inputs.
- [`memory.py`](file:///e:/Sarathi/src/sarathi/smriti/memory.py): High-speed in-memory L1 cache with bounded LRU eviction.
- [`policy.py`](file:///e:/Sarathi/src/sarathi/smriti/policy.py): Cache invalidation and retention rules (`CachePolicy`).
- [`serialization.py`](file:///e:/Sarathi/src/sarathi/smriti/serialization.py): Lossless serialization and deserialization of cached results.
- [`store.py`](file:///e:/Sarathi/src/sarathi/smriti/store.py): Multi-tier cache coordinator managing L1 memory and optional L2 disk cache.

### 8. Darpana — Telemetry (`src/sarathi/darpana/`)
- [`history.py`](file:///e:/Sarathi/src/sarathi/darpana/history.py): Manages persistent storage of completed runs in JSONL or SQLite.
- [`maruti.py`](file:///e:/Sarathi/src/sarathi/darpana/maruti.py): Operational performance and execution span records (`MarutiRecord`).
- [`pramana.py`](file:///e:/Sarathi/src/sarathi/darpana/pramana.py): Quality observations, confidence ratings, and accuracy measurements (`PramanaRecord`).
- [`service.py`](file:///e:/Sarathi/src/sarathi/darpana/service.py): Telemetry capture service with timing scopes and span tracking (`Darpana`).

### 9. Yantra — Execution & Device Resources (`src/sarathi/yantra/`)
- [`devices.py`](file:///e:/Sarathi/src/sarathi/yantra/devices.py): Hardware device inventory and accelerator discovery (`DeviceInfo`).
- [`manager.py`](file:///e:/Sarathi/src/sarathi/yantra/manager.py): Device scheduler managing concurrency capacity across CPU, GPU, and NPU.
- [`resources.py`](file:///e:/Sarathi/src/sarathi/yantra/resources.py): Subtask execution coordination and bounded queue management.

### 10. Nabhi — Runtime Planning, Execution & Workspace (`src/sarathi/nabhi/`)
- [`kosh.py`](file:///e:/Sarathi/src/sarathi/nabhi/kosh.py): **Kosh** declaration registry storing plugin declarations, capabilities, and dependencies.
- [`manthan.py`](file:///e:/Sarathi/src/sarathi/nabhi/manthan.py): **Manthan** planning engine that maps requests and profiles to an ordered execution plan.
- [`quarantine.py`](file:///e:/Sarathi/src/sarathi/nabhi/quarantine.py): Isolates corrupt or failing inputs to prevent cascade pipeline failures.
- **`artifacts/`** (Staged Artifact Management):
  - [`atomic_io.py`](file:///e:/Sarathi/src/sarathi/nabhi/artifacts/atomic_io.py): Atomic write primitives using staging files and verified rename.
  - [`boundary.py`](file:///e:/Sarathi/src/sarathi/nabhi/artifacts/boundary.py): Filesystem containment validation preventing directory traversal.
  - [`finalization.py`](file:///e:/Sarathi/src/sarathi/nabhi/artifacts/finalization.py): Commits staged artifacts to final output paths on successful runs.
  - [`manifest.py`](file:///e:/Sarathi/src/sarathi/nabhi/artifacts/manifest.py): Run workspace manifest generation and record keeping.
  - [`paths.py`](file:///e:/Sarathi/src/sarathi/nabhi/artifacts/paths.py): Resolves canonical input, output, and staging file paths.
  - [`promotion.py`](file:///e:/Sarathi/src/sarathi/nabhi/artifacts/promotion.py): Streaming file promotion with on-the-fly SHA-256 calculation and rollback.
  - [`workspace.py`](file:///e:/Sarathi/src/sarathi/nabhi/artifacts/workspace.py): Manages isolated per-run scratch workspaces.
- **`pravaha/`** (Plan Execution Engine):
  - [`common.py`](file:///e:/Sarathi/src/sarathi/nabhi/pravaha/common.py): Shared execution types and state tracking.
  - [`engine.py`](file:///e:/Sarathi/src/sarathi/nabhi/pravaha/engine.py): Step-level execution dispatcher.
  - [`lifecycle.py`](file:///e:/Sarathi/src/sarathi/nabhi/pravaha/lifecycle.py): Step execution lifecycle, telemetry timing, and failure management.
  - [`pipeline.py`](file:///e:/Sarathi/src/sarathi/nabhi/pravaha/pipeline.py): End-to-end plan coordinator managing sequential execution, retries, and handoffs.

### 11. Shakti — Document Intelligence Capabilities (`src/sarathi/shakti/`)
- [`artifact_naming.py`](file:///e:/Sarathi/src/sarathi/shakti/artifact_naming.py): Canonical filename formatting for exported artifacts.
- [`providers.py`](file:///e:/Sarathi/src/sarathi/shakti/providers.py): Built-in plugin provider catalog (`BUILTIN_PLUGIN_PROVIDERS`).

#### Shakti Sub-packages:
- **`darshana/`** (Intake Identification):
  - [`capability.py`](file:///e:/Sarathi/src/sarathi/shakti/darshana/capability.py): Document intake inspection capability.
  - [`facts.py`](file:///e:/Sarathi/src/sarathi/shakti/darshana/facts.py): Extracted intake metadata and document classification facts.
  - [`identifier.py`](file:///e:/Sarathi/src/sarathi/shakti/darshana/identifier.py): File format magic byte sniffer and signature rules.
  - [`plugin.py`](file:///e:/Sarathi/src/sarathi/shakti/darshana/plugin.py), [`provider.py`](file:///e:/Sarathi/src/sarathi/shakti/darshana/provider.py): Plugin declaration and provider factory.
- **`native_extraction/`** (Direct Digital Extraction):
  - [`capability.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/capability.py): Native extraction capability and OCR escalation hand-off.
  - [`detector.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/detector.py): Byte-level format detector (PDF, DOCX, XLSX, XLS, HTML, text).
  - [`plugin.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/plugin.py), [`provider.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/provider.py): Plugin declaration and provider factory.
  - **`readers/`**:
    - [`common.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/readers/common.py): Common reader constants.
    - [`delimited.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/readers/delimited.py): Delimited text reader (CSV, TSV, semicolon, pipe) via Polars.
    - [`docx.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/readers/docx.py): OpenXML DOCX paragraph, table, and style parser.
    - [`html.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/readers/html.py): HTML table extractor.
    - [`pdf.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/readers/pdf.py): PyMuPDF vector text and layout parser.
    - [`spreadsheet.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/readers/spreadsheet.py): Spreadsheet readers for XLSX (calamine/openpyxl), legacy XLS (xlrd), and SpreadsheetML.
- **`ocr/`** (Optical Character Recognition):
  - [`capability.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/capability.py): Local OCR capability coordinator.
  - [`plugin.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/plugin.py), [`provider.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/provider.py): Plugin declaration and provider factory.
  - [`telemetry.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/telemetry.py): Emits Pramana quality and Maruti timing telemetry for OCR runs.
  - [`typography.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/typography.py): Line-height, heading inference, and point size estimation.
  - **`engine/`**:
    - [`coordinator.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/coordinator.py): Multi-page OCR orchestration.
    - [`factory.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/factory.py): Instantiates RapidOCR sessions with target devices.
    - [`openvino.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/openvino.py): OpenVINO device patching, model compilation caching, and telemetry opt-out.
    - [`parser.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/parser.py): Converts RapidOCR raw output into canonical `TextSpan` and `TableData`.
    - [`preprocessing.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/preprocessing.py): Image preprocessing (CLAHE, deskew, binarization).
    - [`rasterize.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/rasterize.py): High-fidelity PDF page rasterization.
    - [`readiness.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/readiness.py): Preflight validation of ONNX model checksums and dependencies.
    - [`tesseract.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/tesseract.py): Targeted Tesseract 5 fallback adapter for difficult spans.
- **`translation/`** (Neural Machine Translation):
  - [`capability.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/capability.py): Translation capability coordinator.
  - [`detector.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/detector.py): Dominant script and language detection.
  - [`engine.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/engine.py): CTranslate2 neural translation inference engine wrapper.
  - [`glossary.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/glossary.py): Enforces custom glossary mappings and term substitutions.
  - [`models.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/models.py): Translation data structures.
  - [`plugin.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/plugin.py), [`provider.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/provider.py): Plugin declaration and provider factory.
  - [`protector.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/protector.py): Masks non-translatable entities (numbers, dates, URLs, statutory IDs).
- **`font_conversion/`** (Legacy Indian Font Conversion):
  - [`akshara.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/akshara.py): Devanagari ligatures, half-letters, and matra placement logic.
  - [`capability.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/capability.py): Font conversion capability coordinator.
  - [`converter.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/converter.py): Legacy 8-bit glyph to Unicode conversion mapper.
  - [`detector.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/detector.py): Parses TrueType SFNT binary `name` tables to extract font families.
  - [`models.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/models.py): Font conversion candidates and decision models.
  - [`plugin.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/plugin.py), [`provider.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/provider.py): Plugin declaration and provider factory.
  - [`protector.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/protector.py): Protects Latin, numeric, and already-Unicode text segments.
  - [`telemetry.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/telemetry.py): Quality telemetry for converted font spans.
  - [`validator.py`](file:///e:/Sarathi/src/sarathi/shakti/font_conversion/validator.py): Validates Devanagari syntactic coherence in converted output.
- **`bank_statements/`** (Financial Document Processing):
  - [`capability.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/capability.py): Bank statement processing capability coordinator.
  - [`consolidator.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/consolidator.py): Stitches multi-page statement tables into unified transactions.
  - [`converter.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/converter.py): Currency, debit/credit value, and date format normalizer.
  - [`deduplicator.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/deduplicator.py): Identifies and removes repeated transactions across overlapping pages.
  - [`detector.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/detector.py): Identifies financial institution layouts from headers.
  - [`mapper.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/mapper.py): Maps tabular headers to canonical financial fields.
  - [`models.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/models.py): Transaction and financial statement dataclasses (`TransactionRecord`).
  - [`plugin.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/plugin.py), [`provider.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/provider.py): Plugin declaration and provider factory.
  - [`row_classifier.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/row_classifier.py): Classifies table rows (header, transaction, summary, noise).
  - [`table_locator.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/table_locator.py): Finds statement transaction tables within multi-page documents.
  - [`validator.py`](file:///e:/Sarathi/src/sarathi/shakti/bank_statements/validator.py): Reconciles running balances against debit and credit arithmetic.
- **`statutory/`** (Statutory & Legal Intelligence):
  - [`capability.py`](file:///e:/Sarathi/src/sarathi/shakti/statutory/capability.py): Statutory extraction capability coordinator.
  - [`checksums.py`](file:///e:/Sarathi/src/sarathi/shakti/statutory/checksums.py): Implements mathematical checksum algorithms (Luhn Mod-36, GSTIN, PAN, TAN, CIN, CNR, DIN, IRN).
  - [`detector.py`](file:///e:/Sarathi/src/sarathi/shakti/statutory/detector.py): Regex pattern detector for government identifiers.
  - [`extractor.py`](file:///e:/Sarathi/src/sarathi/shakti/statutory/extractor.py): Contextual entity extraction from text spans.
  - [`models.py`](file:///e:/Sarathi/src/sarathi/shakti/statutory/models.py): Statutory entity data structures (`StatutoryMetadata`).
  - [`plugin.py`](file:///e:/Sarathi/src/sarathi/shakti/statutory/plugin.py), [`provider.py`](file:///e:/Sarathi/src/sarathi/shakti/statutory/provider.py): Plugin declaration and provider factory.
- **`docx_exporter/`** (OpenXML Generation & Transformation):
  - [`builder.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/builder.py): WordprocessingML XML package assembler.
  - [`constants.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/constants.py): XML namespaces, typography constants, and default fonts.
  - [`font_size_normalizer.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/font_size_normalizer.py): Normalizes font sizes to half-points (`w:sz`).
  - [`scripts.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/scripts.py): Segments text runs by script (Devanagari vs Latin).
  - [`styles.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/styles.py): Resolves XML styles and font families.
  - [`transformer.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/transformer.py): In-place DOCX XML tree transformer preserving styles and tables.
- **`text/`** (Shared Neutral Text Helpers):
  - [`legacy_detection.py`](file:///e:/Sarathi/src/sarathi/shakti/text/legacy_detection.py): Statistical bigram signature detection for legacy fonts.
  - [`markdown.py`](file:///e:/Sarathi/src/sarathi/shakti/text/markdown.py): Markdown table parser for cloud OCR outputs.
  - [`span_protection.py`](file:///e:/Sarathi/src/sarathi/shakti/text/span_protection.py): Common text span mask and restoration utilities.
  - [`typography.py`](file:///e:/Sarathi/src/sarathi/shakti/text/typography.py): Neutral typography helpers (Nirmala UI / Times New Roman).
- **Cloud Adapters** (`azure/`, `gemini/`, `mistral/`, `bhashini/`):
  - Each contains `client.py` (REST client), `ocr.py` (OCR capability), `translation.py` (Translation capability), `plugin.py` (declaration), and `provider.py` (provider registration).

### 12. Mukha — Presentation & Local Web Transport (`src/sarathi/mukha/`)
- [`intake.py`](file:///e:/Sarathi/src/sarathi/mukha/intake.py): Ingests uploaded files and maps HTTP requests into pipeline inputs.
- [`presenter.py`](file:///e:/Sarathi/src/sarathi/mukha/presenter.py): Formats canonical execution results and artifacts for frontend presentation.
- [`state.py`](file:///e:/Sarathi/src/sarathi/mukha/state.py): In-memory application state tracker for active and completed runs.
- **`web/`** (ASGI Server & UI Delivery):
  - [`app.py`](file:///e:/Sarathi/src/sarathi/mukha/web/app.py): Starlette ASGI application, routes, middleware, and Server-Sent Events (`/api/events`).
  - [`comparison.py`](file:///e:/Sarathi/src/sarathi/mukha/web/comparison.py): Run artifact comparison endpoints.
  - [`diagnostics.py`](file:///e:/Sarathi/src/sarathi/mukha/web/diagnostics.py): System health, device inventory, and configuration diagnostics API.
  - [`native_picker.py`](file:///e:/Sarathi/src/sarathi/mukha/web/native_picker.py): Native operating system file picker integration.
  - [`planner.py`](file:///e:/Sarathi/src/sarathi/mukha/web/planner.py): Web UI plan request adapter bridging to Manthan.
  - [`preview.py`](file:///e:/Sarathi/src/sarathi/mukha/web/preview.py): Generates preview streams for generated artifacts.
  - [`runner.py`](file:///e:/Sarathi/src/sarathi/mukha/web/runner.py): `RunCoordinator` managing background pipeline task execution and event dispatch.
  - [`security.py`](file:///e:/Sarathi/src/sarathi/mukha/web/security.py): Enforces loopback binding, Host/Origin validation, and security response headers.
  - [`server.py`](file:///e:/Sarathi/src/sarathi/mukha/web/server.py): `MukhaWebServer` lifecycle facade managing Uvicorn startup, shutdown, and port resolution.
  - [`state_builder.py`](file:///e:/Sarathi/src/sarathi/mukha/web/state_builder.py): Real-time application state projection builder.
  - **`assets/`**: Static SVG graphics and icons ([`icons.svg`](file:///e:/Sarathi/src/sarathi/mukha/web/assets/icons.svg)).
  - **`ui/`**: Production compiled single-page application ([`index.html`](file:///e:/Sarathi/src/sarathi/mukha/web/ui/index.html), [`app.js`](file:///e:/Sarathi/src/sarathi/mukha/web/ui/app.js), [`app.css`](file:///e:/Sarathi/src/sarathi/mukha/web/ui/app.css)).
