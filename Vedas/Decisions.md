# Sarathi Decision Log

This file records product and UI decisions agreed during planning discussions.

## Working Rule

- Do not modify implementation code from planning discussions unless explicitly requested.
- Record only agreed decisions in this file.
- Keep unresolved ideas clearly marked as pending rather than treating them as implementation requirements.

## Home Screen Simplification

**Status:** Direction approved; detailed layout pending

The current Home screen is considered too cluttered and should be simplified before implementation work is requested.

### Agreed direction

- Reduce visual and decision clutter on the Home screen.
- Do not expose every provider-specific capability as an equal top-level choice.
- Avoid duplicating the same capabilities across dropdowns, tabs, and cards in the default view.
- Keep advanced OCR/provider/settings controls out of the default Home experience unless they are relevant to the selected task.
- No implementation code should be changed until the simplified layout is explicitly approved.

### Current runtime state

The Processing Action UI currently exposes 14 registered actions:

1. Native Document Extraction
2. Optical Character Recognition (OCR)
3. Bank Statement Normalization
4. Statutory & Legal Extraction
5. Legacy Font Conversion
6. Machine Translation
7. Mistral Cloud OCR
8. Mistral Cloud Translation
9. Google Gemini Cloud OCR
10. Google Gemini Cloud Translation
11. Azure Document Intelligence OCR
12. Azure AI Translation
13. Bhashini Chitrakshar OCR
14. Bhashini IndicTrans2 Translation

The same actions are additionally regrouped into Core Local, OCR, Translation, CLOUD, and All tabs. OCR selection can expose multiple technical parameters such as execution profile, model/language, preprocessing, deskew, CLAHE, binarization, Tesseract fallback, and validation.

### Pending decisions

- Final set of primary Home actions.
- Final visual order of those actions.
- Which controls belong under Advanced Settings.
- How cloud providers should be selected.
- Whether the execution-plan preview should remain visible by default.
