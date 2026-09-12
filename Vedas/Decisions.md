# Sarathi Decision Log

This file records product and UI decisions agreed during planning discussions.

## Working Rule

- Do not modify implementation code from planning discussions unless explicitly requested.
- Record only agreed decisions in this file.
- Keep unresolved ideas clearly marked as pending rather than treating them as implementation requirements.

## Home Screen — User-Facing Task Optimization

**Status:** Approved task set and order; second-level tasks approved for Documents Extraction, Bank Account Consolidation, Font Conversion, and Translation; implementation completed

The Home screen user-facing processing choices will be limited to the following four tasks, in this order:

1. **Documents Extraction**
2. **Bank Account Consolidation**
3. **Font Conversion**
4. **Translation**

### Agreed scope

- Optimize only the processing tasks presented to the user.
- Do not redesign Document Intake, Execution Plan, navigation, monitoring, review, summary, or inspector screens as part of this decision.
- Do not expose OCR, statutory/legal extraction, or provider-specific cloud actions as separate top-level Home tasks for now.
- Do not expose Mistral, Gemini, Azure, Bhashini, or other provider-specific implementations as equal top-level tasks.
- Preserve the underlying capabilities unless a later implementation decision explicitly removes or changes them; this decision concerns what the user sees on Home.

### Approved user-facing tasks

1. **Documents Extraction**
2. **Bank Account Consolidation**
3. **Font Conversion**
4. **Translation**

## Documents Extraction — Second-Level Tasks

**Documents Extraction** is a parent task. Selecting it expands the following second-level choices, in this order:

1. **Native Extraction**
   - Automatically extracts native document text/content.
   - Converts embedded Indian legacy Devanagari fonts (KrutiDev, DevLys, Chanakya, Shusha, Shivaji) to standardized Unicode Devanagari by default.
   - User toggle: "Convert Legacy Fonts to Unicode" (`convert_legacy_fonts: bool`, default: `true`).
   - Deep Layout Analysis (GNN): Optional GNN-based reading order and semantic layout analysis (`layout_analysis: bool`, profile: `layout_preserving`) leveraging `pymupdf-layout`. Gracefully falls back to standard PyMuPDF if package is absent.
   - Legal/statutory extraction is performed automatically as part of this path rather than exposed as a separate user-facing task.
   - Backend mapping: `requirement="read_native"`, `profile="instant"` (or `profile="layout_preserving"` when GNN layout analysis is active).

2. **Instant OCR**
   - Super-fast OCR mode.
   - Uses only the minimum essential preprocessing and post-processing required for a fast usable result.
   - Backend mapping: `requirement="ocr"`, `profile="instant"`.

3. **Accurate OCR**
   - Accuracy-focused OCR mode.
   - Uses optimal, accuracy-focused preprocessing and post-processing automatically.
   - Automatically performs selective fallback/reprocessing for OCR output with low confidence instead of applying expensive fallback indiscriminately.
   - Provides an option to preserve the source document's layout and formatting.
   - Backend mapping: `requirement="ocr"`, `profile="accurate"`.

4. **Cloud OCR**
   - Selecting this expands the available cloud OCR providers/options.
   - Cloud providers remain subordinate choices under this task rather than separate Home tasks.
   - Supported cloud providers: Gemini (`gemini_ocr`), Mistral (`mistral_ocr`), Azure (`azure_ocr`), Bhashini (`bhashini_ocr`).

5. **Custom OCR**
   - Exposes the full OCR configuration surface.
   - Allows selection and control of preprocessing and post-processing options.
   - Allows OCR engine selection, including local engines and Cloud OCR options.
   - Backend mapping: `requirement="ocr"`, `profile="custom"`.

## Bank Account Consolidation — Second-Level Tasks

**Bank Account Consolidation** is a parent task. Selecting it expands the following two choices, in this order:

1. **Instant Consolidation**
   - Speed-focused consolidation mode.
   - Uses minimal preprocessing and post-processing.
   - Uses optimal validation suitable for the instant workflow.
   - Backend mapping: `requirement="bank_statements"`, `profile="instant"`.

2. **Accurate Consolidation**
   - Accuracy-focused consolidation mode.
   - Uses optimal preprocessing and post-processing.
   - Uses robust validation for higher-confidence consolidation results.
   - Backend mapping: `requirement="bank_statements"`, `profile="accurate"`.

## Font Conversion — Second-Level Tasks

**Font Conversion** is a parent task. Selecting it expands the following three choices, in this order:

1. **Auto detect to Unicode**
   - Auto-detects non-Unicode Indian font encodings (KrutiDev, DevLys, Chanakya, Shusha, Shivaji) and converts to standardized Unicode Devanagari.
   - Backend mapping: `requirement="font_conversion"`, `custom_options={"font_mode": "auto_unicode"}`.
2. **Auto detect to Devlys**
   - Reverses Unicode Devanagari text into legacy DevLys 010 typewriter encoding using precompiled reverse transducers.
   - Backend mapping: `requirement="font_conversion"`, `custom_options={"font_mode": "to_devlys"}`.
3. **Auto detect to Kurtidev**
   - Reverses Unicode Devanagari text into legacy KrutiDev 010 typewriter encoding using precompiled reverse transducers.
   - Backend mapping: `requirement="font_conversion"`, `custom_options={"font_mode": "to_krutidev"}`.

## Translation — Second-Level Tasks

**Translation** is a parent task. Selecting it first detects the source document language automatically, then presents exactly these six translation-engine choices, in this order:

1. **IndicTrans2**
   - On-device/local translation engine.
   - Backend mapping: `requirement="translation"`, `custom_options={"engine": "indictrans2"}`.

2. **OPUS-MT**
   - On-device/local translation engine.
   - Backend mapping: `requirement="translation"`, `custom_options={"engine": "opus_mt"}`.

3. **Bhashini**
   - Bhashini translation service/engine.
   - Backend mapping: `requirement="bhashini_translation"`.

4. **Mistral**
   - Mistral cloud translation engine.
   - Backend mapping: `requirement="mistral_translation"`.

5. **Gemini**
   - Google Gemini cloud translation engine.
   - Backend mapping: `requirement="gemini_translation"`.

6. **Azure Translator**
   - Microsoft Azure cloud translation engine.
   - Backend mapping: `requirement="azure_translation"`.

- These six are the approved Translation choices for now.
- Sarvam AI Translation is not part of the approved Translation list for now.
- Provider-specific translation engines remain under Translation rather than appearing as separate top-level Home tasks.

### Deferred from the Home task list

The following are not to be presented as separate top-level Home tasks for now:

- Optical Character Recognition (OCR)
- Statutory & Legal Extraction
- Mistral Cloud OCR
- Google Gemini Cloud OCR
- Azure Document Intelligence OCR
- Bhashini Chitrakshar OCR

---

## Technical Mapping & Orchestration Invariants

1. **Thin Mapping Layer**:
   UI task selection maps directly to existing backend contracts: `(requirement, profile, custom_options)`.
2. **Native Extraction $\to$ Statutory Processing**:
   When Native Extraction runs with statutory extraction enabled (default), Pravaha continuation automatically stages `statutory` following `read_native`. `StatutoryCapability` preserves prior `CanonicalDocument` structures.
3. **Font Conversion Reverse Transducers**:
   `FontConverter.convert_to_legacy` provides verified reverse mapping for both `krutidev010` and `devlys010`.
4. **Local Translation Abstraction**:
   Both `indictrans2` and `opus_mt` execute under the canonical `translation` capability through `CTranslate2TranslationEngine`. If weights are missing, execution fails closed with `FailureCode.DEPENDENCY_UNAVAILABLE`.
