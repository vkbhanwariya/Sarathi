# Sarathi Decision Log

This file records product and UI decisions agreed during planning discussions.

## Working Rule

- Do not modify implementation code from planning discussions unless explicitly requested.
- Record only agreed decisions in this file.
- Keep unresolved ideas clearly marked as pending rather than treating them as implementation requirements.

## Home Screen — User-Facing Task Optimization

**Status:** Approved task set and order; Documents Extraction and Bank Account Consolidation second-level tasks approved; implementation not requested

The Home screen user-facing processing choices will be limited to the following four tasks, in this order:

1. Documents Extraction
2. Bank Account Consolidation
3. Font Conversion
4. Translation

### Agreed scope

- Optimize only the processing tasks presented to the user.
- Do not redesign Document Intake, Execution Plan, navigation, monitoring, review, summary, or inspector screens as part of this decision.
- Do not expose OCR, statutory/legal extraction, or provider-specific cloud actions as separate top-level Home tasks for now.
- Do not expose Mistral, Gemini, Azure, Bhashini, or other provider-specific implementations as equal top-level tasks.
- Preserve the underlying capabilities unless a later implementation decision explicitly removes or changes them; this decision concerns what the user sees on Home.
- No implementation code should be changed until explicitly requested.

### Approved user-facing tasks

1. **Documents Extraction**
2. **Bank Account Consolidation**
3. **Font Conversion**
4. **Translation**

## Documents Extraction — Second-Level Tasks

**Documents Extraction** is a parent task. Selecting it expands the following second-level choices, in this order:

1. **Native Extraction**
   - Automatically extracts native document text/content.
   - Legal/statutory extraction is performed automatically as part of this path rather than exposed as a separate user-facing task.

2. **Instant OCR**
   - Super-fast OCR mode.
   - Uses only the minimum essential preprocessing and post-processing required for a fast usable result.

3. **Accurate OCR**
   - Accuracy-focused OCR mode.
   - Uses optimal preprocessing and post-processing automatically.
   - Automatically performs selective fallback/reprocessing for OCR output with low confidence instead of applying expensive fallback indiscriminately.

4. **Cloud OCR**
   - Selecting this expands the available cloud OCR providers/options.
   - Cloud providers remain subordinate choices under this task rather than separate Home tasks.

5. **Custom OCR**
   - Exposes the full OCR configuration surface.
   - Allows selection and control of preprocessing and post-processing options.
   - Allows OCR engine selection, including local engines and Cloud OCR options.

## Bank Account Consolidation — Second-Level Tasks

**Bank Account Consolidation** is a parent task. Selecting it expands the following two choices, in this order:

1. **Instant Consolidation**
   - Speed-focused consolidation mode.
   - Uses minimal preprocessing and post-processing.
   - Uses optimal validation suitable for the instant workflow.

2. **Accurate Consolidation**
   - Accuracy-focused consolidation mode.
   - Uses optimal preprocessing and post-processing.
   - Uses robust validation for higher-confidence consolidation results.

### Deferred from the Home task list

The following are not to be presented as separate top-level Home tasks for now:

- Optical Character Recognition (OCR)
- Statutory & Legal Extraction
- Mistral Cloud OCR
- Mistral Cloud Translation
- Google Gemini Cloud OCR
- Google Gemini Cloud Translation
- Azure Document Intelligence OCR
- Azure AI Translation
- Bhashini Chitrakshar OCR
- Bhashini IndicTrans2 Translation
