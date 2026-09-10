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
- a loopback-only local web interface backed by Starlette/Uvicorn and a TypeScript/Preact frontend migration.

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

## Repository map

| Path | Purpose |
| --- | --- |
| `src/sarathi/` | Python application/runtime code |
| `ui/` | TypeScript/Preact frontend |
| `Vedas/` | Current architecture and engineering documentation |
| `tests/` | Unit, integration, architecture, browser, and specialized tests |
| `config/` | Runtime configuration |
| `data/` | Checked-in configuration/data assets such as bank mappings and OCR manifests |
| `scripts/` | Environment, model, benchmark, and maintenance scripts |
| `.github/workflows/ci.yml` | Permanent CI definition |

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

## Validation

Useful local checks mirror the permanent CI gates:

```powershell
uv run --group dev python -m compileall -q src tests scripts
uv run ruff check .
uv run --group dev pytest -q tests/architecture
uv run --all-extras --group dev pytest -q -m "not browser and not performance and not real_model and not architecture"
```

CI also builds the TypeScript UI and runs Playwright browser tests. OCR CI provisions verified model assets and the required Tesseract language packs.

## Documentation

Start with [`Vedas/README.md`](Vedas/README.md). It links the current architecture, capability, Mukha transport, cleanup roadmap, and machine-readable architecture manifest.

Current documentation describes the code that exists now. Superseded product-generation documents are intentionally not kept in the active Vedas tree; historical context belongs in Git history, not in current operating instructions.

## Engineering rule

Preserve behavior, keep one clear owner for each decision, delete obsolete paths instead of maintaining parallel architectures, and complete one cleanup phase—including tests and documentation—before starting the next.