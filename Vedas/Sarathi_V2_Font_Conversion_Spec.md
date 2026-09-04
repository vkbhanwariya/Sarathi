# Sarathi V2 — Roopa — Font Conversion Specification

**Specification Updated:** 04-09-2026 (Asia/Kolkata)

Scope: **Roopa — Convert / Font Conversion** canonical ownership, evidence-based detection, profile resolution, precompiled transducers, run-level style hierarchy, run stitching & DOM fidelity, single ConversionPlan truth, structural Devanagari validation, Pramana telemetry, and acceptance criteria.

---

## 1. Canonical Ownership and File Placement

The canonical owner of font conversion in Sarathi V2 is **`src/sarathi/shakti/font_conversion/`**.
No parallel engines, secondary subsystems, or private transducers (such as `plugins/roopa/`) are permitted.

- `models.py`: Canonical dataclasses (`LegacyFontProfile`, `FontEvidence`, `ConversionCandidate`, `ConversionDecision`, `LogicalRun`, `ConversionPlan`, `ConversionMetrics`).
- `akshara.py`: Universal Unicode Devanagari cluster synthesis, prefix matra reordering, and reph positioning invariants.
- `detector.py`: Strict schema validation, trusted profile resolution from font names, candidate scoring from digraphs, ambiguity detection, and `decide_run_profile()`.
- `converter.py`: Precompiled forward and reverse transducer execution, two-tier Anubhava correction (`generic` before profile-specific), and reverse mapping.
- `protector.py`: Protected span detection and byte-for-byte PUA restoration (URLs, emails, Unicode Devanagari, parenthesized Latin phrases, dates, currency, IDs).
- `validator.py`: Mapping coverage calculation (`calculate_mapping_coverage`) and structural Devanagari integrity validation (`validate_devanagari_structure`).
- `capability.py`: Canonical `FontConversionCapability` implementing `Capability` contract with item-scoped batch escalation and telemetry emission.
- `docx_exporter.py`: `DocxStyleResolver` (rPr -> rStyle -> pStyle -> basedOn -> docDefaults), safe run stitching (`_NON_DELETABLE_RUN_CHILDREN`), symbol conversion (`<w:sym>`), and typography preservation.

---

## 2. Evidence-Based Detection and Run Profile Resolution

Font detection is deterministic, multi-tiered, and strictly evidence-driven:
1. **Trusted Font Resolution (`resolve_profile_from_font_name`)**:
   - Exact legacy aliases (e.g. `'Kruti Dev 010'`, `'DevLys 010'`, `'Walkman-Chanakya'`) resolve directly to profile ID and family.
   - Known modern Unicode fonts (e.g. `'Mangal'`, `'Aparajita'`, `'Kokila'`, `'Arial'`, `'Calibri'`, `'Times New Roman'`) resolve to `(None, "modern")` and are preserved without conversion.
2. **Text Evidence Fallback (`rank_profiles_from_text`)**:
   - Scores candidates based on positive signature digraphs (`pos_score = len(pos) * 2.0`), mapping coverage (`cov_score = cov * 5.0`), and negative signatures (`neg_score = len(neg) * 3.0`).
   - Requires `score >= 2.0` and structural validity before authorizing conversion.
3. **Ambiguity Resolution**:
   - If KrutiDev and DevLys tie or have margin `< 1.0` on text alone without font alias or document profile disambiguation, `decide_run_profile` returns `ConversionDecision(decision="ambiguous", reason="conflicting_profile_evidence")`.
4. **Elimination of Document-Profile Leakage**:
   - Run decisions are evaluated locally via `decide_run_profile()`. Document-level hints never force conversion on runs styled with modern Unicode or Latin fonts.

---

## 3. Precompiled Transducers and Anubhava Corrections

1. **Profile Transducers**:
   - Profile forward transducers (`compiled_forward_regex`) and reverse transducers (`compiled_reverse_regex`, `compiled_reverse_map`) are precompiled at profile loading time.
   - Reverse mapping prioritizes `reverse_preferred` mappings declared in profile JSON, and disallows identity fallbacks from overriding legitimate legacy keystrokes.
2. **Anubhava Corrections**:
   - Stored in `data/font_conversion/anubhava.toml`.
   - Executed in two tiers: `[corrections.generic]` applied first, profile-specific (e.g. `[corrections.devlys010]`) applied second.
   - Hardcoded lexical replacements in Python code are prohibited.

---

## 4. OpenXML DOCX Fidelity & Style Resolution

1. **Style Hierarchy Resolution (`DocxStyleResolver`)**:
   - Resolves effective run font by traversing: direct `w:rPr/w:rFonts` $\rightarrow$ character style (`w:rStyle`) $\rightarrow$ paragraph style (`w:pStyle`) $\rightarrow$ parent style (`w:basedOn`) $\rightarrow$ document defaults (`w:docDefaults`).
   - Resolves ASCII text to `w:ascii`/`w:hAnsi` channel and Devanagari text to `w:cs` channel.
2. **Run Stitching & Semantic Node Preservation**:
   - Adjacent compatible runs within paragraphs and hyperlinks are stitched prior to conversion to resolve cross-run split Aksharas (e.g. `'f'` + `'d'` $\rightarrow$ `'fd'` $\rightarrow$ `'कि'`).
   - Runs containing non-deletable child elements (`w:tab`, `w:drawing`, `w:sym`, `w:br`, `w:cr`, `w:fldSimple`, etc.) are never removed from the XML DOM; their text is cleared into the primary run while preserving formatting and layout nodes.
3. **Symbol Conversion (`<w:sym>`)**:
   - Legacy symbols declared in `profile.symbols` (e.g. `F0B5` $\rightarrow$ `µ`, `F0B1` $\rightarrow$ `±`) are transformed into `<w:t>` elements. Modern symbols remain untouched.
4. **Typography Preservation**:
   - When `preserve_typography=True`, original font sizes (`w:sz`), bold (`w:b`), italic (`w:i`), color (`w:color`), and effects are preserved byte-for-byte; only the font name is updated to canonical Devanagari (`Nirmala UI`).

---

## 5. Architectural Invariants and Batch Execution

1. **Single Conversion Truth (`ConversionPlan`)**:
   - The same conversion decisions and offsets govern `CanonicalDocument`, TXT export, and DOCX export.
2. **No Private OCR Oracle**:
   - Private `ocr_oracle` fallbacks are eliminated. Unreadable or empty documents escalate via canonical Pravaha handoff (`next_requirement="ocr"`, `resume_self=True`).
3. **Item-Scoped Batch Escalation**:
   - Escalation to OCR occurs only if **all** documents in a batch are empty.
   - If a batch contains mixed empty and non-empty documents, empty documents are preserved with a classified warning (`EMPTY_DOCUMENT_SKIPPED`), while non-empty documents are converted cleanly.
4. **Strict Source Input Association**:
   - DOCX artifacts are bound strictly by matching `doc.source_input_id == inp.input_id`. Positional array indexing fallback is forbidden.
5. **Devanagari Structural Validation**:
   - Converted text must pass `validate_devanagari_structure()`. Any structural collapse, orphan matra/halant at boundaries, doubled virama, or consecutive conflicting matras raises classified `DoshError(FailureCode.VALIDATION_FAILED)`. No fake success is permitted.
6. **Pramana Telemetry**:
   - Emits structured `ConversionMetrics` in `ProvenanceRecord.evidence` detailing runs scanned, converted, preserved, ambiguous, and mapping coverage.
