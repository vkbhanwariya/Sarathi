# Sarathi Capabilities

## Capability model

Document work is implemented under `src/sarathi/shakti/`. Providers declare capabilities to Kosh; Manthan resolves a request to compatible capability IDs; Pravaha executes that resolved plan. Capability code owns domain behavior, while shared execution, security, caching, and presentation remain outside the capability.

## Current capability families

### Native extraction

Extracts text/structure directly from formats that expose usable native content. Native extraction should avoid OCR when the requested behavior can be satisfied without raster recognition.

### OCR

Provides local optical character recognition using the configured RapidOCR/OpenVINO stack, with targeted Tesseract support where applicable. OCR-specific preprocessing, engine behavior, page handling, and recognition semantics stay inside the OCR capability. Generic CPU/GPU/resource allocation belongs to Yantra.

### Translation

Provides document/text translation with local and optional provider-backed implementations. Requested profile/language/provider behavior must not silently change when dependencies or credentials are unavailable.

### Font conversion

Converts supported legacy Hindi font encodings to Unicode-oriented output and can participate in DOCX generation. Font-specific mappings live in checked-in data assets; shared typography helpers should be consolidated only when their semantics are genuinely identical across capabilities.

### Bank statements

Locates statement tables, maps headers, normalizes financial values, validates rows, and consolidates supported bank-statement data. Bank-specific mappings live under `data/banks/`.

### Provider adapters

Optional cloud-assisted OCR/translation adapters currently exist for Mistral, Gemini, Azure, and Bhashini. A provider can run only when its declared network/privacy/credential requirements are authorized and its runtime dependencies are ready.

### Supporting document intelligence

Shakti also contains intake identification (`darshana`), shared text/document helpers, artifact naming/export support, and statutory/document-oriented plugin declarations represented by the architecture manifest.

## Capability invariants

- Kosh records declarations; it does not execute capabilities.
- Manthan resolves compatibility and dependencies before execution.
- Pravaha executes the selected plan and does not silently choose a competing route.
- Capability-specific workload behavior stays with the capability.
- Networked providers must pass the real Kavacha policy boundary before outbound transfer.
- Missing dependencies, credentials, models, or unsupported profiles are reported explicitly.
- User-visible output semantics and warning/error behavior are protected by tests.
