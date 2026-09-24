# Sarathi Product Decisions — Task Hierarchy

This document records the canonical, approved user-facing task hierarchy for the Sarathi Home interface (`Screen 1: Griha`).

---

## Canonical Home Task Hierarchy

The Home screen user-facing processing choices are structured into **Four Primary Tasks** in strict order:

| Parent Task | Second-Level Choice | Mode / Scope | Target Requirement | Target Profile / Custom Options |
| :--- | :--- | :--- | :--- | :--- |
| **1. Documents Extraction** | **Native Extraction** | Direct text & table extraction; auto-converts legacy fonts | `read_native` | `instant` (or `layout_preserving` with Xberg Rust layout analysis) |
| | **Instant OCR** | Speed-optimized single-pass OCR | `ocr` | `instant` |
| | **Accurate OCR** | Multi-pass OCR with weak-crop retry | `ocr` | `accurate` |
| | **Cloud OCR** | Delegated remote OCR (Mistral) | `ocr` (cloud) | `custom` (`provider: mistral`) |
| | **Custom OCR** | Full parameter control (thresholds, angles) | `ocr` | `custom` (`custom_options`) |
| **2. Bank Account Consolidation** | **Instant Consolidation** | Fast single-pass statement reconciliation | `bank_statements` | `instant` |
| | **Accurate Consolidation** | Robust balance verification & deduplication | `bank_statements` | `accurate` |
| **3. Font Conversion** | **Auto-detect to Unicode** | Detects legacy 8-bit fonts $\rightarrow$ Unicode | `font_conversion` | `custom` (`font_mode: auto_unicode`) |
| | **Auto-detect to Devlys** | Transduces Unicode $\rightarrow$ DevLys 010 typewriter | `font_conversion` | `custom` (`font_mode: to_devlys`) |
| | **Auto-detect to Krutidev** | Transduces Unicode $\rightarrow$ Kruti Dev 010 typewriter | `font_conversion` | `custom` (`font_mode: to_krutidev`) |
| **4. Translation** | **Hindi → English** | Krutrim-Translate (4096 Context) neural translation | `translation` | `instant` (or `accurate` with glossaries) |
| | **English → Hindi** | Neural translation with Proper Noun Guard | `translation` | `instant` |
| | **Custom Translation** | Glossary selection, legal domain terminology tuning | `translation` | `custom` |

---

## UI Invariants
1. **Zero Raw Primitives**: Low-level engine names (e.g. `Calamine`, `PyMuPDF`, `RapidOCR`, `CTranslate2`) are encapsulated inside the approved task hierarchy and not presented as disconnected top-level tasks.
2. **Deterministic Fallbacks**: Selecting a capability initiates deterministic, fail-closed execution. No silent downgrade to unrequested cloud services.
