# Sarathi

Sarathi is a local-first document intelligence application for extracting, understanding, translating, converting, and consolidating documents. The current package version is `3.0.0.dev0` and the Python runtime baseline is `>=3.13,<3.14`.

The repository is intentionally simple: `development` is the active integration branch and `main` is the stable branch. Changes are completed and validated on `development`, then promoted to `main` only after the permanent CI gates pass.

## What Sarathi does

Sarathi currently provides:

- native text and structure extraction from supported documents;
- local OCR using RapidOCR/OpenVINO with targeted Tesseract support;
- Hindi/English translation;
- legacy Hindi font conversion and DOCX output;
- bank-statement extraction and consolidation;
- optional cloud OCR/translation adapters for Mistral, Gemini, Azure, and Bhashini;
- a loopback-only local web interface backed by Starlette/Uvicorn and a production TypeScript/Preact single-page application.

Capability availability depends on installed optional dependencies, configured credentials, and runtime readiness checks. Sarathi must report unavailable capabilities explicitly rather than silently changing the requested behavior.

## Runtime flow

```text
CLI / Local Web UI
        |
        v
     Agni
composition + lifecycle
        |
        v
Kosh declarations -> Manthan planning
                        |
                        v
                    Pravaha
               pipeline execution
                        |
                        v
                     Shakti
             document capabilities
                        |
                        v
                committed artifacts
```

Cross-cutting services are explicit: Kavacha authorizes real security/privacy boundaries, Yantra owns execution/device resources, Smriti provides optional caching, Darpana records runtime/quality history, Sankalpa defines shared contracts, Sutra loads settings, and Dosh defines shared errors.

`sarathi.nabhi` is the physical runtime namespace that currently contains Kosh, Manthan, Pravaha, artifact/quarantine support, and the deprecated Prana compatibility adapter. It is not a second planning or execution authority: Kosh owns declarations, Manthan owns planning, and Pravaha executes the returned plan.

## Plugin model

Sarathi follows a modular, plugin-first architecture under `src/sarathi/shakti/`. Each capability is implemented as an independent provider:

- **Provider contract**: Extends `PluginProvider` in `sarathi.sankalpa`, declaring plugin metadata, security declarations (PII, network, credentials), and capability factories.
- **Registration**: Built-in providers are listed in `BUILTIN_PLUGIN_PROVIDERS` inside `src/sarathi/shakti/providers.py`.
- **Extensibility**: Adding a new capability requires only adding the provider package under `src/sarathi/shakti/`, registering it in `BUILTIN_PLUGIN_PROVIDERS` (or via `Agni(extra_plugin_providers=...)`), and declaring the component in `Vedas/architecture.manifest.json`. Core planning, execution, and presentation subsystems remain untouched.

## Security model

Sarathi is local-first and fail-closed:

- **Transport boundary**: The Mukha web server binds strictly to the loopback interface (`127.0.0.1`) with Host and Origin validation.
- **Kavacha authorization**: Pravaha authorizes every capability execution and provider call against Kavacha's `SecurityPolicy` before invoking operations. Cloud capabilities requiring network access or API credentials must be explicitly permitted.
- **Filesystem containment**: Input, runtime staging, and output roots are strictly separated; path traversal attempts outside authorized boundaries are rejected with `403 Forbidden`.
- **Artifact promotion**: Staged streaming promotion with SHA-256 verification and automatic rollback on failure prevents partial or contaminated artifacts.

## Repository map

| Path | Purpose |
| --- | --- |
| `src/sarathi/` | Python application/runtime code |
| `ui/` | TypeScript/Preact single-page application |
| `Vedas/` | Current architecture and engineering documentation |
| `tests/` | Unit, integration, architecture, and browser test suites |
| `config/` | Runtime configuration (`settings.toml`) |
| `data/` | Checked-in data assets (bank mappings, OCR manifests) |
| `scripts/` | Environment, model, and benchmark utilities |
| `.github/workflows/ci.yml` | Permanent read-only CI pipeline |

The canonical production topology is machine-readable in `Vedas/architecture.manifest.json` and validated by architecture tests.

## Setup

Install the project and development dependencies:

```powershell
uv python install 3.13
uv sync --all-extras --group dev
```

Run the local web application:

```powershell
.\arambha.bat
```

Or run the module directly:

```powershell
uv run python -m sarathi
```

CLI example:

```powershell
uv run sarathi --input "path/to/document.pdf" --requirement "read_native" --profile "instant"
```

## Frontend development

The frontend lives in `ui/` and compiles to `src/sarathi/mukha/web/ui/`:

```powershell
cd ui
npm ci
npm run build      # Typecheck with tsc and bundle with Vite
```

## Validation

Local validation mirrors the 5 permanent CI gates:

```powershell
# Gate 1: Compilation & Ruff lint
uv run python -m compileall -q src tests scripts
uv run ruff check .

# Gate 2: Architecture sanity
uv run --group dev pytest -q tests/architecture

# Gate 3: Frontend TypeScript build
cd ui; npm run build; cd ..

# Gate 4: Deterministic unit & integration tests
uv run --all-extras --group dev pytest -q -m "not browser and not performance and not real_model and not architecture"

# Gate 5: Accelerated Playwright browser tests
uv run --all-extras --group dev pytest -q -m browser
```

## Documentation

Start with [`Vedas/README.md`](Vedas/README.md). It links the current architecture, capability, Mukha transport, cleanup roadmap, and machine-readable architecture manifest.

Current documentation describes the code that exists now. Superseded product-generation documents are intentionally not kept in the active Vedas tree; historical context belongs in Git history, not in current operating instructions.