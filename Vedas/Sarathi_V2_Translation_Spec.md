# Sarathi V2 — Translation Specification

**Specification Updated:** 06-09-2026, 07:30 PM IST (Asia/Kolkata)

Scope: Translation canonical ownership, input prerequisites, local Hindi-English models, protected
content, terminology data, reusable approved corrections, dependencies, and
acceptance behavior.

## Canonical Ownership and File Placement

The canonical owner of translation in Sarathi V2 is **`src/sarathi/shakti/translation/`**.
No parallel engines or secondary translation subsystems are permitted.

- `models.py`: Typed translation request, segment, and result dataclasses.
- `capability.py`: Canonical `TranslationCapability` implementing `Capability` contract with batch execution, sentence translation coordination, and pipeline continuation.
- `provider.py`: Canonical `TranslationProvider` constructing executable capability, canonical Yantra device binding, and lightweight model readiness probes.
- `engine.py`: IndicTrans2 distilled 200M + CTranslate2 inference engine with dynamic VRAM batching based on Yantra hardware inventory.
- `detector.py`: Source language detection and Unicode script validation.
- `protector.py`: Protected span detection and placeholder restoration for legal terms, citations (CrPC, IPC, BNS), numbers, dates, and amounts.
- `glossary.py`: Static terminology dictionary loading and glossary replacement.
- `typography.py`: Capability-local typography helpers mapping translated text to standard 12 pt baseline (`Nirmala UI` for Hindi / `Times New Roman` for English).
- `plugin.py`: Plugin registration and capability declaration metadata.

## Input Boundary

Translation accepts normalized Unicode text. Legacy Hindi/Devanagari input must
first return a **Roopa — Convert / Font Conversion** requirement.

## Locked Local Hindi ↔ English Path

``` text
Hindi → English  → IndicTrans2 distilled 200M + CTranslate2
English → Hindi  → IndicTrans2 distilled 200M + CTranslate2
```

Initial models:

``` text
ai4bharat/indictrans2-indic-en-dist-200M
ai4bharat/indictrans2-en-indic-dist-200M
```

Initial runtime dependencies:

``` text
ctranslate2
sentencepiece
regex
```

Torch, Transformers, Fairseq, Pandas, NLTK, and Sacremoses are not initial
runtime dependencies. OpenVINO translation remains a future benchmark candidate,
not a parallel initial path.

## Translation Flow

``` text
Normalized Unicode input
→ language detection
→ protect legal terms, IDs, numbers, dates, amounts and references
→ sentence-aware translation
→ restore protected content
→ validate
→ return translated result or explicit escalation requirement
```

Translation never silently rewrites factual identifiers.

Static terminology and glossaries live under `data/translation/`. Approved
reusable translation or legal corrections may live in
`data/translation/anubhava.toml`; unapproved runtime candidates never enter the
active path and runtime never edits the file.

## Typography and Output Formatting

- Capability-local typography helper lives in `src/sarathi/shakti/translation/typography.py`.
- Target font family: `Times New Roman` for English-only translated output; `Nirmala UI` for Hindi or mixed Devanagari output.
- Font size: Preserves source logical font size and heading hierarchy (`normalize_size`), falling back to standard 12 pt baseline.
- Preserves pure Unicode boundary: does not own legacy font conversions, calibration tables, or OpenXML serialization.

## Acceptance

- non-Unicode legacy input returns an explicit conversion requirement;
- Hindi→English and English→Hindi use their fixed local model directions;
- legal terms, identifiers, numbers, dates, amounts, and references survive
  protect/restore unchanged;
- sentence boundaries and factual meaning are regression-tested;
- terminology and approved corrections cannot bypass validation;
- unsupported or unresolved input produces an explicit warning/failure or
  escalation requirement rather than invented output;
- external translation is never invoked implicitly.
