# Sarathi V2 — Roopa — Font Conversion Specification

**Specification Updated:** 31-08-2026, 07:32 PM IST (Asia/Kolkata)

Scope: **Roopa — Convert / Font Conversion** detection, protected-span handling,
legacy mapping, Unicode correction, recovery, capability data, dependencies, and
acceptance behavior.

## Purpose

Roopa converts validated legacy Hindi/Devanagari encodings into Unicode without
corrupting Latin text, numbers, dates, identifiers, or punctuation.

## Conversion Flow

``` text
Input
→ detect legacy font / encoding
→ request selective OCR only when protection requires visual evidence
→ protect Latin/English, numbers, dates, IDs and punctuation
→ apply validated legacy mapping
→ Unicode reordering and corrections
→ NFC normalization
→ restore protected spans
→ validate
→ RapidFuzz recovery only where evidence justifies it
→ Unicode result
```

Roopa does not contain an OCR engine. Selective OCR is a capability requirement,
not a private implementation.

## Conversion Modes

Roopa supports directional and legacy-targeted conversion modes via `font_mode` configuration:
- `auto_unicode` (default): Legacy Hindi/Devanagari encodings → standard Unicode Devanagari.
- `to_krutidev`: Standard Unicode Devanagari → legacy KrutiDev 010 encoding.
- `to_devlys`: Standard Unicode Devanagari → legacy DevLys 010 encoding.

Any unsupported `font_mode` is strictly rejected with `VALIDATION_FAILED`. Transformed documents are typed truthfully (`unicode_document` for Unicode targets; `legacy_font_document` for legacy targets).

## Dependencies and Data

``` text
regex
rapidfuzz
stdlib unicodedata
stdlib json
```

No NumPy, Pandas, Torch, Transformers, IndicNLP, or private OCR dependency is
introduced for Roopa.

Validated mapping data is dynamically discovered under `data/fonts/`, including
tested Krutidev, Devlys, Chanakya, and Shusha/Shivaji-family profiles. A mapping
becomes active only after validation and representative regression coverage.

Approved reusable corrections may live in
`data/font_conversion/anubhava.toml`. Every correction is revalidated through
the normal conversion path; runtime never edits the file.

## Acceptance

- unsupported or ambiguous encodings do not trigger destructive conversion;
- protected Latin text, amounts, dates, identifiers, and punctuation round-trip
  unchanged;
- glyph mapping, akshara ordering, Unicode corrections, and NFC output are
  deterministic;
- selective OCR is requested only with evidence;
- RapidFuzz recovery is absent until reproducible failed cases and regression
  tests justify it;
- new mapping profiles remain inactive until validation and regression coverage;
- approved Anubhava corrections cannot bypass normal validation.
