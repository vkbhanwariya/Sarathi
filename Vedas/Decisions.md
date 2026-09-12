# Sarathi Decision Log

This file records product and UI decisions agreed during planning discussions.

## Working Rule

- Do not modify implementation code from planning discussions unless explicitly requested.
- Record only agreed decisions in this file.
- Keep unresolved ideas clearly marked as pending rather than treating them as implementation requirements.

## Home Screen — User-Facing Task Optimization

**Status:** Scope approved; final task set and order pending

The current Home screen exposes too many processing choices to the user. Optimization work is limited to the user-facing task choices only.

### Agreed scope

- Optimize only the processing tasks presented to the user.
- Do not redesign Document Intake, Execution Plan, navigation, monitoring, review, summary, or inspector screens as part of this decision.
- Do not change OCR parameters, provider configuration, execution profiles, or other technical controls as part of this decision unless a later decision explicitly includes them.
- Do not expose every provider-specific implementation as an equal user-facing task when several providers perform the same underlying task.
- Prefer clear task-oriented labels over engine/provider-oriented labels.
- No implementation code should be changed until the final user-facing task set and order are explicitly approved.

### Current runtime task choices

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

### Pending decisions

- Final set of user-facing tasks.
- Final wording/labels for those tasks.
- Final order of the tasks.
- Whether any closely related tasks should be grouped under one user-facing choice.
