# Sarathi V2 — Implementation Guide

**Specification Updated:** 10-09-2026 (Asia/Kolkata)

This guide describes the current physical implementation boundaries, bootstrap
wiring, development baseline, and verification gates. Detailed capability
behavior belongs in the capability specifications; this file does not duplicate
those rules or pre-allocate speculative modules.

## Development Baseline

Sarathi V2 targets:

- Windows 11 x64 for the primary desktop runtime;
- Python 3.13 (`>=3.13,<3.14`);
- `uv` for dependency resolution and environment management;
- `src/` package layout;
- `pyproject.toml` as dependency declaration authority;
- `uv.lock` as the exact resolved dependency lock.

The runtime is editor-agnostic. No application behavior may depend on a
particular IDE.

## Implementation Order

Shared contracts and policy must exist before the runtime that consumes them:

```text
Sankalpa — contracts
→ Dosh — errors
→ Sutra — settings
→ Kavacha — security policy
→ Darpana — telemetry
→ Smriti — optional cache
→ Yantra — execution resources
→ Nabhi — registry/resolution/pipeline
→ Agni — composition and lifecycle
→ Mukha — presentation
→ Shakti — capability implementations
```

Capability work follows demonstrated product dependencies rather than creating
frameworks in advance.

## Runtime Ownership

| Area | Owner | Boundary |
|---|---|---|
| Application composition and process lifecycle | `sarathi.agni` | Select providers, construct shared services, start/close runtime components |
| Plugin/capability declaration registry | `sarathi.nabhi.kosh` | Validate and atomically register provider metadata supplied by Agni |
| Capability planning | `sarathi.nabhi.manthan` | Resolve dependency-ordered capability plans |
| Pipeline execution, retry and quarantine decisions | `sarathi.nabhi.pravaha` | Execute plans and own failure lifecycle |
| Resource allocation/execution | `sarathi.yantra` | Choose compatible execution resources and bounded concurrency |
| Security/privacy authorization | `sarathi.kavacha` | Enforce approved policy boundaries |
| Telemetry | `sarathi.darpana` | Observe factual runtime/quality events |
| Result cache | `sarathi.smriti` | Optional reusable-result cache |
| Presentation | `sarathi.mukha` | Render runtime state; no domain execution |
| Domain/document behavior | `sarathi.shakti.*` | Implement capabilities behind canonical provider contracts |

`Prana` is a deprecated compatibility view only. Agni owns lifecycle state and
ordering directly.

## Provider Registration and Executable Wiring

There is no separate discovery/registration manager.

```text
sarathi.shakti.providers
        ↓
Agni resolves enabled PluginProviders
        ├── provider metadata ──→ Kosh.register_providers(...)
        │                         validate full batch first
        │                         then mutate registry atomically
        │
        └── provider factories ─→ executable Capability objects
                                  ↓
                              Pravaha bindings
```

Rules:

- Agni decides which providers are active for the runtime.
- Kosh never imports Shakti or scans the filesystem for plugins.
- Kosh accepts provider objects from Agni and owns declaration consistency.
- Provider registration is idempotent for identical existing declarations.
- Conflicting or duplicate incoming plugin/capability IDs fail before partial
  registry mutation.
- Runtime executable bindings and Kosh declarations must maintain exact 1:1
  consistency at bootstrap.
- `Agni(capabilities=...)` replacement composition registers only declarations
  relevant to supplied executable capabilities plus explicitly supplied plugin
  metadata.

## Current Project Shape

```text
Sarathi/
├── README.md
├── AGENTS.md
├── pyproject.toml
├── uv.lock
├── config/
├── data/
├── scripts/
├── src/sarathi/
│   ├── agni/
│   │   ├── bootstrap.py
│   │   ├── dispatcher.py
│   │   ├── preflight.py
│   │   ├── readiness.py
│   │   └── wiring.py
│   ├── sankalpa/
│   ├── dosh/
│   ├── sutra/
│   ├── kavacha/
│   ├── darpana/
│   ├── smriti/
│   ├── yantra/
│   ├── nabhi/
│   │   ├── kosh.py
│   │   ├── manthan.py
│   │   ├── prana.py          # deprecated compatibility view
│   │   ├── quarantine.py
│   │   ├── pravaha/
│   │   └── artifacts/
│   ├── mukha/
│   └── shakti/
│       ├── providers.py
│       ├── darshana/
│       ├── native_extraction/
│       ├── ocr/
│       ├── font_conversion/
│       ├── translation/
│       ├── bank_statements/
│       ├── mistral/
│       ├── gemini/
│       ├── azure/
│       └── bhashini/
├── tests/
└── Vedas/
```

This is an inventory of current architectural areas, not a mandate to create
empty files. New modules are introduced only when a demonstrated responsibility
cannot remain cohesive in an existing module.

## File Responsibility Rules

- `agni/bootstrap.py` owns the concrete application runtime and process lifecycle.
- `agni/preflight.py` owns bootstrap validation and provider selection helpers.
- `agni/wiring.py` constructs concrete services and executable capability maps.
- `agni/readiness.py` coordinates provider readiness facts for presentation.
- `nabhi/kosh.py` owns plugin/capability declaration registration and lookup.
- `nabhi/manthan.py` owns capability plan resolution.
- `nabhi/pravaha/` owns execution of resolved plans and retry/quarantine flow.
- `nabhi/artifacts/` owns staging and final artifact commit behavior.
- `yantra/` owns execution-resource policy and bounded execution helpers.
- `shakti/<capability>/` owns only capability/domain behavior and provider adapters.

File size by itself is not an architecture rule. Split a module when it carries
multiple responsibilities, not to satisfy an arbitrary byte threshold.

## Data and Configuration

```text
Code        → algorithms and runtime decisions
config/     → operator/runtime policy
 data/      → mappings, model manifests, profiles and validated capability data
pyproject   → declared dependencies
uv.lock     → exact dependency resolution
Vedas/      → architecture and behavioral specifications
```

Human-editable data must remain data rather than becoming a pseudo-programming
language. Runtime configuration must not duplicate capability knowledge.

## OCR Runtime Provisioning

OCR tests and supported local execution depend on declared model assets and
Tesseract language support where fallback is enabled.

- `scripts/Setup-OCRModels.ps1` provisions model files declared by the OCR model
  manifest and verifies SHA-256 before accepting them.
- CI installs Tesseract English and Hindi language packs for full OCR readiness.
- Windows-only `.bat`/`.exe` shim assertions remain Windows-specific; Linux CI
  verifies the cross-platform executable path and actual supported OCR behavior.
- Browser CI receives the same verified OCR readiness inputs as the deterministic
  test lane so the UI does not test a falsely disabled OCR capability.

## Verification Gates

Every subsystem change should first run focused tests, then the complete CI gate
before the subsystem is considered finished.

Canonical CI lanes:

```text
Lint & Compilation
    python compileall
    ruff check

Architecture Sanity
    tests/architecture

Unit & Integration Tests
    full extras
    verified OCR model provisioning
    Tesseract ENG + HIN
    deterministic non-browser/non-performance suite

Browser Tests
    full extras
    verified OCR model provisioning
    Tesseract ENG + HIN
    Playwright Chromium
    browser-marked suite
```

A change is not complete while any required lane is red.

## Architecture Change Discipline

For architecture simplification:

1. identify the actual decision owner;
2. move behavior before deleting the old abstraction;
3. migrate meaningful tests to the surviving owner;
4. remove the old public export, state, file, and duplicate tests;
5. update affected specifications in the same branch;
6. run focused and full verification;
7. do not retain a compatibility layer unless a demonstrated external consumer
   requires it.

The goal is one decision authority per concern, not one wrapper class per noun.
