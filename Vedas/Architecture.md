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

## Primary Hardware Specification & Optimization Target

Sarathi's authoritative reference hardware deployment profile is pinned below.
**Rule (Primary Hardware First):** All system, threading, concurrency, accelerator, and pipeline optimizations MUST be engineered, tuned, and validated for this primary Sarathi Hardware profile first before considering generic fallback hardware.

| Component | Specification | Deployment Role & Optimization Invariants |
| :--- | :--- | :--- |
| **System** | HP Laptop 15-fd1xxx (Windows 11 x64) | Reference production host. |
| **CPU** | Intel(R) Core(TM) Ultra 5 125H (14 Cores: 4P + 8E + 2LPE, 18 Logical Processors) | **Primary Translation & Logic Host**: Tuned for multi-core x86 AVX2/AVX-VNNI neural acceleration. Compute-intensive inference must never artificially choke on single-core serialization when multi-core throughput is available. |
| **GPU** | Intel(R) Graphics (Meteor Lake iGPU, 7 Xe Cores, Driver 32.0.101.8508) | **Primary RapidOCR Accelerator**: Dedicated to OpenVINO FP16/INT8 OCR inference with persistent shader cache (`Runtime/Cache/openvino_model_cache`). Not for CUDA. |
| **NPU** | Intel(R) AI Boost (Meteor Lake NPU) | **OpenVINO NPU Engine**: Probed and managed via `yantra.devices` for static workloads. |
| **Memory** | 24 GB Physical RAM | Ample memory for concurrent in-memory OCR models and CTranslate2 neural weights without swapping. |
| **CUDA** | None (0 physical devices) | Translation and OCR pipelines must never depend on or expect NVIDIA CUDA on primary hardware. |

### Optimization Priority Invariants:
1. **Primary Hardware First**: Maximize throughput across the 14-core Core Ultra 5 125H CPU and Intel Arc iGPU (OpenVINO).
2. **Generic Hardware Second**: Provide clean fallbacks (e.g. CUDA on external GPU, pure CPU without iGPU) without degrading primary hardware execution.

---

## Architectural Invariants

- **Single Planning Authority**: Only Manthan creates execution plans.
- **Single Execution Authority**: Only Pravaha executes plans.
- **Single Registry Authority**: Only Kosh stores capability declarations.
- **Fail-Closed Security**: Kavacha validates path containment and authorizes capabilities before I/O or network operations.
- **Local-First Boundary**: Mukha binds strictly to loopback (`127.0.0.1`). Network access is permitted only when explicitly authorized in configuration.
- **Overengineering & ROI Discipline**: New dependencies and major architectural changes require demonstrated ROI (measurable gains in correctness, speed, security, or maintainability vs. footprint/learning costs) and evaluation against simpler built-in alternatives. Speculative abstraction layers and redundant wrappers are rejected.

---

## Confidence & Quality Telemetry Contract

Sarathi enforces strict integrity rules for confidence and quality observations:

- **Maruti vs. Pramana**:
  - **Maruti** records factual operational telemetry: monotonic execution durations, UTC timestamps, run/trace/span correlation, device allocation facts, and failure classification.
  - **Pramana** records evidence-backed quality observations: confidence metrics, region/page validation outcomes, and accuracy measurements when verified reference data exists. Confidence is never relabeled as accuracy.
- **Strict Evidence Requirement**: Every reported `ConfidenceValue` mandates a non-empty calculation `method` and a non-empty `evidence` map.
- **Canonical Scale**: Confidence scores are represented strictly on a ratio scale (`0.0 <= score <= 1.0`); percentage formatting is presentation-only.
---

## Canonical Project Structure

```text
sarathi/
├── pyproject.toml                     # Project packaging, build metadata, dependencies, and capability extras
├── uv.lock                            # Deterministic pinned lockfile for all runtime and development packages
├── arambha.bat                        # Windows one-click local launcher (runs uv run python -m sarathi)
├── README.md                          # Repository overview, capabilities, quickstart, and engineering summary
├── AGENTS.md                          # Canonical rules of engagement, modularity, and ROI discipline for AI agents
├── .gitignore                         # Git exclusion rules (virtual environments, test artifacts, model weights)
├── .antigravityignore                 # Antigravity agent indexing exclusion rules (scratch, models, node_modules)
├── .python-version                    # Pinned Python version specification (3.13)
├── src/                               # Production source tree
│   └── sarathi/                       # Root application package
│       ├── __init__.py                # Package initialization and version declaration
│       ├── __main__.py                # CLI entry point and process lifecycle dispatcher
│       ├── agni/                      # Composition root & process lifecycle subsystem
│       │   ├── __init__.py            # Agni module namespace
│       │   ├── bootstrap.py           # Subsystem wiring and runtime bootstrapping orchestrator
│       │   ├── dispatcher.py          # Unified CLI and daemon lifecycle command runner
│       │   ├── preflight.py           # Startup verification of environment, paths, and platform readiness
│       │   ├── readiness.py           # Subsystem health aggregator and dependency status checks
│       │   └── wiring.py              # Inversion-of-control dependency container and service wiring
│       ├── sankalpa/                  # Shared data contracts & document models subsystem
│       │   ├── __init__.py            # Sankalpa module namespace
│       │   ├── artifact.py            # Generated file artifact metadata and staging descriptors
│       │   ├── cancellation.py        # Cooperative cancellation tokens and state primitives
│       │   ├── capability.py          # Capability interface, execution contracts, and failure handling
│       │   ├── context.py             # Pipeline ExecutionContext carrying services, telemetry, and cancellation
│       │   ├── document.py            # CanonicalDocument, PageData, TextSpan, and TableData domain models
│       │   ├── execution_profile.py   # Standard execution profiles (Instant, Accurate, Layout-Preserving, Custom)
│       │   ├── plugin.py              # Plugin declaration, requirements, and manifest structures
│       │   ├── readiness.py           # Capability and plugin readiness status contracts
│       │   ├── request.py             # User processing request contracts, requirements, and profile mapping
│       │   └── result.py              # Execution result payloads, provenance history, and warning records
│       ├── dosh/                      # Shared error vocabulary subsystem
│       │   ├── __init__.py            # Dosh module namespace
│       │   └── errors.py              # Standardized failure codes (FailureCode) and DoshError exception type
│       ├── sutra/                     # Runtime settings subsystem
│       │   ├── __init__.py            # Sutra module namespace
│       │   ├── loader.py              # TOML settings file discovery, parsing, and env overrides
│       │   └── settings.py            # Immutable, validated Settings dataclass and typed section accessors
│       ├── kavacha/                   # Security authorization subsystem
│       │   ├── __init__.py            # Kavacha module namespace
│       │   ├── policy.py              # SecurityPolicy declaring allowed networks, secrets, and PII permissions
│       │   └── service.py             # Kavacha security validator enforcing boundaries at capability invocation
│       ├── smriti/                    # Deterministic result caching subsystem
│       │   ├── __init__.py            # Smriti module namespace
│       │   ├── key.py                 # Cryptographic cache key computation (inputs, options, profiles, hashes)
│       │   ├── memory.py              # In-memory L1 cache implementation with LRU eviction
│       │   ├── policy.py              # CachePolicy specifying TTL, maximum entries, and persistence thresholds
│       │   ├── serialization.py       # Deterministic payload serializer/deserializer for cached results
│       │   └── store.py               # Two-tier cache facade coordinating L1 memory and L2 persistent store
│       ├── darpana/                   # Telemetry & quality observation subsystem
│       │   ├── __init__.py            # Darpana module namespace
│       │   ├── history.py             # Persistent storage backend for historical run records (JSONL / SQLite)
│       │   ├── maruti.py              # Operational performance telemetry records (MarutiRecord: timing, spans)
│       │   ├── pramana.py             # Evidence-backed quality observations (PramanaRecord: confidence, metrics)
│       │   └── service.py             # Telemetry service managing live recording scopes, spans, and subscribers
│       ├── yantra/                    # Execution & device resource subsystem
│       │   ├── __init__.py            # Yantra module namespace
│       │   ├── devices.py             # Hardware discovery probing CPU cores, OpenVINO GPUs, and NPUs
│       │   ├── manager.py             # Device capacity scheduler allocating concurrency slots per hardware unit
│       │   └── resources.py           # Subtask queue coordination and concurrency rate-limiting
│       ├── nabhi/                     # Planning, execution & workspace subsystem
│       │   ├── __init__.py            # Nabhi module namespace
│       │   ├── kosh.py                # Capability declaration registry storing plugins, adapters, and readiness
│       │   ├── manthan.py             # Dynamic pipeline planner resolving execution stages from request profile
│       │   ├── quarantine.py          # Input defect isolation preventing cascading pipeline crash loops
│       │   ├── artifacts/             # Staged file promotion & filesystem boundary utilities
│       │   │   ├── __init__.py        # Artifacts utility namespace
│       │   │   ├── atomic_io.py       # Atomic file write primitives using temporary staging and verified rename
│       │   │   ├── boundary.py        # Path containment validation preventing directory traversal attacks
│       │   │   ├── finalization.py    # Commit staged artifacts into final output directories on success
│       │   │   ├── manifest.py        # Run manifest generation tracking committed and quarantined artifacts
│       │   │   ├── paths.py           # Canonical path resolution for input, output, and staging directories
│       │   │   ├── promotion.py       # Streaming file promotion with on-the-fly SHA-256 calculation
│       │   │   └── workspace.py       # Per-run isolated scratch workspace lifecycle manager
│       │   └── pravaha/               # Plan execution engine
│       │       ├── __init__.py        # Pravaha module namespace
│       │       ├── common.py          # Execution state tracking and stage transition primitives
│       │       ├── engine.py          # Step-level capability dispatcher and execution worker
│       │       ├── lifecycle.py       # Stage execution timing, telemetry dispatch, and retry isolation
│       │       └── pipeline.py        # End-to-end plan coordinator managing stages, continuations, and handoffs
│       ├── shakti/                    # Document intelligence capabilities subsystem
│       │   ├── __init__.py            # Shakti module namespace
│       │   ├── artifact_naming.py     # Canonical artifact filename generation based on input, stage, and profile
│       │   ├── providers.py           # Built-in plugin provider catalog registration
│       │   ├── text/                  # Neutral text processing and typography helpers
│       │   │   ├── __init__.py        # Text utility namespace
│       │   │   ├── direction.py       # Bidirectional and text direction layout inspection
│       │   │   ├── legacy_detection.py# Statistical bigram signature analyzer for legacy Indic fonts
│       │   │   ├── markdown.py        # Structured markdown table parser for cloud extraction outputs
│       │   │   ├── span_protection.py # Non-translatable text span masking and restoration helpers
│       │   │   ├── transliteration.py # Phonetic Romanized Indic (Hinglish) to Devanagari rule transducer
│       │   │   └── typography.py      # Standardized script typography profiles (Nirmala UI / Times New Roman)
│       │   ├── darshana/              # Intake inspection & format identification capability
│       │   │   ├── __init__.py        # Darshana module namespace
│       │   │   ├── capability.py      # File format identification capability implementation
│       │   │   ├── facts.py           # Extracted intake metadata and document classification facts
│       │   │   ├── identifier.py      # Magic byte header sniffer and format classification rules
│       │   │   ├── plugin.py          # Plugin declaration and capability requirements
│       │   │   └── provider.py        # Provider factory for Darshana registration
│       │   ├── native_extraction/     # Digital document extraction capability
│       │   │   ├── __init__.py        # Native extraction module namespace
│       │   │   ├── capability.py      # Native digital extraction capability and OCR escalation handoff
│       │   │   ├── detector.py        # Fast format sniffer routing files to specialized native readers
│       │   │   ├── plugin.py          # Plugin declaration and capability requirements
│       │   │   ├── provider.py        # Provider factory for native extraction registration
│       │   │   └── readers/           # Format-specific document parsers
│       │   │       ├── __init__.py    # Readers namespace
│       │   │       ├── common.py      # Shared reader constants and extraction helpers
│       │   │       ├── delimited.py   # Delimited tabular text parser (CSV, TSV, semicolon, pipe) via Polars
│       │   │       ├── docx.py        # OpenXML WordprocessingML parser for paragraphs, styles, and tables
│       │   │       ├── html.py        # HTML table extractor parsing table tags into tabular data
│       │   │       ├── pdf.py         # PyMuPDF vector text parser extracting characters, spans, and rects
│       │   │       ├── pdf_layout.py  # GNN-based deep layout parser and reading order recovery (pymupdf-layout)
│       │   │       └── spreadsheet.py # Multi-sheet Excel parser for XLSX, XLSM, legacy XLS (BIFF8), and XML-2003
│       │   ├── ocr/                   # Local optical character recognition capability
│       │   │   ├── __init__.py        # OCR module namespace
│       │   │   ├── capability.py      # Local OCR capability coordinator orchestrating page recognition
│       │   │   ├── plugin.py          # Plugin declaration and capability requirements
│       │   │   ├── provider.py        # Provider factory for local OCR registration
│       │   │   ├── telemetry.py       # Emits Pramana quality and Maruti timing telemetry for OCR runs
│       │   │   ├── typography.py      # Bounding box line-height, heading inference, and font size estimation
│       │   │   └── engine/            # RapidOCR neural recognition engine (OpenVINO accelerated)
│       │   │       ├── __init__.py    # OCR engine namespace
│       │   │       ├── common.py      # Shared OCR engine data structures and bounding box primitives
│       │   │       ├── coordinator.py # Multi-page document OCR orchestration and page worker dispatch
│       │   │       ├── factory.py     # Instantiates RapidOCR inference sessions bound to target devices
│       │   │       ├── layout.py      # Spatial reading order reconstruction and Recursive XY-Cut partitioning
│       │   │       ├── openvino.py    # OpenVINO device patching, model compilation cache, and telemetry opt-out
│       │   │       ├── parser.py      # Converts raw OCR boxes and text into TextSpan and TableData structures
│       │   │       ├── preprocessing.py# Adaptive image enhancement (CLAHE, deskew, binarization)
│       │   │       ├── rasterize.py   # High-resolution PDF page rendering to raster images
│       │   │       └── readiness.py   # Validates existence and SHA-256 checksums of local ONNX models
│       │   ├── translation/           # Neural machine translation capability
│       │   │   ├── __init__.py        # Translation module namespace
│       │   │   ├── capability.py      # Neural translation capability coordinator preserving formatting
│       │   │   ├── detector.py        # Source language and regional Indic script detection
│       │   │   ├── engine.py          # CTranslate2 neural translation inference engine wrapper
│       │   │   ├── glossary.py        # Custom glossary enforcement and terminology substitution
│       │   │   ├── models.py          # Translation request models and language pair definitions
│       │   │   ├── plugin.py          # Plugin declaration and capability requirements
│       │   │   ├── protector.py       # Masks non-translatable entities (dates, numbers, URLs, statutory IDs)
│       │   │   └── provider.py        # Provider factory for neural translation registration
│       │   ├── font_conversion/       # Legacy Indian font conversion capability
│       │   │   ├── __init__.py        # Font conversion module namespace
│       │   │   ├── akshara.py         # Devanagari ligature, half-letter, and matra reordering rules
│       │   │   ├── capability.py      # Legacy font conversion capability coordinator
│       │   │   ├── converter.py       # Bidirectional glyph mapping engine (legacy 8-bit <-> Unicode Devanagari)
│       │   │   ├── detector.py        # Identifies legacy fonts via TrueType SFNT tables or text signatures
│       │   │   ├── models.py          # Font conversion candidate representations and conversion metrics
│       │   │   ├── plugin.py          # Plugin declaration and capability requirements
│       │   │   ├── protector.py       # Protects Latin, numeric, and valid Unicode spans from modification
│       │   │   ├── provider.py        # Provider factory for font conversion registration
│       │   │   ├── telemetry.py       # Emits Pramana quality telemetry for converted font spans
│       │   │   └── validator.py       # Syntactic validation ensuring output conforms to valid Devanagari rules
│       │   ├── bank_statements/       # Financial statement processing capability
│       │   │   ├── __init__.py        # Bank statement module namespace
│       │   │   ├── capability.py      # Bank statement parsing and transaction normalization coordinator
│       │   │   ├── consolidator.py    # Multi-page table consolidator stitching contiguous transactions
│       │   │   ├── converter.py       # Currency, numeric value, and date format normalizer
│       │   │   ├── deduplicator.py    # Identifies and eliminates duplicate transactions across page overlaps
│       │   │   ├── detector.py        # Identifies financial institution layout from document headers
│       │   │   ├── mapper.py          # Maps institutional column headers to canonical transaction fields
│       │   │   ├── models.py          # Financial statement and TransactionRecord data models
│       │   │   ├── plugin.py          # Plugin declaration and capability requirements
│       │   │   ├── provider.py        # Provider factory for bank statement processing registration
│       │   │   ├── row_classifier.py  # Categorizes extracted rows (transaction, continuation, header, balance)
│       │   │   ├── table_locator.py   # Discovers transaction tables within multi-page documents
│       │   │   └── validator.py       # Reconciles running balances against debit and credit arithmetic
│       │   ├── statutory/             # Statutory & legal identifier extraction capability
│       │   │   ├── __init__.py        # Statutory module namespace
│       │   │   ├── capability.py      # Statutory identifier extraction capability coordinator
│       │   │   ├── checksums.py       # Algorithmic checksum validators (Luhn Mod-36, GSTIN, PAN, TAN, CIN, CNR)
│       │   │   ├── detector.py        # Regular expression pattern recognizer for government identifiers
│       │   │   ├── extractor.py       # Contextual entity extraction from text spans and tables
│       │   │   ├── models.py          # Statutory metadata data structures and validation flag models
│       │   │   ├── plugin.py          # Plugin declaration and capability requirements
│       │   │   └── provider.py        # Provider factory for statutory extraction registration
│       │   ├── docx_exporter/         # OpenXML DOCX assembly & transformation capability
│       │   │   ├── __init__.py        # DOCX exporter module namespace
│       │   │   ├── builder.py         # WordprocessingML XML package assembler generating output documents
│       │   │   ├── constants.py       # OpenXML namespaces, typography standards, and default dimensions
│       │   │   ├── font_size_normalizer.py # Normalizes font sizes to half-points (w:sz)
│       │   │   ├── scripts.py         # Segments text runs by script (Devanagari vs Latin) for typography styling
│       │   │   ├── styles.py          # Resolves paragraph styles, heading hierarchies, and font families
│       │   │   └── transformer.py     # In-place DOCX XML tree transformer preserving styles and tables
│       │   ├── mistral/               # Mistral AI cloud adapter
│       │   │   ├── __init__.py        # Mistral module namespace
│       │   │   ├── client.py          # HTTP client communicating with Mistral REST API endpoints
│       │   │   ├── ocr.py             # Mistral OCR capability implementation
│       │   │   ├── plugin.py          # Plugin declaration and requirements
│       │   │   ├── provider.py        # Provider factory for Mistral adapter registration
│       │   │   └── translation.py     # Mistral translation capability implementation
│       │   ├── gemini/                # Google Gemini cloud adapter
│       │   │   ├── __init__.py        # Gemini module namespace
│       │   │   ├── client.py          # HTTP client communicating with Gemini REST API endpoints
│       │   │   ├── ocr.py             # Gemini OCR capability implementation
│       │   │   ├── plugin.py          # Plugin declaration and requirements
│       │   │   ├── provider.py        # Provider factory for Gemini adapter registration
│       │   │   └── translation.py     # Gemini translation capability implementation
│       │   ├── azure/                 # Microsoft Azure cloud adapter
│       │   │   ├── __init__.py        # Azure module namespace
│       │   │   ├── client.py          # HTTP client communicating with Azure Document Intelligence & Translator
│       │   │   ├── ocr.py             # Azure Document Intelligence OCR capability implementation
│       │   │   ├── plugin.py          # Plugin declaration and requirements
│       │   │   ├── provider.py        # Provider factory for Azure adapter registration
│       │   │   └── translation.py     # Azure Translator capability implementation
│       │   └── bhashini/              # Bhashini Indian Government AI cloud adapter
│       │       ├── __init__.py        # Bhashini module namespace
│       │       ├── client.py          # HTTP client communicating with Bhashini Dhruva inference pipelines
│       │       ├── ocr.py             # Bhashini Chitrakshar OCR capability implementation
│       │       ├── plugin.py          # Plugin declaration and requirements
│       │       ├── provider.py        # Provider factory for Bhashini adapter registration
│       │       └── translation.py     # Bhashini NMT translation capability implementation
│       └── mukha/                     # Presentation, local web transport & UI subsystem
│           ├── __init__.py            # Mukha module namespace
│           ├── intake.py              # Ingests uploaded files and maps HTTP requests into pipeline inputs
│           ├── presenter.py           # Formats canonical execution results and artifacts for frontend presentation
│           ├── state.py               # In-memory application state tracker for active and historical runs
│           └── web/                   # ASGI web server & API delivery
│               ├── __init__.py        # Web transport namespace
│               ├── app.py             # Starlette ASGI application, routes, middleware, and SSE endpoint
│               ├── comparison.py      # Run artifact comparison endpoints
│               ├── diagnostics.py     # System health, device inventory, and configuration diagnostics API
│               ├── native_picker.py   # Controlled native operating system file/folder picker integration
│               ├── planner.py         # Web UI plan request adapter bridging to Manthan planner
│               ├── preview.py         # Renders file preview streams for ingested and generated documents
│               ├── runner.py          # RunCoordinator managing background pipeline execution and SSE dispatch
│               ├── security.py        # Enforces loopback binding, Host/Origin validation, and security headers
│               ├── server.py          # MukhaWebServer lifecycle facade managing Uvicorn startup and shutdown
│               ├── state_builder.py   # Real-time application state projection builder for frontend clients
│               ├── assets/            # Embedded static graphic assets
│               │   ├── __init__.py    # Assets package namespace
│               │   └── icons.svg      # Unified SVG icon sprite sheet for the web interface
│               └── ui/                # Production compiled single-page application
│                   ├── index.html     # SPA HTML entry point
│                   ├── app.js         # Compiled Preact/TypeScript application bundle
│                   └── app.css        # Bundled application styles
├── ui/                                # Frontend source tree (TypeScript / Preact / Vite)
│   ├── package.json                   # Frontend npm package manifest and build scripts
│   ├── package-lock.json              # Pinned npm dependency lockfile
│   ├── tsconfig.json                  # TypeScript compiler options and JSX configuration
│   ├── vite.config.ts                 # Vite bundler configuration, loopback dev proxy, and output targets
│   ├── index.html                     # Vite development HTML template
│   └── src/                           # Frontend application source code
│       ├── App.tsx                    # Root UI component structuring the 5 dedicated screens
│       ├── api.ts                     # Typed REST API client and SSE event listener
│       ├── types.ts                   # TypeScript interfaces mirroring backend Sankalpa contracts
│       ├── main.tsx                   # Preact application DOM mount entry point
│       ├── styles.css                 # Application design tokens, theme styles, and cockpit layout
│       └── vite-env.d.ts              # Vite environment type declarations
├── data/                              # Static domain assets & templates
│   ├── banks/                         # Bank statement format definitions
│   │   ├── common.yaml                # Universal Indian bank header heuristic layout definition
│   │   ├── hdfc.yaml                  # HDFC Bank statement column and layout definition
│   │   ├── icici.yaml                 # ICICI Bank statement column and layout definition
│   │   └── sbi.yaml                   # State Bank of India statement column and layout definition
│   ├── fonts/                         # Legacy Indic font mapping tables
│   │   ├── chanakya010.json           # Chanakya 010 to Unicode Devanagari character mapping table
│   │   ├── devlys010.json             # DevLys 010 to Unicode Devanagari character mapping table
│   │   ├── krutidev010.json           # Kruti Dev 010 to Unicode Devanagari character mapping table
│   │   ├── shivaji010.json            # Shivaji 010 to Unicode Devanagari character mapping table
│   │   └── shusha010.json             # Shusha 010 to Unicode Devanagari character mapping table
│   ├── ocr/                           # OCR model manifests & storage
│   │   ├── manifest.json              # Checksum-verified catalog of declared RapidOCR models (det, cls, rec_devanagari, rec_v6_en)
│   │   └── models/                    # Downloaded/exported ONNX model weights and vocabulary files
│   └── translation/                   # Translation model manifests & glossaries
│       ├── manifest.json              # Catalog of declared CTranslate2 neural translation models
│       └── glossaries/                # Domain-specific terminology and phrase substitution dictionaries
├── config/                            # Runtime configuration
│   └── settings.toml                  # Default TOML configuration file (storage, security, cache, hardware)
├── tools/                             # Developer & engineering tooling
│   ├── scripts/                       # Operational PowerShell automation scripts
│   │   ├── Setup-OCRModels.ps1        # Automated model downloader, provisioner, and SHA-256 verifier (CI)
│   │   ├── update_sarathi.cmd         # Windows Command prompt launcher for update_sarathi.ps1
│   │   └── update_sarathi.ps1         # Interactive environment and dependency manager (uv bootstrap, sync)
│   └── benchmark_ocr_and_font.py      # Performance and accuracy measurement harness
├── tests/                             # Automated test suite
│   ├── architecture/                  # Subsystem boundary, manifest sync, and hygiene tests
│   ├── agni/                          # Composition root, bootstrap, and lifecycle tests
│   ├── bank_statements/               # Financial statement parsing, reconciliation, and validation tests
│   ├── cancellation/                  # Cooperative pipeline cancellation tests
│   ├── configuration/                 # Sutra settings loading and validation tests
│   ├── contracts/                     # Sankalpa request, result, and document contract tests
│   ├── dosh/                          # Error code and failure taxonomy tests
│   ├── font_conversion/               # Legacy font detection, conversion, and validation tests
│   ├── integration/                   # Multi-component end-to-end pipeline integration tests
│   ├── mukha/                         # Web transport, API routes, and presentation state tests
│   ├── nabhi/                         # Planning, execution, and artifact workspace tests
│   ├── native_extraction/             # Digital document reader and format detector tests
│   ├── ocr/                           # Optical character recognition and engine tests
│   ├── security/                      # Kavacha security policy and boundary enforcement tests
│   ├── shakti/                        # Capability provider and plugin isolation tests
│   ├── smriti/                        # Result caching, key computation, and serialization tests
│   ├── statutory/                     # Statutory extraction and checksum validation tests
│   ├── telemetry/                     # Darpana operational timing and quality observation tests
│   ├── translation/                   # Neural translation, language detection, and glossary tests
│   └── yantra/                        # Hardware discovery and device scheduler tests
├── Input/                             # Default root directory for incoming documents
├── Output/                            # Default root directory for committed output artifacts
├── Runtime/                           # Temporary workspaces and runtime state
│   ├── Cache/                         # OpenVINO compiled model cache and L2 result cache
│   ├── Quarantine/                    # Isolated corrupt or failing documents
│   └── Telemetry/                     # Persisted operational timing and quality event logs
└── Vedas/                             # Engineering documentation & architecture specifications
    ├── architecture.manifest.json     # Machine-readable production package and component topology
    ├── architecture.manifest.schema.json # JSON schema defining production manifest rules
    ├── README.md                      # Engineering guide documentation index
    ├── Architecture.md                # Canonical subsystem ownership, runtime flow, and topology
    ├── Capabilities.md                # Capability specifications, fallbacks, and execution profiles
    ├── Configuration.md               # Typed Sutra configuration keys, defaults, and cloud settings
    ├── Decisions.md                   # Canonical UI/UX progressive Home task hierarchy and technical mapping
    ├── Development.md                 # Environment setup, developer workflows, and CI gate commands
    ├── Formats.md                     # Supported document, spreadsheet, delimited, and font formats
    ├── Mukha_Transport.md             # Local ASGI web transport, SSE streaming, and security boundary
    └── Troubleshooting.md             # Diagnoses and actionable fixes for operational issues
```
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
    - [`pdf_layout.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/readers/pdf_layout.py): GNN-based deep layout analysis and reading order recovery leveraging PyMuPDF-layout.
    - [`spreadsheet.py`](file:///e:/Sarathi/src/sarathi/shakti/native_extraction/readers/spreadsheet.py): Spreadsheet readers for XLSX (calamine/openpyxl), legacy XLS (calamine/xlrd), and SpreadsheetML.
- **`ocr/`** (Optical Character Recognition):
  - [`capability.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/capability.py): Local OCR capability coordinator.
  - [`plugin.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/plugin.py), [`provider.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/provider.py): Plugin declaration and provider factory.
  - [`telemetry.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/telemetry.py): Emits Pramana quality and Maruti timing telemetry for OCR runs.
  - [`typography.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/typography.py): Line-height, heading inference, and point size estimation.
  - **`engine/`**:
    - [`coordinator.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/coordinator.py): Multi-page OCR orchestration.
    - [`factory.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/factory.py): Instantiates RapidOCR sessions with target devices.
    - [`layout.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/layout.py): Spatial reading order reconstruction and Recursive XY-Cut partitioning.
    - [`openvino.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/openvino.py): OpenVINO device patching, model compilation caching, and telemetry opt-out.
    - [`parser.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/parser.py): Converts RapidOCR raw output into canonical `TextSpan` and `TableData`.
    - [`preprocessing.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/preprocessing.py): Image preprocessing (CLAHE, deskew, binarization).
    - [`rasterize.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/rasterize.py): High-fidelity PDF page rasterization.
    - [`readiness.py`](file:///e:/Sarathi/src/sarathi/shakti/ocr/engine/readiness.py): Preflight validation of ONNX model checksums and dependencies.
- **`translation/`** (Neural Machine Translation):
  - [`capability.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/capability.py): Translation capability coordinator with upfront whole-document string pre-collection and batch translation.
  - [`detector.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/detector.py): Dominant script and language detection.
  - [`engine.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/engine.py): CTranslate2 neural translation inference engine wrapper with dual SentencePiece tokenizers, IndicTrans2 + OPUS-MT support, and `translate_batch()` multi-core CPU decoder.
  - [`glossary.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/glossary.py): Enforces custom glossary mappings and term substitutions.
  - [`models.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/models.py): Translation data structures.
  - [`plugin.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/plugin.py), [`provider.py`](file:///e:/Sarathi/src/sarathi/shakti/translation/provider.py): Plugin declaration and provider factory with multi-model readiness audit.
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
  - [`builder.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/builder.py): WordprocessingML XML package assembler with proportional table column widths (`<w:tblGrid>`), cell margins (`<w:tblCellMar>`), cantSplit row pagination, in-flow anchors, and row deduplication.
  - [`constants.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/constants.py): XML namespaces, typography constants, and default fonts.
  - [`font_size_normalizer.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/font_size_normalizer.py): Normalizes font sizes to half-points (`w:sz`).
  - [`scripts.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/scripts.py): Segments text runs by script (Devanagari vs Latin).
  - [`styles.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/styles.py): Resolves XML styles and font families.
  - [`transformer.py`](file:///e:/Sarathi/src/sarathi/shakti/docx_exporter/transformer.py): In-place DOCX XML tree transformer preserving styles and tables.
- **`text/`** (Shared Neutral Text Helpers):
  - [`direction.py`](file:///e:/Sarathi/src/sarathi/shakti/text/direction.py): Bidirectional and text direction layout inspection.
  - [`legacy_detection.py`](file:///e:/Sarathi/src/sarathi/shakti/text/legacy_detection.py): Statistical bigram signature detection for legacy fonts.
  - [`markdown.py`](file:///e:/Sarathi/src/sarathi/shakti/text/markdown.py): Markdown table parser for cloud OCR outputs.
  - [`span_protection.py`](file:///e:/Sarathi/src/sarathi/shakti/text/span_protection.py): Common text span mask and restoration utilities.
  - [`transliteration.py`](file:///e:/Sarathi/src/sarathi/shakti/text/transliteration.py): Phonetic Romanized Indic (Hinglish) to Devanagari rule-based transducer.
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

### 13. Developer & Engineering Tools (`tools/`)
- [`benchmark_ocr_and_font.py`](file:///e:/Sarathi/tools/benchmark_ocr_and_font.py): Performance and accuracy benchmark suite comparing OCR engines and font transducers against reference data.
- **`scripts/`**:
  - [`Setup-OCRModels.ps1`](file:///e:/Sarathi/tools/scripts/Setup-OCRModels.ps1): Automated model downloader, provisioner, and SHA-256 verifier ensuring declared OpenVINO OCR model assets match `data/ocr/manifest.json`.
  - [`update_sarathi.ps1`](file:///e:/Sarathi/tools/scripts/update_sarathi.ps1): Interactive environment and dependency manager providing uv bootstrapping, root `.venv` synchronization, PyPI update audits, and lockfile maintenance.
