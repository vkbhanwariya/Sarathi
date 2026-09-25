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

---

## Architectural Decisions (ADRs)

### ADR-001: Indian Bank Statement Currency & Forex Narration Isolation
- **Context**: Sarathi is purpose-built for Indian document processing. All bank statements processed originate from Indian financial institutions (SBI, HDFC, ICICI, Axis, PNB, etc.). Indian bank accounts record all ledger entries (debit, credit, running balance) in Indian Rupee (`INR`). International card/POS or e-commerce purchases frequently include foreign currency amounts and exchange rates in the transaction narration (e.g. `POS 401284XXXXXX0001 STEAM GAMES SEATTLE WA USD 14.99 @ 84.50`).
- **Decision**: Statement currency strictly defaults to `INR`. Loose currency symbols (`$`, `€`, `£`, etc.) or currency codes found within unstructured document text or transaction descriptions are treated strictly as descriptive narrative text and MUST NEVER override the statement currency or alter column values. Statement currency may only be overridden by explicit profile configuration or labeled statement headers (e.g., `Currency: USD`).
- **Consequences**: Eliminates false currency switching, avoids overengineering multi-currency table mappers, and preserves exact double-entry arithmetic across statements.

### ADR-002: IFSC 4-Letter Prefix Binding for Cross-Bank Account Identity
- **Context**: When bank profile detection falls back to generic profiles or when statements across different banks share identical trailing masked digits (e.g. `...1234`), cross-document deduplication risks conflating different customer accounts from different banks into a single entity.
- **Decision**: The 4-letter RBI IFSC prefix (`clean_ifsc[:4]`, representing the institution, e.g. `SBIN`, `HDFC`, `ICIC`, `PUNB`) is incorporated into `AccountIdentity` and factored into `account_fingerprint`. Furthermore, cross-statement deduplication strictly isolates statements under generic detection unless verified institution identity (matching IFSC prefix) exists.
- **Consequences**: Guarantees statements from different institutions are never cross-deduplicated or conflated, even under generic profile fallbacks.

### ADR-003: Pure Content-Streaming File Fingerprints
- **Context**: Intake file fingerprinting previously incorporated `path.name` and sampled 32 KB blocks, which caused renamed identical files to produce different IDs and created a 32–64 KB sampling blind spot.
- **Decision**: `mukha.intake._compute_file_fingerprint` streams the entire file in 64 KB chunks without incorporating `path.name`. Document fingerprints in `shakti.bank_statements` similarly hash all page text, full document text, table headers, and all table rows.
- **Consequences**: Pure content-addressable document IDs invariant to renaming, eliminating false duplicate or false mutation errors.
