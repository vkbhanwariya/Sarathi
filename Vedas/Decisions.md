# Sarathi Decision Log

This file records product and UI decisions agreed during planning discussions.

## Working Rule

- Do not modify implementation code from planning discussions unless explicitly requested.
- Record only agreed decisions in this file.
- Keep unresolved ideas clearly marked as pending rather than treating them as implementation requirements.

## Home Screen — User-Facing Task Optimization

**Status:** Approved task set and order; implementation not requested

The Home screen user-facing processing choices will be limited to the following four tasks, in this order:

1. Documents Extraction
2. Bank Account Consolidation
3. Font Conversion
4. Translation

### Agreed scope

- Optimize only the processing tasks presented to the user.
- Do not redesign Document Intake, Execution Plan, navigation, monitoring, review, summary, or inspector screens as part of this decision.
- Do not change OCR parameters, provider configuration, execution profiles, or other technical controls as part of this decision unless a later decision explicitly includes them.
- Do not expose OCR, statutory/legal extraction, or provider-specific cloud actions as separate user-facing Home tasks for now.
- Do not expose Mistral, Gemini, Azure, Bhashini, or other provider-specific implementations as equal top-level tasks.
- Preserve the underlying capabilities unless a later implementation decision explicitly removes or changes them; this decision concerns what the user sees on Home.
- No implementation code should be changed until explicitly requested.

### Approved user-facing tasks

1. **Documents Extraction**
2. **Bank Account Consolidation**
3. **Font Conversion**
4. **Translation**

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
