# Sarathi · Operational Purpose & Dual-Module Architecture

Sarathi (सारथी) is an offline-first document and financial intelligence platform engineered to eliminate high-frequency document bottlenecks in Indian legal, administrative, and accounting office environments.

---

## Executive Architecture: Dual Operational Modules

Rather than exposing fragmented technical primitives, Sarathi organizes all capabilities into **Two Primary Operational Modules**, backed by **Smart Auto-Detection** and an **Inline Password Unlocker**:

```mermaid
graph TD
    Intake[Document Intake: Drag & Drop] --> AutoDetect{Smart Auto-Detection}
    AutoDetect -->|Court Orders, FIRs, Circulars, Word| M1[Module 1: Documents Studio]
    AutoDetect -->|Bank Statements, Passbooks, Ledgers| M2[Module 2: Bank Statement Analysis]

    subgraph M1_Workflows["Module 1: Documents Studio"]
        W1[1. 📄 Scan to Word (Hindi Unicode / English Translated)]
        W2[2. 🔤 Font Standardizer (Legacy 8-bit to Unicode in Word & Excel)]
        W3[3. 🌐 Document Translation (Hindi ↔ English Word, PDF & Excel)]
        W4[4. 📊 PDF Tables to Excel (Digital & Scanned)]
    end

    subgraph M2_Workflows["Module 2: Bank Statement Analysis"]
        W5[1. 🏦 Statement Consolidation & Arithmetic Reconciler]
        W6[2. 📑 1-Page Executive Audit Memo (.docx / PDF)]
        W7[3. 📈 Cash Flow & Transaction Analytics]
        W8[4. 🔍 Forensic Fraud & PMLA Red-Flag Detection]
    end

    M1 --> M1_Workflows
    M2 --> M2_Workflows
```

---

## Document Ingestion Innovations

### 1. Inline PDF Password Unlocker
- **Problem**: Indian e-bank statements, payslips, and court orders are frequently password-protected (PAN, DOB, account suffix).
- **Behavior**: Locked PDFs display an inline password unlock prompt (`🔑`) directly in the intake inventory table. The operator enters the password once with an optional *"Apply to all in batch"* toggle. Decryption occurs strictly in-memory without saving plaintext credentials to disk.

### 2. Smart Intent Auto-Detection
- **Behavior**: On document drop, lightweight header sniffing classifies files in milliseconds:
  - Banking signatures (HDFC, ICICI, SBI, PNB, passbook grids) $\rightarrow$ Automatically activates **Module 2: Bank Statement Analysis**.
  - Legal notices, orders, petitions, legacy font documents $\rightarrow$ Automatically activates **Module 1: Documents Studio**.
  - Operators can override the auto-detected selection with a single click.

---

## Module 1: Documents Studio (Workflow Matrix)

| Workflow | Inputs | Output | Core Behavior & Safeguards |
| :--- | :--- | :--- | :--- |
| **1. 📄 Scan to Word** | Scanned PDF, Images (`.pdf`, `.png`, `.jpg`) | Microsoft Word (`.docx`) | OpenVINO RapidOCR on Intel Arc iGPU. Preserves geometry, tables, margins, and headings. Sub-modes: *Hindi Unicode* (with typewriter font repair) and *English Translated*. |
| **2. 🔤 Font Standardizer** | Word (`.docx`), Excel (`.xlsx`, `.xls`) | Clean `_Unicode.docx` or `_Unicode.xlsx` | Non-destructive conversion of legacy 8-bit Hindi fonts (Kruti Dev, Devlys, Chanakya, Shusha, Shivaji) to standard Unicode. In Excel, numbers, dates, and formulas (`=SUM(...)`) remain 100% untouched. Supports reverse conversion to Kruti Dev. |
| **3. 🌐 Document Translation** | Word (`.docx`), PDF (`.pdf`), Excel (`.xlsx`, `.csv`) | Translated Word, PDF, or Excel | CTranslate2 neural translation (Krutrim-Translate 4096 Context). Preserves layout, tables, and formulas. Includes *Proper Noun Guard* (protects names via ISO 15919 transliteration) and *Statutory Legal Glossary* (PMLA, IPC, BNS, court titles). |
| **4. 📊 PDF Tables to Excel** | Digital or Scanned PDF | Excel Workbook (`.xlsx`) | Reconstructs borderless and ruled tables with cell alignments intact; auto-converts legacy fonts inside table cells to Unicode. |

---

## Module 2: Bank Statement Analysis (Financial Intelligence Matrix)

| Workflow | Inputs | Output | Core Behavior & Verification Invariants |
| :--- | :--- | :--- | :--- |
| **1. 🏦 Statement Consolidation & Reconciler** | Multi-bank statements (PDF, XLSX, CSV) | Master Consolidated `.xlsx` + Parquet source | Normalizes multi-month statements into canonical columns: `Date`, `Description`, `Ref/UTR`, `Withdrawal (Dr)`, `Deposit (Cr)`, `Balance`. Deduplicates overlapping dates across consecutive files. |
| **2. 📑 1-Page Executive Audit Memo** | Consolidated Statements | Executive Memo (`.docx` / PDF) | Authoritative summary for advocates and auditors: Turnover volumes, Top 5 senders/beneficiaries, high-value cash scrutiny alerts (Section 269ST), and mathematical reconciliation badge. |
| **3. 🔍 Forensic & PMLA Checks** *(Roadmap)* | Consolidated Ledger | Risk Report & Anomaly Ledger | Flags circular/round-trip funds, structuring/smurfing just below statutory cash thresholds (₹50,000 / ₹10,00,000), and sudden velocity spikes. |

### Banking Verification Invariants
- **Double-Entry Arithmetic**: Mathematically verifies: $\text{Opening Balance} + \text{Deposits} - \text{Withdrawals} == \text{Closing Balance}$ per page/statement. Discrepancies generate warning records.
- **UTR & IFSC Auto-Repair**: Heuristically repairs OCR glyph confusions (`0` vs `O`, `1` vs `I`, `8` vs `B`) in 16/22-character UTR numbers and validates 11-character RBI IFSC syntax.

---

## Sovereign & Security Invariants

1. **Air-Gapped & Local-First**: 100% of processing runs locally on loopback `127.0.0.1`. No document or financial data leaves the host machine unless an external cloud AI adapter is explicitly configured.
2. **Primary Hardware Optimized**: Built specifically for Intel Core Ultra 5 125H (14-core CPU) and Intel Arc iGPU (OpenVINO FP16 shader cache), guaranteeing high throughput without external GPU dependencies.
3. **Fail-Closed Privacy**: Path traversal attacks and unauthorized directory access are blocked unconditionally by Kavacha.
