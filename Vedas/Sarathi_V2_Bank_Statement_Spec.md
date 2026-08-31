# Sarathi V2 — Bank Statement Consolidation Specification

**Specification Updated:** 31-08-2026, 06:59 PM IST (Asia/Kolkata)

This file contains the detailed canonical specification for Bank Statement Consolidation.
The main [Sarathi V2 README](../README.md) retains only stable architecture, ownership, and document routing.

## Bank Statement Consolidation

Bank Statement Consolidation is a Phase 1 business capability. It consumes reusable document capabilities and produces a canonical financial dataset; it does not recreate file readers, OCR, security, telemetry, scheduling, or generic pipeline infrastructure.

### Definitive pipeline

``` text
Input documents
→ Darshana — Identify
→ Shruti — Read / Native Extraction
→ actual content / format detection
→ sheets / pages / tables with provenance
→ bank/profile identification
→ account + statement metadata extraction
→ table classification
→ raw-row classification
   transaction / continuation / opening / closing / EOD / summary / repeated header / noise
→ Header Mapping
   bank exact / generic exact / bank fuzzy / generic fuzzy
→ Setu — Map / Normalize
   dates / optional time / description / reference / cheque / dirty amounts / Dr-Cr / balances / currency
→ transaction validation
→ determine source chronology
   Date → Time when available → Source order
→ Running Balance validation
→ Opening / Closing / EOD reconciliation
→ source totals reconciliation
→ account identity grouping
→ overlap detection
→ evidence-based deduplication
→ chronological consolidation
→ final validation
→ Sangam — Consolidate
→ canonical BankStatement dataset
→ Parquet machine store
→ optional XLSX human export
```

Original documents are ingestion/provenance sources. Repeated analysis reads the canonical Parquet dataset rather than reparsing PDF/XLS/XLSX/CSV every time.

### Canonical statement and transaction model

``` text
BankStatement
├── statement_id
├── bank_name
├── bank_code              # optional
├── account_identity
├── account_holder         # optional
├── account_type           # optional
├── branch                 # optional
├── ifsc                   # optional
├── statement_from         # date | None
├── statement_to           # date | None
├── currency
├── opening_balance        # Decimal | None
├── closing_balance        # Decimal | None
├── balance_as_on          # statement-generation balance, if explicit
├── transactions[]
├── daily_balances[]
├── totals
├── validation
└── provenance
```

``` text
Transaction
├── transaction_date
├── transaction_time       # time | None; never fabricated
├── transaction_datetime  # datetime | None
├── posting_datetime      # only if explicitly distinct in source
├── description
├── value_date            # optional
├── reference_number      # optional
├── debit                 # positive Decimal magnitude | None
├── credit                # positive Decimal magnitude | None
├── running_balance       # Decimal | None
├── currency
├── metadata
└── provenance
```

`metadata` may contain `cheque_number`, `transaction_type`, `channel`, `branch`, `is_reversal`, `reversal_reference`, and an `extras{}` bag for genuine bank-specific fields. Canonical schema represents universal financial meaning; bank-specific vocabulary remains profile data.

### Account identity and provenance

``` text
account_identity
├── masked_account_number
├── account_fingerprint
├── account_holder        # optional
├── account_type          # optional
└── bank_code / bank_name
```

Raw account identifiers remain under **Kavacha --- Security & Privacy**. A deterministic fingerprint groups the same account when sufficient evidence exists; weak similarities never force a merge.

Every transaction retains source traceability:

``` text
provenance
├── source_document_id
├── source_file_name
├── source_sheet          # spreadsheet
├── source_page           # PDF
├── source_table
├── source_row
├── bank_profile
├── extraction_method
└── raw values / material repair decisions where relevant
```

A deduplicated transaction may retain multiple source references.

### Header mapping

``` text
Raw headers
→ normalize
→ bank-specific exact alias
→ generic exact synonym
→ bank-specific fuzzy alias
→ generic fuzzy alias
→ ambiguity validation
→ canonical field
```

Exact matches always beat fuzzy matches; bank-profile aliases beat generic aliases. Fuzzy matching is used only for unresolved headers.

Default fuzzy decision bands:

``` text
>= 92      automatic only when canonical meaning is unambiguous
85–91      accept only if best candidate beats second-best by >= 5
< 85       unresolved
```

One source column cannot silently map to two canonical fields, and Debit/Credit ambiguity is never guessed. Mapping metadata records source header, normalized header, canonical field, match type, score where applicable, and profile used.

Generic reusable mappings live in `data/banks/common.yaml`. Bank-specific profiles are added/refined from validated real cases.

### Raw-row classification before normalization

``` text
Raw table row
→ transaction
→ continuation / multiline narration
→ opening balance
→ closing balance
→ EOD balance
→ subtotal / summary
→ repeated header
→ noise / footer
```

Only classified transaction rows enter canonical transaction normalization. Missing date alone does not define a continuation row.

``` text
Missing date + financial values → possible date inheritance → separate transaction
Missing date + narration only   → possible continuation → merge when context proves it
```

Opening, closing, EOD, total, and summary rows remain statement evidence; they are never injected as fake transactions.

### Debit, Credit and amount normalization

A valid canonical transaction requires at least one financial side:

``` text
(debit is not None) OR (credit is not None)
```

Both blank means the row is not a valid canonical transaction. Both populated is an anomaly that must be inspected/reconciled, not silently rewritten.

Canonical Debit and Credit are always positive magnitudes. Direction is represented by the field, not by sign. Source layouts may be:

``` text
Separate Debit / Credit columns
Amount + Dr/Cr indicator
Signed Amount column when the profile explicitly defines signed semantics
```

Examples:

``` text
Amount 1250 + DR → Debit 1250.00, Credit None
Amount 1250 + CR → Credit 1250.00, Debit None
Signed -1250     → Debit 1250.00 only when signed-amount semantics are established
Signed +5000     → Credit 5000.00 only when signed-amount semantics are established
```

Dirty monetary values are normalized conservatively:

``` text
₹50
50Cr / 50Dr
₹1,250.50
1 250.50
(1,250.00)
₹ 50/-
OCR-confused numeric characters such as 1,O00.00 only in numeric context with evidence
```

Ambiguous spacing such as `5 0` is repaired to `50.00` only when numeric-column context, neighboring rows/source pattern, and/or reconciliation provide sufficient evidence. Failed parsing stays unresolved/`None`; it is never silently converted to `0.00`.

All financial arithmetic uses `Decimal` end-to-end. Float is not a canonical financial representation.

### Three distinct balance semantics

``` text
Transaction.running_balance        → balance after a transaction
DailyBalance.eod_balance            → date-level end-of-day balance
BankStatement.balance_as_on         → statement-generation/as-of balance
```

These meanings must never be conflated. If a source says only `Balance` and semantics cannot be established, the system preserves ambiguity rather than guessing.

Every available Running Balance is validated by default:

``` text
current = previous + credit - debit
```

Validation is O(n), sequential within one account, and requires only constant working state beyond issue/provenance recording. Multiple independent statements/accounts may be processed in parallel by **Yantra --- Resource & Execution Manager**.

Missing Running Balance does not invalidate a genuine transaction. Sparse checkpoints can still reconcile cumulative movement. Negative/overdraft balances are valid and are never clamped to zero.

### Reconciliation and inversion detection

Where source semantics exist:

``` text
Opening Balance + Total Credits - Total Debits = Closing Balance
```

Source-provided debit total, credit total, transaction count, opening balance, closing balance, and EOD balances are independently compared with canonical calculations. Missing source totals create no warning by themselves.

Potential Debit/Credit inversion uses multiple signals: bank/profile header meaning, balance continuity, explicit Dr/Cr markers, signed-amount semantics, and neighboring transaction behavior. A global column flip requires consistent multi-row evidence; one strange row is not enough.

### Reversal, refund and foreign-currency handling

A reversal/refund does not change canonical Debit/Credit semantics. A debit reversal is typically represented as a credit and a credit reversal as a debit. `is_reversal` and `reversal_reference` are metadata only when evidence supports that classification; keywords alone do not prove reversal.

For foreign-card/account transactions, canonical Debit/Credit represents the actual account-currency movement. Optional metadata may preserve `foreign_amount`, `foreign_currency`, `exchange_rate`, and `forex_markup`. No FX conversion is invented.

### Multiple tables, sheets and wrong-document protection

**Shruti --- Read / Native Extraction** returns all detected tables/sheets with provenance. The bank capability separately classifies transaction, continuation, metadata, EOD/summary, and unrelated tables. One source may yield multiple `BankStatement` objects when it contains multiple accounts.

**Darshana --- Identify** plus bank-specific evidence must distinguish a bank account statement from credit-card statements, loan schedules, account summaries, interest certificates, FD statements, charges tables, and unrelated documents. Filename/extension is never proof.

### Chronology, overlap and deduplication

Source order is preserved until source chronology is understood. Ordering evidence is:

``` text
transaction_date
→ transaction_time when available
→ original source row order
```

Time is optional extra information: preserve when present, otherwise `None` with no warning or confidence penalty.

Deduplication has only three decisions:

``` text
PROVEN DUPLICATE
PROBABLE DUPLICATE
DISTINCT / NOT PROVEN
```

Signals include account identity, reference/UTR, amount, direction, description, balance transition, overlap, datetime, and source context. Same date + same amount + similar narration alone is insufficient. When evidence is uncertain, retain the transaction rather than silently delete it.

### Validation status

``` text
VALID
WARNING
INVALID
```

`VALID` means canonical financial movement is established and material invariants hold. `WARNING` means usable data with non-fatal uncertainty/reconciliation limitations. `INVALID` means transaction semantics cannot be established, for example unrecoverable monetary value or unresolved contradictory Debit/Credit interpretation.

Optional missing fields such as Time, Cheque No., Reference No., Running Balance, or Account Holder do not automatically create warnings.

### Human and machine outputs

Canonical machine storage:

``` text
Consolidated_Bank_Statement.parquet
```

Parquet is the persistent machine-analysis source because repeated filtering, aggregation, and column selection should not reparse original documents or XLSX. **Viveka --- Analyse** should use Polars lazy scans (`scan_parquet`) and read only required rows/columns where possible.

Human-facing export:

``` text
Consolidated_Bank_Statement.xlsx
```

Primary human table:

``` text
Date
Time                  # optional
Description
Reference No.
Cheque No.
Debit
Credit
Running Balance
Bank
Account Holder Name
Account
Source
```

Presentation formatting is applied only at export/display boundaries:

``` text
Date                 → DD-MM-YYYY
Money                → Indian grouping + 2 decimals, e.g. 1,25,750.50
Blank Debit/Credit   → blank / None, never forced 0.00
```

For large XLSX exports, use a write-optimized path rather than naïve cell-by-cell `openpyxl` loops. Parquet remains the machine source of truth; XLSX is a review/export artifact.

A database is not introduced now. Partitioned Parquet or a database is evaluated only if actual scale demonstrates a need for cross-file indexing, transactional updates, or many-dataset querying.

### Bank profile data

Bank profile data is dynamic rather than README-driven:

``` text
data/banks/
├── common.yaml
└── <bank-profile>.yaml   # discovered/loaded from validated profile data
```

`common.yaml` carries generic English/Hindi aliases, date patterns, footer/header clues, amount-cleanup data, and reusable mapping knowledge. Bank profile files contain only bank-specific identification clues, aliases, date formats, and deviations. Algorithmic logic stays in Python.

### Focused bank tests

``` text
tests/bank_statements/
├── test_mapping.py
├── test_amounts.py
├── test_rows.py
├── test_balances.py
├── test_dedup.py
├── test_identity.py
└── test_end_to_end.py
```

Representative corpus must include true `.xls`, HTML-disguised `.xls`, `.xlsx`, CSV, dirty amounts, combined Amount+Dr/Cr layouts, reverse chronology, multiline narration, missing balance, negative balance, overlapping statements, and multiple sheets/tables.

Not Phase 1: ML bank classifiers, scoring frameworks, rule engines, OLAP dashboards, mapping-learning systems, automatic profile generation, generic financial ontology, or a database-backed transaction store.

------------------------------------------------------------------------
