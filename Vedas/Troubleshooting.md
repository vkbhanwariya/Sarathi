# Sarathi Troubleshooting

Quick diagnostic checklist and actionable recovery commands for common runtime issues.

---

## Diagnostic & Recovery Matrix

| Area | Observed Symptom | Root Cause | Actionable Fix / Recovery Command |
| :--- | :--- | :--- | :--- |
| **OCR Models** | `Required OCR model asset is missing` | Missing ONNX weights in `data/ocr/models/` | Run model provisioner: `powershell -ExecutionPolicy Bypass -File tools\scripts\Setup-OCRModels.ps1` |
| **OpenVINO / GPU** | GPU initialization failure or OpenCL crash | Corrupted shader cache or driver mismatch | Clear cache: `Remove-Item -Recurse -Force Runtime\Cache\openvino_model_cache`<br>Or force CPU in `config/settings.toml`: `detect_accelerators = false` |
| **Translation** | `Missing model asset` or SentencePiece error | Unprovisioned CTranslate2 weights | Run translation provisioner: `powershell -ExecutionPolicy Bypass -File tools\scripts\Setup-TranslationModels.ps1 -Engine krutrim` |
| **Legacy XLS** | `XLRDError` on `.xls` file | Disguised HTML table or XML SpreadsheetML | Sarathi auto-sniffs and routes disguised files. If corrupted, re-save as clean `.xlsx` in Excel. |
| **Font Detection** | Kruti Dev / Devlys text not converted | Snippet too short (<10 chars) or missing signatures | Auto-detection requires $\ge 2$ distinct bigram signatures. For short snippets, use explicit font mode (`font_mode: auto_unicode`). |
| **Encoding / Garbled Text** | Output contains replacement characters (``) | Non-UTF8 legacy encoding | Convert source file to UTF-8: `Get-Content input.csv \| Out-File -Encoding utf8 clean.csv` |
| **Port Conflict** | Server fails to bind to loopback port | Port 8000 in use | Let Sarathi auto-assign an ephemeral port (pass `port = 0`) or change port via CLI: `sarathi --port 8080` |
| **Frontend UI** | `404 Not Found` accessing `127.0.0.1:8000` | Compiled web assets missing in `src/sarathi/mukha/web/ui/` | Rebuild frontend SPA: `cd ui; npm ci; npm run build; cd ..` |
| **Bank Statements** | Non-zero `Reconciliation Diff` in `Statements` sheet | Opening + Credits - Debits $\neq$ Closing balance | Open the `Exceptions` sheet in `Consolidated_Bank_Statement.xlsx` to review flagged rows, missing boundary balances, or unmapped reversal entries. |
| **Cheque vs Reference**| Cheque number populated into Reference No. | Alias collision in bank profile | Isolate cheque headers strictly to `cheque_number:` and transaction/UTR tokens to `reference_number:` in the profile YAML. |
| **PDF Subprocesses** | Subprocess error on huge vector PDF | Process pool worker error or system memory ceiling | The engine automatically catches subprocess exceptions and falls back transparently to serial in-process extraction. |
| **Cloud Egress** | `403 Forbidden` / Security Denied on cloud OCR | `[security]` policy blocks outbound network | In `config/settings.toml`, set `allow_network_access = true` and configure `allowed_secrets = ["MISTRAL_API_KEY"]`. |

---

## Recovery Verification
After applying fixes, verify environment health with the fast pre-commit check:
```powershell
uv run python -m compileall -q src tests tools; uv run ruff check .; uv run python tools/generate_code_index.py --check
```
