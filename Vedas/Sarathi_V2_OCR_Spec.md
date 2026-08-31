# Sarathi V2 — OCR — Optical Character Recognition Specification

**Specification Updated:** 31-08-2026, 07:32 PM IST (Asia/Kolkata)

Scope: OCR engines, processing profiles, preprocessing, fallback, page-level
output evidence, dependencies, capability data, and acceptance behavior.

## Engine Direction

``` text
Primary local OCR
    RapidOCR + PP-OCRv5 + OpenVINO
        ↓ weak page / region or unsupported case
Targeted local fallback
    Tesseract 5
        ↓ unresolved and external OCR is permitted
Last-resort external OCR request
```

External OCR is only an escalation request; OCR does not authorize external
processing. ONNX Runtime and additional OCR frameworks remain deferred until
representative benchmarks prove a capability gap.

## Processing Profiles

There is no Auto mode or automatic engine-selection layer.

1. **Instant** — fastest useful OCR with minimum beneficial preprocessing and
   one fixed tested primary engine path.
2. **Accurate** — validation plus targeted fallback only for weak
   pages/regions/lines; consensus exists only after reproducible corpus evidence.
3. **Layout Preserving** — fixed tested pipeline that returns text with useful
   region, table, and position information.
4. **Custom** — user selects an installed, tested OCR engine and a compatible
   processing profile/options combination.

Each standard profile fixes its engine, model, preprocessing, validation, and
fallback path after representative testing. Custom combinations are explicitly
validated; invalid combinations are rejected with a reason.

## Profile Behavior

### Instant

- orientation check;
- resize only when required;
- grayscale only when beneficial;
- single RapidOCR + PP-OCRv5 + OpenVINO pass;
- punctuation, numbers, and line order preserved;
- Unicode NFC normalization;
- weak output is reported without silently invoking fallback.

### Accurate

- adaptive preprocessing where evidence supports it;
- primary pass followed by validation;
- targeted Tesseract fallback only on weak units;
- consensus only when tested disagreement resolution improves failed cases
  without degrading valid cases.

### Layout Preserving

- region and reading-order retention;
- table/position evidence where supported;
- engine binding fixed only after layout-corpus testing.

### Custom

- tested engine selection;
- tested processing profile/options selection;
- compatibility validation before execution.

## Page-level Output

Each page/pass returns factual capability output:

- page and attempt identity;
- text plus regions/coordinates when requested and supported;
- selected profile, engine, model, and backend identity;
- measured confidence components and validation outcome;
- warnings, fallback reason, and terminal page outcome;
- no default confidence, assumed accuracy, or fabricated metric.

Confidence is not accuracy. Verified accuracy requires a named metric,
reference corpus, and sample count.

## Dependencies and Data

``` text
RapidOCR + PP-OCRv5
OpenVINO
Tesseract 5
Pillow / OpenCV Headless only when preprocessing requires them
```

Tested profiles and calibration assets live under `data/ocr/`. Approved
reusable OCR knowledge may live in `data/ocr/anubhava.toml`; runtime never
auto-promotes candidates into that file.

## Acceptance

- every standard profile resolves to one fixed tested engine path;
- Custom rejects unavailable or incompatible combinations;
- Instant never triggers hidden consensus or fallback;
- Accurate fallback is targeted and evidence-driven;
- Layout Preserving retains tested region/table/position semantics;
- page/pass identity and confidence evidence remain correlated;
- failed, cancelled, retried, and fallback pages retain factual outcomes;
- output contains no fabricated confidence, accuracy, speed, or success values.
