# Sarathi V3

**Development version:** `3.0.0.dev0`  
**Branch:** `v3`  
**Updated:** 10-09-2026 (Asia/Kolkata)

Sarathi is a local-first document intelligence application for OCR, native document extraction, translation, font conversion, bank-statement processing, and optional cloud-assisted document processing.

V3 is the simplification line. It keeps useful product behavior while removing internal architecture machinery that does not justify its cost.

> `main` remains the V2 stable line. V3 development happens on `v3`; V3 changes are not merged into V2 merely to preserve history.

---

## Principles

- Prefer the smallest implementation that completely solves the current requirement.
- Preserve user-visible behavior while deleting redundant internal layers.
- One decision should have one clear authority; avoid shadow managers and parallel policy paths.
- Add abstractions only when current code has a demonstrated need for them.
- Keep capabilities focused on document/domain work; shared runtime concerns stay outside capability implementations.
- Tests protect behavior and important boundaries, not arbitrary architecture metrics.
- Compatibility exists where users or persisted data require it, not automatically for superseded internal APIs.

---

## Runtime flow

```text
Input documents
      ↓
Identify
      ↓
Resolve required capabilities
      ↓
Execute pipeline
      ↓
OCR / Extract / Translate / Convert / Consolidate
      ↓
Commit completed outputs
```

The current internal names remain while V3 simplification proceeds:

- **Agni** — composition and process lifecycle
- **Kosh** — plugin/capability declaration registry
- **Manthan** — initial and continuation plan resolution
- **Pravaha** — plan execution, hand-off, retry/cancellation flow
- **Yantra** — hardware allocation and execution concurrency
- **Kavacha** — declared security-policy authorization and path safety
- **Smriti** — reusable result cache
- **Darpana** — runtime/quality observation
- **Shakti** — document and business capabilities
- **Mukha** — presentation layer

These names are not a reason to preserve unnecessary subsystems. V3 may flatten or rename them when doing so makes the product easier to understand and maintain.

---

## V3 simplification completed so far

### Runtime and governance

- Replaced architecture-heavy contribution rules with simple-code-first guidance.
- Removed the arbitrary 30 KB source-file architecture rule.
- Removed duplicated import-linter architecture policy and stale boundary inventories.
- Reduced architecture tests to meaningful sanity checks.
- Moved process lifecycle ownership into Agni.
- Removed Dvara; Kosh now performs atomic provider declaration registration directly.

### Planning and execution

- Manthan is the sole authority for initial and continuation capability plans.
- Pravaha no longer silently changes execution profiles or constructs competing continuation plans.
- Continuation preserves the requested profile and fails clearly when the route is incompatible.

### Hardware policy

- Yantra owns device allocation and concurrency policy.
- Removed the synthetic multi-device `DeviceSlotPool` / hybrid OCR scheduling path.
- OCR owns page decomposition and OCR behavior, not CPU/GPU spillover or worker policy.
- Real allocator-backed preferred-device/spillover behavior remains intact.

### Security boundary

- Removed the unused parallel `OutboundRequest` / per-request outbound policy model.
- Kavacha authorizes the owning plugin's declared PII/network/external-processing/credential-name requirements before capability execution.
- Cloud clients own provider-specific HTTP transport and credential-value lookup.
- Kavacha is intentionally not a credential vault, HTTP proxy, PII scanner, or network gateway.

---

## Current capabilities

- Native document extraction
- Local OCR with RapidOCR/OpenVINO and targeted Tesseract fallback
- Hindi/English translation
- Legacy Hindi font conversion and DOCX output
- Bank statement extraction and consolidation
- Optional cloud OCR/translation adapters for Mistral, Gemini, Azure, and Bhashini

---

## Development setup

Python `>=3.13,<3.14` is the current runtime baseline.

```powershell
uv sync --all-extras --group dev
```

Run Sarathi:

```powershell
# Local web UI
.\arambha.bat

# Or module entry point
uv run python -m sarathi

# CLI example
uv run sarathi --input "path/to/document.pdf" --requirement "read_native" --profile "instant"
```

Useful verification commands:

```powershell
uv run --group dev python -m compileall -q src tests scripts
uv run ruff check .
uv run --group dev pytest -q tests/architecture
uv run --all-extras --group dev pytest -q -m "not browser and not real_model and not performance"
```

The CI workflow runs on both `main` and `v3`. V3 uses the fully loaded OCR test environment with verified model assets and Tesseract English/Hindi language packs.

---

## Documentation

Detailed specifications currently remain under `Vedas/` while they are simplified alongside the owning code. Some filenames still carry the `Sarathi_V2_` prefix because V3 is being migrated incrementally rather than rewritten from scratch.

Key references:

- [Core Runtime Specification](Vedas/Sarathi_V2_Core_Runtime_Spec.md)
- [Shared Services Specification](Vedas/Sarathi_V2_Shared_Services_Spec.md)
- [Plugin & Capability Specification](Vedas/Sarathi_V2_Plugin_Capability_Spec.md)
- [OCR Specification](Vedas/Sarathi_V2_OCR_Spec.md)
- [Native Extraction Specification](Vedas/Sarathi_V2_Native_Extraction_Spec.md)
- [Translation Specification](Vedas/Sarathi_V2_Translation_Spec.md)
- [Font Conversion Specification](Vedas/Sarathi_V2_Font_Conversion_Spec.md)
- [Bank Statement Specification](Vedas/Sarathi_V2_Bank_Statement_Spec.md)
- [Mukha Screen Specification](Vedas/Sarathi_V2_Mukha_Screen_Spec.md)
- [Implementation Guide](Vedas/Sarathi_V2_Implementation_Guide.md)

V3 documentation should describe implemented behavior, not speculative infrastructure. When an old V2 rule conflicts with current V3 implementation, fix or remove the stale rule as part of the owning subsystem cleanup.

---

## Version policy

- `main` — V2 stable/history line
- `v3` — active V3 development line
- current package version — `3.0.0.dev0`
- first stable V3 release — `3.0.0`

V3 is an evolution of the tested V2 codebase, not a rewrite-from-zero. Each subsystem is simplified one at a time and must remain behaviorally validated before moving to the next.
