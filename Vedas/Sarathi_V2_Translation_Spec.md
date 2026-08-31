# Sarathi V2 — Translation Specification

**Specification Updated:** 31-08-2026, 07:32 PM IST (Asia/Kolkata)

Scope: Translation input prerequisites, local Hindi-English models, protected
content, terminology data, reusable approved corrections, dependencies, and
acceptance behavior.

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
