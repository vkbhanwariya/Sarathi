# Sarathi V2

**README Updated:** 08-09-2026, 11:55 PM IST (Asia/Kolkata)


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
| [Shakti Plugin & Capability Specification](Vedas/Sarathi_V2_Plugin_Capability_Spec.md) | Shared plugin rules, **Darshana --- Identify**, built-in provider catalog (including Mistral, Gemini, Azure, Bhashini cloud capabilities), and capability-document routing |
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
-   Sarathi operates local-first, plugin-first, and dependency-disciplined.
-   Modern, actively maintained dependencies are preferred after compatibility
    and benchmark verification.
-   Optional fallbacks remain disabled unless the primary path fails or an
    explicit profile requests them.
-   Canonical DOCX typography standardizes on a 12 pt baseline across scripts:
    English in `Times New Roman`, Hindi and mixed Devanagari in `Nirmala UI`,
    with capability-local typography helpers and script-segmented legacy export.
-   Implementation strictly adheres to the locked architecture and linked
    capability specifications.

------------------------------------------------------------------------

## 7. Local Run Command

Sarathi provides a single interactive **Mukha Local Web** presentation dashboard and a non-interactive CLI entry point using the canonical Agni runtime bootstrap path:

```bash
# Interactive Local Web Dashboard (opens http://127.0.0.1:<port> in default browser)
.\arambha.bat
# or:
uv run python -m sarathi

# Non-interactive CLI execution via console script entry point
uv run sarathi --input "path/to/document.pdf" --requirement "read_native" --profile "instant"

# Non-interactive execution via Python module entry point
uv run python -m sarathi --input "path/to/document.txt" --requirement "read_native" --output-root "Output"
```

------------------------------------------------------------------------

## 8. Contributing & Development Setup

Sarathi strictly enforces architectural authority and deterministic runtime behavior:

- **Single Source of Truth**: [AGENTS.md](AGENTS.md) and locked specifications in [Vedas/](Vedas/) are the binding authority for architecture, contracts, and scoped testing.
- **Environment Setup**: Python 3.13 (`>=3.13,<3.14`). Sync locked dependencies:
  ```powershell
  uv sync --all-extras --group dev
  ```
- **Pre-Commit Verification**: Run the canonical verification gate before submitting changes:
  ```powershell
  uv run lint-imports
  uv run --group dev python -m compileall -q src tests
  uv run --group dev pytest -q -m architecture
  uv run --group dev pytest -q <targeted-test-path>
  git diff --check
  ```
- **Scoped Testing**: Test according to impact (local change $\rightarrow$ targeted test; subsystem change $\rightarrow$ subsystem tests; global milestone $\rightarrow$ full suite).
- **Protected Baselines**: The Font Conversion architecture (`src/sarathi/shakti/font_conversion/`, `src/sarathi/shakti/docx_exporter/`, and `tests/font_conversion/`) is a protected baseline. Any cross-cutting change must verify that `tests/font_conversion` remains 100% passing.

------------------------------------------------------------------------

## 9. Security & Privacy Model

Sarathi operates as a local-first, privacy-preserving document intelligence runtime:

1. **Local-First & Offline Default**:
   - Documents are processed entirely on the local machine without transmitting contents, OCR text, or extracted financial data to external endpoints.
   - The **Kavacha** subsystem strictly regulates network policies; outbound socket connections are blocked by policy when network access is disallowed.
2. **Web Interface Security (Mukha)**:
   - The Mukha HTTP server binds strictly to loopback interfaces (`127.0.0.1` or `::1`).
   - Standard security headers are enforced on all responses: `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and strict referrer policies.
3. **Telemetry & Cache Privacy (Darpana & Smriti)**:
   - Darpana records structural metrics, execution durations, and outcome statuses. Document text and sensitive PII are never logged to telemetry buffers or serialized in trace events.
   - Smriti cache keys derive from privacy-safe content fingerprints and framed length-delimited hashes without leaking local file paths or raw payload text.
4. **Vulnerability Reporting**:
   - If you discover a security vulnerability, please report it responsibly directly to the maintainers rather than opening a public issue.

------------------------------------------------------------------------

## 10. Release History (Changelog)

### [2.1.3] - 2026-09-08

- **Cloud Document Intelligence & Multimodal Capability Suite**:
  - **Mistral AI Plugin (`shakti.mistral`)**: Dedicated, isolated Shakti plugin providing Cloud OCR (`mistral-ocr-latest`) with document markdown, layout bounding boxes, and tabular extraction, plus multilingual Translation (`mistral-large-latest`).
  - **Google Gemini Plugin (`shakti.gemini`)**: Multimodal vision OCR (`gemini-2.5-flash`) and neural translation via direct Google Generative Language REST APIs without heavy vendor SDK dependencies.
  - **Microsoft Azure Plugin (`shakti.azure`)**: Azure AI Document Intelligence layout OCR (`documentModels/prebuilt-layout`) extracting word-level confidences, polygon spans, paragraphs, and tables, plus direct Azure AI Translator REST integration.
  - **Bhashini Indic AI Plugin (`shakti.bhashini`)**: Government of India National Language Translation Mission pipeline integrating Chitrakshar OCR (22 scheduled Indian languages) and IndicTrans2 NMT via zero-leak direct HTTP inference calls.
- **Standardized Cloud Confidence Matrix & Pramana Telemetry**:
  - Multi-tier confidence quantification across all 4 cloud OCR providers: span/word-level polygons, page-level (`min_confidence`, `max_confidence`, `confidence` stored in `PageData.metadata`), and document-level aggregate (`ConfidenceValue(score, method="<provider>_mean")` on `Result.confidence`).
  - Live telemetry integration emitting `PramanaRecord` events to the Darpana bus for real-time visualization in Mukha UI.
- **Zero-Leak Direct REST Transport & Kavacha Security Gating**:
  - All cloud providers communicate via lightweight direct REST clients (`httpx`), completely eliminating vendor telemetry SDKs and runtime bloat.
  - Strict Kavacha policy enforcement: each provider declares explicit `SecurityDeclaration(network_access=True, external_processing=True, required_secrets=...)`, rejected by default unless explicitly permitted in operator configuration.
  - Lossless canonical synthesis into `CanonicalDocument`, `PageData`, `TextSpan`, and `TableData` with automated `.txt` and formatted `.docx` artifact export.
- **Mukha UI/API Wiring Remediation, State Hydration & Runner Lifecycle**:
  - Remediated Mukha presentation models: added `WARNING` and `PARTIAL` to `_TERMINAL_STATUSES`, mapped run history to canonical schema, scoped review items to active run, and added Tesseract 5 fallback readiness checks.
  - Remediated Mukha HTTP transport: added `/pdf_page` and `/raw` routes across intake and artifact endpoints, supported `?download=1` on diagnostics bundles, and ensured uniform JSON error formatting across all `/api/*` endpoints.
  - Hardened runner lifecycle: cleared review intents on run start, reset `started_ns` across file and stage transitions, and cleared live worker references on completion.
  - Frontend reactive state: added `isHydrated` tracking, dynamic review badge binding, strict eligible-item filtering for "Start" button, safe cancel confirmation, null-safe confidence rendering, and separate accuracy reporting.
  - Enforced truthful telemetry and eliminated synthetic metric defaults across font conversion, native extraction, translation, and cloud OCR plugins.

### [2.1.2] - 2026-09-08

- **Mukha UI Design System & Tokens (Phase 6)**: Curated minimal design tokens in `app.css` (compact 32px toolbars, 12-13px typography, subtle gradients, and unified status indicators); improved density, contrast, and visual rhythm across all 6 dashboard screens.
- **Test Suite Audit & CI Hardening (Phases 1-5)**:
  - *Phase 1 (CI & Lint Unblock)*: Resolved all ruff linting errors across tests; established explicit pytest marks (`unit`, `integration`, `architecture`, `browser`) in `pyproject.toml`.
  - *Phase 2 (False-Success Tests)*: Remediated false-success tests (fixed cooperative cancellation UI interception in `runner.js`, resolved stale async run summary in `test_runs_e2e.py`, aligned JS tests with canonical `buildRequestPayload()`, replaced MagicMock with factual `DeviceInfo` dataclasses in Yantra tests, correctly classified mock-based translation tests as integration).
  - *Phase 3 (CI Decoupling & Modularization)*: Decoupled GitHub Actions CI workflow into parallel isolated jobs (`lint`, `architecture`, `test`, `browser`); modularized `ocr/capability.py` and `mukha/web/http_handler.py` under the strict 30 KB limit.
  - *Phase 4 (Structural Deduplication)*: Dismantled obsolete `tests/kernel/` in favor of canonical `tests/nabhi/`; consolidated duplicate bank deduplication tests into single canonical `tests/bank_statements/test_deduplicator.py`; enforced affirmative invariant test naming across all test suites.
  - *Phase 5 (Critical Defect Regressions)*: Added rigorous regression coverage for critical defects: layout-preserving OCR continuation hand-off, recursive prerequisite profile validation in `Manthan`, UI "Process Documents" button disabling with 0 eligible inputs in `home.js`, and `avg_confidence=None` anti-fabrication for uncomputed/non-applicable confidence metrics.
- **Test Suite Consolidation, Bottleneck Elimination & Canonical Re-Homing**:
  - *Stale Test Remediation*: Corrected stale OCR tests (`LAYOUT_PRESERVING` profile assertion and positive execution verification replacing negative rejection tests).
  - *Server Teardown Bottleneck Elimination*: Implemented `poll_interval=0.05` in `_MukhaHTTPServer.serve_forever()` reducing shutdown time from 500ms to 50ms, and replaced blind sleeps with reactive condition polling in Mukha tests (reducing test execution time by over 70%).
  - *Duplicate & Ad-Hoc Suite Consolidation*: Merged duplicate test files (`test_cross_statement_dedup.py` into `test_deduplicator.py`, `test_docx_fidelity.py` into `test_docx_exporter.py`, `test_akshara_remediation.py` into `test_akshara_golden.py`), and replaced ad-hoc `test_t15_hardening.py` with canonical `test_cancellation_hardening.py`.
  - *Canonical Domain Re-Homing*: Dissolved non-canonical `tests/capabilities/` and partitioned miscellaneous cross-domain files (`test_pipeline_continuation_integrity.py`, `test_runtime_bootstrap_integrity.py`, `test_font_and_translation_integrity.py`, `test_bootstrap_*.py`) into their true single-owner domain test packages (`tests/agni/`, `tests/bank_statements/`, `tests/translation/`, `tests/font_conversion/`, `tests/smriti/`, `tests/configuration/`).
- **Canonical Cleanliness & Anti-Drift Governance**: Relocated root manifest validator to canonical `tests/architecture/manifest_validator.py`, eliminated non-canonical `tools/` root folder, updated CI compileall paths, and codified Rule 13 ("Strict Governance — Zero Architectural Drift & Explicit Approval for New Files/Folders") in `AGENTS.md`.


### [2.1.1] - 2026-09-07

- **Windows Explorer Foreground Reveal**: Overcame Windows Foreground Lock restriction when clicking "Open Output Folder" across all capability modules (Font Conversion, OCR, Translation, Bank Statements, Native Extraction) using Win32 COM `Shell.Application.Windows()` and parameterized raw PowerShell activation (`-targetPath`).
- **Pre-Run Input File Preview**: Cached intake document selections in `RunCoordinator` during `POST /api/intake`, resolving `inp-001` identifiers instantly prior to pipeline initiation.
- **Preview Dialog & Cancellation Responsiveness**: Attached direct dismissal handlers to close button, backdrop clicks, and Escape key in `#doc-preview-dialog`, preventing modal click trapping and restoring instant responsiveness to the "Cancel Run" control.
- **Global Top-Level Progress Bar**: Embedded dynamic progress bar (`#top-progress-bar`) directly beneath the global header, updated in real time via Server-Sent Events (SSE) stream reflecting active stage and completion percentage.
- **Run History & Historical Results Inspection**: Added `GET /api/runs/<run_id>/summary` endpoint, history drawer integration, and direct `"📋 View Result"` loading into Samapti (Screen 4) alongside `"🔍 Telemetry"` into Nirikshana (Screen 5).
- **Tesseract Fallback Quality Telemetry**: Exposed quality recovery metrics, regional confidence gain, and Tesseract interception counts in Nirikshana (Screen 5).
- **Full Capability & Parameter Wiring**: Seamless bidirectional wiring across all 5 Shakti modules (`ocr`, `font_conversion`, `translation`, `bank_statements`, `read_native`), including translation direction parameters.

### [2.1.0] - 2026-09-06

- **Pillar A: Declarative Architecture Manifest**: Introduced `Vedas/architecture.manifest.json` with strict JSON schema verification asserting explicit module roles, boundaries, and default-deny internal import policy.
- **Pillar B: Automated Layering & Dependency Linter**: Integrated `import-linter` contracts enforcing foundational isolation (Sankalpa foundation, Shakti sibling independence, generic Nabhi decoupling, and Mukha presentation isolation).
- **Pillar C: Subsystem Test Suites & Architectural Fitness**: Created dedicated `tests/architecture/` suite verifying AST boundary isolation, manifest topology adherence, platform service constraints, lazy module loading, explicit exports, and zero-monolith invariants.
- **Pillar D: Zero-Monolith Modular Decomposition**: Decomposed all monolithic modules (>30 KB) across the system into focused single-responsibility subpackages:
  - `shakti/native_extraction/readers/`: `pdf_reader.py`, `html_reader.py`, `spreadsheet_reader.py`, `docx.py`, `delimited.py`, `common.py`.
  - `shakti/ocr/engine/`: `rapidocr.py`, `tesseract.py`, `preprocessing.py`, `rasterize.py`, `readiness.py`, `parser.py`, `factory.py`, `coordinator.py`.
  - `nabhi/artifacts/`: `paths.py`, `atomic_io.py`, `manifest.py`, `boundary.py`, `promotion.py`, `finalization.py`, `workspace.py`.
  - `shakti/docx_exporter/`: `helpers.py`, `styles.py`, `table_builder.py`, `section_builder.py`, `exporter.py`.
  - `agni/`: `preflight.py`, `wiring.py`, `readiness.py`, `dispatcher.py`, `bootstrap.py`.
  - `nabhi/pravaha/`: `common.py`, `lifecycle.py`, `pipeline.py`, `engine.py`.
  - `mukha/web/`: `runner.py`, `state_builder.py`, `server.py`, `http_handler.py`, `native_picker.py`.
- **Zero Monolithic Files**: 0 files exceeding 30 KB remain across `src/sarathi/`.
- **100% Backward Compatibility**: Maintained seamless public façade re-exports across all package roots ensuring zero breakage for external callers and existing test suites.

### [2.0.0] - 2026-09-04

- **Security & Kavacha**: Strict loopback host validation in Mukha; mandatory security headers (`CSP`, `nosniff`, `DENY`); outbound network access policy enforcement.
- **Yantra Execution Binding**: Concrete `backend_locators` on `DeviceInfo` for multi-GPU identification (`GPU.0`, `GPU.1`, `cuda:0`, `cuda:1`); strict execution binding propagation to translation and OCR backends without `TypeError` fallbacks.
- **Composition Root Dependency Injection**: Topological bootstrap order in `Agni.bootstrap()`; injected dependencies via standard constructors, eliminating post-construction private attribute mutation.
- **Telemetry & Cancellation (Darpana & Pravaha)**: Added `FailureCode.OPERATION_CANCELLED` and `"cancelled"` outcome recording; immediate bypass of retry loops and quarantine storage on user cancellation; configurable live telemetry buffers in Sutra settings.
- **Artifact Naming Disambiguation**: Deterministic artifact filename generation avoiding collisions across multi-document batches.
- **Bank Statement Financial Correctness**: Continuous monotonic sequence ID indexing across multi-page/multi-table parses; strong-signal deduplication with contradiction detection per Bank Statement Veda.
- **Smriti Two-Tier Cache Integrity**: Framed length-delimited input fingerprinting preventing boundary collisions; deterministic set sorting in digest computations; multi-document envelope serialization/deserialization.
- **Font Conversion & Mixed-Font DOCX Fidelity**: Consolidated Roopa font-conversion engine preserving document structure, formatting, and run stitching across mixed KrutiDev, DevLys, and Unicode Hindi text.
