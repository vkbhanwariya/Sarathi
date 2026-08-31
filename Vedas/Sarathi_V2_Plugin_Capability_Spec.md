# Sarathi V2 — Shakti — Plugin & Capability Specification

**Specification Updated:** 31-08-2026, 07:32 PM IST (Asia/Kolkata)

This file owns shared plugin rules, **Darshana — Identify**, and capability
specification routing. Capability-local behavior lives only in its owning file.

## Shakti --- Plugin Ecosystem

**Shakti --- Plugin Ecosystem** contains document and business capabilities.

``` text
Plugin owns:
    domain/capability behavior
    capability-specific preprocessing
    capability-specific confidence and validation
    engine adapters where required
    validation and use of its approved Anubhava data

Plugin does not own:
    worker pools or hardware allocation
    global cache or runtime state
    telemetry or logging infrastructure
    presentation framework
    global configuration or security policy
    generic Anubhava service, loader, writer, database, or optimizer
```

A plugin uses canonical contracts and shared services through their public
boundaries. Its `plugin.py` remains a thin declaration/integration boundary,
not a local service container.

## Darshana --- Identify

**Darshana --- Identify** determines what the input is. It may report media or
document type, structural characteristics, likely document family, and other
evidence required for capability resolution.

``` text
Document
    ↓
Darshana — Identify
    ↓
Document characteristics
```

The core does not identify PDFs, bank statements, scans, or other domain types.

## Capability Specifications

| Capability | Canonical local specification |
|---|---|
| **Shruti — Read / Native Extraction** | [Native Extraction Specification](Sarathi_V2_Native_Extraction_Spec.md) |
| OCR | [OCR Specification](Sarathi_V2_OCR_Spec.md) |
| **Roopa — Convert / Font Conversion** | [Font Conversion Specification](Sarathi_V2_Font_Conversion_Spec.md) |
| Translation | [Translation Specification](Sarathi_V2_Translation_Spec.md) |
| Bank Statement Consolidation | [Bank Statement Consolidation Specification](Sarathi_V2_Bank_Statement_Spec.md) |
