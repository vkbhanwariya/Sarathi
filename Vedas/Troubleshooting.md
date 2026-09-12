# Troubleshooting

Concise fixes for common operational and runtime issues in Sarathi.

---

## 1. OCR / Tesseract / Model Not Found

### Symptoms
- Capability readiness reports `Unavailable (Required OCR model asset is missing)`.
- Runtime errors indicating missing ONNX weights or missing Tesseract binary.

### Fix
- **Provision RapidOCR ONNX Models**: Run the model provisioning script to verify and download missing models to `data/ocr/models/`:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\Setup-OCRModels.ps1
  ```
- **Tesseract Fallback Setup**: If running accurate OCR with Tesseract fallback, install Tesseract 5:
  ```powershell
  winget install UB-Mannheim.TesseractOCR
  ```
  Ensure `tesseract.exe` is in `PATH` or located at `C:\Program Files\Tesseract-OCR\tesseract.exe`. Verify that English (`eng.traineddata`) and Hindi (`hin.traineddata`) language packs are installed in the `tessdata` folder.

---

## 2. OpenVINO Issues

### Symptoms
- GPU/NPU initialization failure, driver incompatibilities, or OpenCL errors during OCR worker bootstrap.

### Fix
- **Force CPU Execution**: Disable accelerator detection in `config/settings.toml`:
  ```toml
  [hardware]
  detect_accelerators = false
  ```
- **Clear Model Cache**: Corrupted compiled model binaries can cause startup crashes. Delete the cache directory:
  ```powershell
  Remove-Item -Recurse -Force Runtime\Cache\openvino_model_cache
  ```
- **Telemetry Suppression**: OpenVINO telemetry is automatically disabled by Sarathi on import. No manual environment flags are required.

---

## 3. Legacy XLS Detection

### Symptoms
- An `.xls` spreadsheet fails with `XLRDError` or fails format detection.

### Fix
- **Disguised HTML / SpreadsheetML**: Many accounting portals export HTML tables or XML Spreadsheet 2003 files with an `.xls` extension. Sarathi automatically sniffs byte headers to route these correctly. Ensure the file header is not truncated or corrupted.
- **Encrypted Spreadsheets**: `xlrd` does not support password-encrypted Excel sheets. Remove the password in Excel or LibreOffice before ingestion.
- **Corrupted Legacy Workbooks**: If a legacy BIFF8 file is corrupted, open and re-save it as standard `.xlsx` before processing.

---

## 4. Encoding Problems

### Symptoms
- Text appears with replacement characters (``) or garbled ASCII characters in output artifacts.

### Fix
- **Check Warnings**: Inspect the `warnings` array in the result payload for `UnicodeDecodeError` or fallback notices.
- **Normalize File Encoding**: Sarathi automatically sniffs encodings via `charset-normalizer`. If an input file has mixed encodings or unsupported legacy codepages, convert it to clean UTF-8 before processing:
  ```powershell
  Get-Content -Path "input.csv" | Out-File -Encoding utf8 "clean_input.csv"
  ```
- **Verify File Completeness**: Ensure the file was not partially downloaded or truncated during transfer.

---

## 5. Legacy-Font Detection

### Symptoms
- Text written in Kruti Dev, Devlys, or Chanakya remains in unreadable ASCII glyphs instead of converting to Hindi Unicode.

### Fix
- **Signature Density**: Automatic text-signature detection requires at least 2 distinct character signatures in the text segment. Very short snippets (<10 characters) may not have sufficient evidence for safe automatic detection.
- **Font Table Metadata**: In DOCX files, ensure font family names (e.g. `Kruti Dev 010`, `Devlys 010`) are preserved in run formatting. Sarathi reads TrueType SFNT font tables directly.
- **Supported Encodings**: Ensure the legacy font is one of the supported families: Kruti Dev, Devlys, Chanakya, Shusha, or Shivaji.

---

## 6. Frontend Build / Assets

### Symptoms
- Navigating to `http://127.0.0.1:8000/` returns `404 Not Found` or missing UI bundles.

### Fix
- **Compile Frontend Assets**: The single-page application must be compiled to `src/sarathi/mukha/web/ui/`:
  ```powershell
  cd ui
  npm ci
  npm run build
  cd ..
  ```
- **Verify Output**: Ensure `src/sarathi/mukha/web/ui/index.html` and `src/sarathi/mukha/web/ui/assets/` exist.
- **Node Requirement**: Node.js >= 20 is required (Node 24 LTS recommended).

---

## 7. Local Port Conflicts

### Symptoms
- Server fails to start with `[Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000)`.

### Fix
- **Identify and Stop Conflicting Process**: Find the process listening on port 8000 and stop it:
  ```powershell
  Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object OwningProcess
  Stop-Process -Id <PID>
  ```
- **Single Process Guarantee**: Ensure no zombie instances of `uvicorn` or `python` are running in the background.

---

## 8. Cloud Credential / Configuration Errors

### Symptoms
- Pipeline fails with `DoshError: SECURITY_VIOLATION` when invoking a cloud provider.
- Readiness checks report `Dependency unavailable: API key not configured`.

### Fix
- **Authorize Cloud Access in Security Policy**: In `config/settings.toml`, ensure network and external processing are authorized:
  ```toml
  [security]
  allow_network_access = true
  allow_external_processing = true
  allowed_secrets = [
      "AZURE_API_KEY",
      "AZURE_ENDPOINT",
      "BHASHINI_API_KEY",
      "BHASHINI_INFERENCE_KEY",
      "BHASHINI_USER_ID",
      "GEMINI_API_KEY",
      "MISTRAL_API_KEY",
  ]
  ```
- **Export Environment Variables**: Set the required secret in your environment before starting Sarathi:
  ```powershell
  $env:MISTRAL_API_KEY = "your-key-here"
  $env:GEMINI_API_KEY = "your-key-here"
  ```
- **Alternative Config**: Alternatively, configure keys directly in the respective provider section of `config/settings.toml`.
