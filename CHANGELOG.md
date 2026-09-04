# Changelog

All notable changes to Sarathi are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-09-04

### Added
- **Security & Kavacha**:
  - Strict loopback and host validation in Mukha web interface.
  - Mandatory security headers (`Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
  - Kavacha outbound network access policy enforcement.
- **Yantra Execution Binding**:
  - Concrete `backend_locators` on `DeviceInfo` for multi-GPU identification (`GPU.0`, `GPU.1`, `cuda:0`, `cuda:1`).
  - Strict execution binding propagation to translation and OCR backends without `TypeError` fallbacks.
- **Composition Root Dependency Injection**:
  - Topological bootstrap order in `Agni.bootstrap()`: `Settings` $\rightarrow$ `Darpana` $\rightarrow$ `Kavacha` $\rightarrow$ `Inventory/Yantra` $\rightarrow$ `Capabilities` $\rightarrow$ `Kosh/Dvara` $\rightarrow$ `Pravaha`.
  - Injected dependencies via standard constructors, eliminating post-construction private attribute mutation (`_yantra`).
- **Telemetry & Cancellation (Darpana & Pravaha)**:
  - Added `FailureCode.OPERATION_CANCELLED` and `"cancelled"` outcome recording in Darpana.
  - Pravaha immediate bypass of retry loops and quarantine storage on user cancellation.
  - Buffer capacity configuration for Darpana live telemetry buffers via Sutra settings.
- **Artifact Naming Disambiguation**:
  - Deterministic artifact filename generation avoiding collisions across multi-document batches.
- **Bank Statement Financial Correctness**:
  - Continuous monotonic sequence ID indexing across multi-page/multi-table parses.
  - Strong-signal deduplication with contradiction detection per Bank Statement Veda.
- **Smriti Two-Tier Cache Integrity**:
  - Framed length-delimited input fingerprinting preventing boundary collisions (`["ab", "c"]` $\neq$ `["a", "bc"]`).
  - Deterministic set sorting in digest computations.
  - Multi-document envelope serialization and deserialization support.
  - Typed cache configuration accessors in Sutra settings.
- **Font Conversion & Mixed-Font DOCX Fidelity**:
  - Consolidated Roopa font-conversion engine preserving document structure, formatting, and run stitching across mixed KrutiDev, DevLys, and Unicode Hindi text.
