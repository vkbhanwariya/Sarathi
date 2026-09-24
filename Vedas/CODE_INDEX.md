# Sarathi Code & Optimization Index

> **Notice:** Generated automatically by `tools/generate_code_index.py`. Do not edit manually.
> Run `uv run python tools/generate_code_index.py` to regenerate, or `--check` to verify.

This dense index maps every source module in `src/sarathi/` to its primary responsibility, compute/hardware profile, and key exported symbols to enable targeted navigation and optimization without browsing entire trees.

---

## Agni (Composition & Process Lifecycle)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `agni/bootstrap.py` | Agni - application composition root for Sarathi | **Process Lifecycle Orchestrator** | `Agni` |
| `agni/dispatcher.py` | Request execution pipeline, lifecycle boundary containment, and telemetry dispatching | **Process Lifecycle Orchestrator** | `record_terminal_summary()`, `execute_request()` |
| `agni/preflight.py` | Preflight validation of configuration, storage roots, security, and provider consistency | **Process Lifecycle Orchestrator** | `validate_and_resolve_context()`, `validate_and_resolve_settings()`, `resolve_storage_roots()`, `resolve_darpana()`, `resolve_kavacha()` |
| `agni/readiness.py` | Capability and plugin provider readiness audit probe coordination | **Process Lifecycle Orchestrator** | `ReadinessAuditor` |
| `agni/wiring.py` | Construction of Sarathi runtime services | **Process Lifecycle Orchestrator** | `AssembledServices`, `assemble_platform_services()` |

## Sankalpa (Contracts, Artifacts & Data Models)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `sankalpa/artifact.py` | Artifact and Input Contracts for Sarathi | **Pure Data Contracts (Zero I/O)** | `InputRef`, `ArtifactIntent`, `ArtifactPayload`, `ArtifactRef` |
| `sankalpa/cancellation.py` | Cancellation Contracts for Sarathi | **Pure Data Contracts (Zero I/O)** | `CancellationToken`, `check_cancelled()` |
| `sankalpa/capability.py` | Capability Contracts for Sarathi | **Pure Data Contracts (Zero I/O)** | `Capability`, `DeviceType`, `DeviceRequirement`, `CapabilityDeclaration` |
| `sankalpa/context.py` | Context Contracts for Sarathi | **Pure Data Contracts (Zero I/O)** | `ExecutionBinding`, `ExecutionContext` |
| `sankalpa/document.py` | Document Contracts for Sarathi | **Pure Data Contracts (Zero I/O)** | `TextSpan`, `TableData`, `PageData`, `CanonicalDocument`, `normalize_canonical_documents()` |
| `sankalpa/execution_profile.py` | Execution Profile Contracts for Sarathi | **Pure Data Contracts (Zero I/O)** | `ExecutionProfile`, `CustomProfileOptions` |
| `sankalpa/plugin.py` | Plugin Contracts and Security Declarations for Sarathi | **Pure Data Contracts (Zero I/O)** | `SecurityDeclaration`, `PluginInfo`, `PluginServices`, `PluginProvider` |
| `sankalpa/readiness.py` | Capability Readiness Contracts for Sarathi | **Pure Data Contracts (Zero I/O)** | `ReadinessStatus`, `CapabilityReadiness`, `CapabilityReadinessProbe` |
| `sankalpa/request.py` | Request Contracts for Sarathi | **Pure Data Contracts (Zero I/O)** | `Request` |
| `sankalpa/result.py` | Result Contracts for Sarathi | **Pure Data Contracts (Zero I/O)** | `ConfidenceValue`, `ProvenanceRecord`, `WarningRecord`, `Result` |

## Nabhi (Planning, Execution & Artifact Quarantine)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `nabhi/artifacts/atomic_io.py` | Atomic file writing for Nabhi persistence | **Disk I/O (Atomic Staging)** | — |
| `nabhi/artifacts/boundary.py` | Canonical Artifact Boundary for Sarathi | **Disk I/O (Atomic Staging)** | `ArtifactBoundary` |
| `nabhi/artifacts/finalization.py` | Run Workspace Finalization and Failure Cleanup for Sarathi | **Disk I/O (Atomic Staging)** | `cleanup_workspace_on_failure()`, `finalize_run_workspace()` |
| `nabhi/artifacts/manifest.py` | Run manifest schema validation and serialization for the artifact boundary | **Disk I/O (Atomic Staging)** | `serialize_run_manifest()` |
| `nabhi/artifacts/paths.py` | Filesystem path security, boundary containment, and directory validation | **Disk I/O (Atomic Staging)** | — |
| `nabhi/artifacts/promotion.py` | Artifact Promotion, Staging Commits, and Partial Preservation for Sarathi | **Disk I/O (Atomic Staging)** | `resolve_relative_path()`, `normalize_path_key()`, `promote_staged_artifact()`, `promote_direct_artifact()`, `preserve_partial_artifact_file()` |
| `nabhi/artifacts/workspace.py` | Active run workspace providing staging, atomic commit, manifest generation, and cleanup | **Disk I/O (Atomic Staging)** | `RunWorkspace` |
| `nabhi/kosh.py` | Kosh — plugin and capability registry for the Sarathi kernel | **Standard Logic** | `Kosh` |
| `nabhi/manthan.py` | Manthan — Capability Resolver for Nabhi Kernel in Sarathi | **Standard Logic** | `CapabilityPlan`, `Manthan` |
| `nabhi/pravaha/common.py` | Shared hashing, authorization, and telemetry observation helpers for Pravaha | **Standard Logic** | `authorize_capability()`, `compute_input_hash()`, `record_pramana_if_available()`, `quarantine_transition_scope()` |
| `nabhi/pravaha/engine.py` | Canonical Dynamic Pipeline Engine for Nabhi Kernel in Sarathi | **Standard Logic** | `Pravaha` |
| `nabhi/pravaha/lifecycle.py` | Quarantine lifecycle state transitions, operator actions, and retry attempt execution | **Standard Logic** | `execute_retry_attempt()`, `execute_manual_retry()`, `apply_lifecycle_action()` |
| `nabhi/pravaha/pipeline.py` | Core dynamic pipeline plan execution loop, continuation hand-off, and cache coordination | **Standard Logic** | `execute_pipeline()` |
| `nabhi/quarantine.py` | Quarantine and Failure Lifecycle State for Nabhi Kernel in Sarathi | **Standard Logic** | `QuarantineStatus`, `LifecycleActionType`, `LifecycleAction`, `RetryPolicy`, `QuarantineRecord` |

## Shakti (Capabilities & Provider Adapters)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `shakti/artifact_naming.py` | Canonical Artifact Naming utilities for Shakti Capabilities | **Standard Logic** | `sanitize_filename_component()`, `format_artifact_filename()`, `infer_cloud_media_type()`, `resolve_source_input()` |
| `shakti/bank_statements/capability.py` | Bank Statement Consolidation Executable Capability for Sarathi | **In-Memory / Polars Columnar** | `BankStatementCapability` |
| `shakti/bank_statements/consolidator.py` | Consolidator and Canonical Output Exporter for Bank Statements | **In-Memory / Polars Columnar** | `consolidate_statements()`, `build_parquet_artifact()`, `build_xlsx_artifact()` |
| `shakti/bank_statements/converter.py` | Financial Value Converter for Bank Statements in Sarathi | **In-Memory / Polars Columnar** | `parse_decimal_amount()`, `parse_date()`, `parse_time()` |
| `shakti/bank_statements/deduplicator.py` | Deterministic Deduplicator for Bank Statement Transactions | **In-Memory / Polars Columnar** | `DeduplicationResult`, `deduplicate_transactions()` |
| `shakti/bank_statements/detector.py` | Bank Statement and Profile Detector | **In-Memory / Polars Columnar** | `DetectionEvidence`, `load_bank_profiles()`, `detect_bank_statement()` |
| `shakti/bank_statements/mapper.py` | Header Mapper for Bank Statements in Sarathi | **In-Memory / Polars Columnar** | `ColumnMapping`, `HeaderMapper`, `load_bank_profile_yaml()` |
| `shakti/bank_statements/models.py` | Typed Decimal-based Financial Models and Contracts for Bank Statements in Sarathi | **In-Memory / Polars Columnar** | `ValidationStatus`, `DuplicateDecision`, `AccountIdentity`, `ValidationIssue`, `Transaction` |
| `shakti/bank_statements/plugin.py` | Bank Statement Consolidation Plugin Declaration for Sarathi | **In-Memory / Polars Columnar** | `PLUGIN_INFO`, `CAPABILITY_DECLARATION` |
| `shakti/bank_statements/provider.py` | Provider implementation for Bank Statement Consolidation | **In-Memory / Polars Columnar** | `BankStatementsProvider` |
| `shakti/bank_statements/row_classifier.py` | Raw Row Classifier for Bank Statement Tables | **In-Memory / Polars Columnar** | `RowType`, `classify_row()` |
| `shakti/bank_statements/table_locator.py` | Table Locator and Classifier for Bank Statements in Sarathi | **In-Memory / Polars Columnar** | `TableType`, `find_header_row_index()`, `get_table_header_and_data_rows()`, `classify_table()`, `reconstruct_table_from_spans()` |
| `shakti/bank_statements/utr_repair.py` | Banking Identifier Syntax Extraction, OCR Auto-Repair, and Balance Integrity | **In-Memory / Polars Columnar** | `BalanceDiscrepancy`, `is_valid_ifsc()`, `repair_ifsc()`, `repair_utr()`, `verify_mathematical_double_entry_balance()` |
| `shakti/bank_statements/validator.py` | Financial Validator for Bank Statements in Sarathi | **In-Memory / Polars Columnar** | `validate_transaction()`, `validate_statement_balances()` |
| `shakti/cloud/http.py` | Unified pooled HTTP transport for cloud provider capabilities | **Standard Logic** | `RateLimiter`, `CloudHttpClient`, `get_user_agent()`, `redact_text()`, `interruptible_sleep()` |
| `shakti/darshana/capability.py` | Executable Capability for Darshana Intake Identification | **Standard Logic** | `DarshanaCapability` |
| `shakti/darshana/facts.py` | Identification Facts contract for Darshana in Sarathi | **Standard Logic** | `IdentificationFacts` |
| `shakti/darshana/identifier.py` | Darshana — Safe Bounded Content Identification | **Standard Logic** | `identify_file()`, `identify_bytes()`, `identify_input()`, `identify_request()` |
| `shakti/darshana/plugin.py` | Plugin information and capability declaration for Darshana Intake Identification | **Standard Logic** | `PLUGIN_INFO`, `CAPABILITY_DECLARATION` |
| `shakti/darshana/provider.py` | Provider implementation for Darshana Intake Identification | **Standard Logic** | `DarshanaProvider` |
| `shakti/docx_exporter/builder.py` | OpenXML low-level element serialization and full-document DOCX payload packaging | **Standard Logic** | `normalize_docx_text()`, `build_docx_payload()` |
| `shakti/docx_exporter/constants.py` | Constants, namespaces, regex patterns, and typography defaults for OpenXML DOCX export | **Standard Logic** | `sanitize_xml_text()` |
| `shakti/docx_exporter/font_size_normalizer.py` | Pair-aware Visual Font-Size Normalization for DOCX Exporter | **Standard Logic** | `FontSizeAdjustment`, `normalize_font_name()`, `get_font_size_adjustment()`, `normalize_font_size()` |
| `shakti/docx_exporter/scripts.py` | Text script segmentation for bilingual Hindi (Devanagari) and Latin/English documents | **Standard Logic** | `segment_text_by_script()` |
| `shakti/docx_exporter/styles.py` | OpenXML style and docDefaults hierarchy resolution for run font and size properties | **Standard Logic** | `DocxStyleResolver`, `resolve_neutral_ooxml_font()` |
| `shakti/docx_exporter/transformer.py` | In-place OpenXML DOCX document transformation and XML tree processing | **Standard Logic** | `transform_docx_artifact()`, `transform_docx_translation_artifact()`, `normalize_font_family()`, `get_default_profiles()` |
| `shakti/font_conversion/akshara.py` | Akshara-aware Devanagari Syllable Synthesis and Reordering for Roopa | **CPU (Font Engine / TTF)** | `reorder_pre_base_matra_legacy()`, `reorder_reph_unicode()` |
| `shakti/font_conversion/byte_normalizer.py` | Byte normalizer for repairing MacRoman-encoded legacy Devanagari streams | **CPU (Font Engine / TTF)** | `has_macroman_signatures()`, `is_macroman_text()`, `normalize_macroman_bytes()` |
| `shakti/font_conversion/capability.py` | Roopa Font Conversion Executable Capability for Sarathi | **CPU (Font Engine / TTF)** | `FontConversionCapability` |
| `shakti/font_conversion/converter.py` | Akshara-aware Legacy Font to Unicode Converter for Roopa | **CPU (Font Engine / TTF)** | `AnubhavaStore`, `FontConverter` |
| `shakti/font_conversion/detector.py` | Module implementation | **CPU (Font Engine / TTF)** | `LegacyFontDetector`, `extract_ttf_font_family()`, `rank_profiles_from_text()`, `decide_run_profile()` |
| `shakti/font_conversion/font_inspector.py` | Binary Font Inspector using fontTools for Roopa Font Conversion | **CPU (Font Engine / TTF)** | `BinaryFontMetadata`, `compute_cmap_signature()`, `compute_anchor_outline_hashes()`, `inspect_font_bytes()` |
| `shakti/font_conversion/models.py` | Models and Data Structures for Roopa Font Conversion in Sarathi | **CPU (Font Engine / TTF)** | `ProtectedSpan`, `FontEvidence`, `ConversionCandidate`, `ConversionDecision`, `LogicalRun` |
| `shakti/font_conversion/plugin.py` | Plugin declaration for Roopa Font Conversion | **CPU (Font Engine / TTF)** | `PLUGIN_INFO`, `CAPABILITY_DECLARATION` |
| `shakti/font_conversion/protector.py` | Span Protection and Restoration Engine for Roopa Font Conversion | **CPU (Font Engine / TTF)** | `TextProtector` |
| `shakti/font_conversion/provider.py` | Provider implementation for Roopa Font Conversion | **CPU (Font Engine / TTF)** | `FontConversionProvider` |
| `shakti/font_conversion/telemetry.py` | Telemetry recording helpers for FontConversionCapability | **CPU (Font Engine / TTF)** | `emit_conversion_telemetry()` |
| `shakti/font_conversion/validator.py` | Integrity and Devanagari Structural Validator for Roopa Font Conversion | **CPU (Font Engine / TTF)** | `MappingMetrics`, `FontConversionValidator`, `validate_devanagari_structure()`, `validate_residual_legacy()`, `calculate_mapping_coverage()` |
| `shakti/font_conversion/visual_resolver.py` | OpenVINO Visual Font Fallback and Metric Prototype Retrieval for Roopa | **CPU (Font Engine / TTF)** | `VisualFontCandidate`, `VisualFontEvidence`, `VisualFontResolver`, `generate_seed_prototype()`, `serialize_prototypes_bin()` |
| `shakti/mistral/client.py` | Direct REST client for Mistral AI APIs with sanitized error handling and pooled transport | **Standard Logic** | `MistralClient` |
| `shakti/mistral/ocr.py` | Mistral Cloud OCR Capability implementation for Sarathi | **Standard Logic** | `MistralOCRCapability` |
| `shakti/mistral/plugin.py` | Plugin metadata and capability declarations for Shakti Mistral AI | **Standard Logic** | `PLUGIN_INFO`, `MISTRAL_OCR_DECLARATION` |
| `shakti/mistral/provider.py` | Provider implementation for Shakti Mistral AI Plugin | **Standard Logic** | `MistralProvider` |
| `shakti/native_extraction/capability.py` | Shruti - Native Extraction Executable Capability | **Native PDF Vector / PyMuPDF** | `NativeExtractionCapability`, `read_pdf()` |
| `shakti/native_extraction/detector.py` | Actual content format detection for Shruti Native Extraction | **Standard Logic** | `DetectedFormat`, `detect_content_format()` |
| `shakti/native_extraction/legacy_doc.py` | Legacy Word 97-2003 (.doc) to OpenXML (.docx) converter for Windows hosts | **Standard Logic** | `is_word_converter_available()`, `convert_doc_to_docx()` |
| `shakti/native_extraction/plugin.py` | Plugin information and capability declaration for Shruti Native Extraction | **Standard Logic** | `PLUGIN_INFO`, `CAPABILITY_DECLARATION` |
| `shakti/native_extraction/provider.py` | Provider implementation for Shruti Native Extraction | **Standard Logic** | `NativeExtractionProvider` |
| `shakti/native_extraction/readers/common.py` | Shared stage and capability identifiers for native extraction format readers | **Standard Logic** | `STAGE_NAME`, `PLUGIN_ID`, `CAPABILITY_ID` |
| `shakti/native_extraction/readers/delimited.py` | Delimited CSV, TSV, and plain text format reader | **In-Memory / Polars Columnar** | `read_csv_or_text()` |
| `shakti/native_extraction/readers/docx.py` | DOCX OpenXML document reader extracting paragraphs, rich text spans, and tables | **Standard Logic** | `read_docx()` |
| `shakti/native_extraction/readers/html.py` | HTML table and markup reader leveraging BeautifulSoup | **Standard Logic** | `read_html_table()` |
| `shakti/native_extraction/readers/pdf.py` | Native PDF format reader leveraging PyMuPDF | **Native PDF Vector / PyMuPDF** | `read_pdf()` |
| `shakti/native_extraction/readers/pdf_layout.py` | High-performance PDF layout analysis reader leveraging the Xberg Rust engine | **Native PDF Vector / PyMuPDF** | `is_layout_package_available()`, `read_pdf_with_layout()` |
| `shakti/native_extraction/readers/spreadsheet.py` | Spreadsheet format readers supporting modern XLSX/XLSM, legacy binary XLS, and XML Spreadsheet 2003 | **Standard Logic** | `read_xlsx()`, `read_xls_legacy()`, `read_spreadsheet_ml()` |
| `shakti/native_extraction/readers/xberg_reader.py` | High-performance document extraction reader leveraging the pure-Rust Xberg engine | **Standard Logic** | `is_xberg_available()`, `read_document_with_xberg()` |
| `shakti/native_extraction/safe_zip.py` | Safe ZIP Archive and XML Processing Engine for Native Extraction | **Standard Logic** | — |
| `shakti/ocr/capability.py` | Executable Capability for OCR Phase 1 | **Standard Logic** | `OCRCapability` |
| `shakti/ocr/engine/checkpoint.py` | Content-addressed per-page OCR checkpoint cache for atomic resumption and crash recovery | **Primary iGPU (OpenVINO FP16)** | `get_default_checkpoint_dir()`, `compute_doc_hash()`, `compute_params_hash()`, `get_checkpoint_path()`, `serialize_page_data()` |
| `shakti/ocr/engine/common.py` | Shared constants, regexes, and language definitions for the OCR engine | **Primary iGPU (OpenVINO FP16)** | `STAGE_NAME`, `PLUGIN_ID`, `CAPABILITY_ID` |
| `shakti/ocr/engine/coordinator.py` | RapidOCR + OpenVINO engine coordinator for Sarathi | **Primary iGPU (OpenVINO FP16)** | `RapidOCREngine` |
| `shakti/ocr/engine/critical.py` | Consequence-driven Critical Span Detector for OCR verification and retry | **Primary iGPU (OpenVINO FP16)** | `CriticalityType`, `classify_label_anchor()`, `classify_span()`, `repair_critical_token()`, `validate_critical_token()` |
| `shakti/ocr/engine/factory.py` | Verified RapidOCR + OpenVINO Engine Instance Factory for Sarathi | **Primary iGPU (OpenVINO FP16)** | `resolve_engine_keys()`, `build_rapidocr_instance()` |
| `shakti/ocr/engine/layout.py` | Layout and Table Reconstruction Engine for Sarathi OCR | **Primary iGPU (OpenVINO FP16)** | `detect_ruled_tables()`, `detect_borderless_tables()`, `reconstruct_layout()`, `group_paragraphs()`, `detect_column_count()` |
| `shakti/ocr/engine/openvino.py` | OpenVINO environment configuration, device patching, and safe model resolution | **Primary iGPU (OpenVINO FP16)** | `is_safe_filename()`, `disable_openvino_telemetry()`, `get_shared_openvino_core()`, `patch_rapidocr_openvino_device()`, `resolve_target_device()` |
| `shakti/ocr/engine/parser.py` | RapidOCR Output and Geometry Parser for Sarathi | **Primary iGPU (OpenVINO FP16)** | `filter_english_and_numbers()`, `sort_reading_order_xycut()` |
| `shakti/ocr/engine/preprocessing.py` | Image enhancement, orientation correction, and noise reduction for OCR | **Primary iGPU (OpenVINO FP16)** | `StampRegion`, `StampDetection`, `StampDetector`, `RotationCandidate`, `deskew_image()` |
| `shakti/ocr/engine/rasterize.py` | Document page rasterization and image extraction for OCR | **Primary iGPU (OpenVINO FP16)** | `BoundedPageRasterizer`, `resolve_ocr_dpi()`, `get_page_count_from_bytes()`, `extract_single_page_image()`, `iter_images_from_bytes()` |
| `shakti/ocr/engine/readiness.py` | OCR Dependency and Model Preflight Readiness Checker for Sarathi | **Primary iGPU (OpenVINO FP16)** | `verify_ocr_manifest_and_models()`, `check_ocr_readiness()` |
| `shakti/ocr/plugin.py` | Plugin information and capability declaration for OCR | **Standard Logic** | `PLUGIN_INFO`, `CAPABILITY_DECLARATION` |
| `shakti/ocr/provider.py` | Provider implementation for Shakti OCR | **Standard Logic** | `OCRProvider` |
| `shakti/ocr/telemetry.py` | Fine-grained worker performance and page/region quality telemetry for OCR | **Standard Logic** | `record_ocr_page_telemetry()` |
| `shakti/ocr/typography.py` | OCR-specific typography helpers | **Standard Logic** | `infer_line_font_size()` |
| `shakti/providers.py` | Canonical Built-in Plugin Provider Catalog for Sarathi | **Standard Logic** | — |
| `shakti/statutory/capability.py` | Statutory and legal document metadata extraction capability | **Native PDF Vector / PyMuPDF** | `StatutoryCapability` |
| `shakti/statutory/checksums.py` | Checksum and statutory identifier validation algorithms | **Standard Logic** | `verify_pan()`, `verify_tan()`, `calculate_gstin_check_digit()`, `verify_gstin()`, `verify_cin()` |
| `shakti/statutory/detector.py` | Fast heuristic detector for statutory, tax, corporate, and legal documents | **Standard Logic** | `is_statutory_document()` |
| `shakti/statutory/extractor.py` | High-speed statutory and legal entity extractor with OCR error-tolerance | **Standard Logic** | `repair_pan_candidate()`, `repair_gstin_candidate()`, `extract_statutory_entities()` |
| `shakti/statutory/models.py` | Data models for statutory and legal document metadata | **Standard Logic** | `StatutoryDocumentType`, `GSTMetadata`, `IncomeTaxMetadata`, `MCAMetadata`, `ECourtsMetadata` |
| `shakti/statutory/plugin.py` | Statutory and Legal Document Intelligence Plugin Declaration for Sarathi | **Standard Logic** | `PLUGIN_INFO`, `CAPABILITY_DECLARATION` |
| `shakti/statutory/provider.py` | Provider implementation for Statutory & Legal Document Intelligence | **Standard Logic** | `StatutoryProvider` |
| `shakti/text/direction.py` | Shared language direction normalization for Shakti translation capabilities | **Standard Logic** | `NormalizedDirection`, `normalize_translation_direction()` |
| `shakti/text/lazy.py` | Lazy export helper for packages to defer module imports | **Standard Logic** | `lazy_exports()` |
| `shakti/text/legacy_detection.py` | Evidence-based Legacy Font Detection for Shakti | **Standard Logic** | `LegacyFontDetector`, `is_legacy_text()` |
| `shakti/text/legacy_fonts.py` | Canonical legacy font profiles, profile loader, and font name resolver | **Standard Logic** | `LegacyFontProfile`, `load_font_profiles()`, `resolve_profile_from_font_name()` |
| `shakti/text/markdown.py` | Neutral Markdown text extraction helpers for Shakti capabilities | **Standard Logic** | `extract_markdown_tables()` |
| `shakti/text/safe_zip.py` | Safe ZIP Archive and XML Processing Engine | **Standard Logic** | `SafeZipFile`, `safe_fromstring()`, `open_zip_safely()` |
| `shakti/text/span_protection.py` | Span Protection and Restoration Utilities for Shakti | **Standard Logic** | `BaseSpanProtector` |
| `shakti/text/table.py` | Table text processing helpers | **Standard Logic** | `cell_text()` |
| `shakti/text/transliteration.py` | Phonetic Transliteration Transducer from Romanized Hindi (Hinglish) to Unicode Devanagari | **Standard Logic** | `is_romanized_hindi()`, `transliterate_word()`, `transliterate_romanized_hindi()` |
| `shakti/text/typography.py` | Shared output typography primitives for Shakti document capabilities | **Standard Logic** | `is_indic_font()`, `contains_devanagari()`, `synthesize_akshara_unicode()`, `heal_devanagari_matra_spacing()`, `normalize_text_spacing()` |
| `shakti/text/usability.py` | Canonical page and document usability arbitration logic shared across Shakti capabilities | **Standard Logic** | `is_usable_page()`, `is_usable_document()` |
| `shakti/translation/capability.py` | Executable Translation Capability for Sarathi | **Multi-core CPU (Neural AVX2)** | `TranslationCapability` |
| `shakti/translation/court_templates.py` | Standard Indian Court Orders, Statutory Boilerplate, and Section Formulas Matcher | **Standard Logic** | `CourtTemplateMatcher` |
| `shakti/translation/detector.py` | Script and Language Identification for Translation | **Standard Logic** | `LanguageDetector` |
| `shakti/translation/engine.py` | Locked CTranslate2 + Krutrim-Translate + SentencePiece Translation Engine for Sarathi | **Multi-core CPU (Neural AVX2)** | `BackendTranslationResult`, `TranslatorBackend`, `CTranslate2NativeBackend`, `CTranslate2TranslationEngine`, `split_sentences()` |
| `shakti/translation/glossary.py` | Domain Glossary and Terminology Manager for Translation | **Standard Logic** | `GlossaryStore` |
| `shakti/translation/harmonizer.py` | On-Device Statutory Terminology Harmonizer for Sarathi Translation | **Standard Logic** | `GlossaryHarmonizer` |
| `shakti/translation/legal_context.py` | Legal context extraction and judicial translation prompt synthesis for Sarathi | **Standard Logic** | `LegalDocumentContext`, `LegalContextBuilder` |
| `shakti/translation/models.py` | Domain Models and Types for Shakti Translation | **Standard Logic** | `Language`, `TranslationDirection`, `TranslationSpan`, `GlossaryEntry`, `TranslationResult` |
| `shakti/translation/plugin.py` | Plugin declaration for Shakti Translation | **Standard Logic** | `PLUGIN_INFO`, `CAPABILITY_DECLARATION` |
| `shakti/translation/proper_noun_guard.py` | Proper-Noun Legal Transliteration Guard for NMT Translation | **Standard Logic** | `ProperNounGuard`, `transliterate_devanagari_to_latin()` |
| `shakti/translation/protector.py` | Span Protection and Byte-for-Byte Restoration Engine for Translation | **Standard Logic** | `TranslationProtector` |
| `shakti/translation/provider.py` | Provider implementation for Shakti Machine Translation | **Multi-core CPU (Neural AVX2)** | `TranslationProvider` |
| `shakti/translation/validator.py` | Post-Translation Factual-Equivalence and Quality Validator | **Standard Logic** | `extract_factual_tokens()`, `validate_factual_equivalence()` |
| `shakti/translation/xlsx_transformer.py` | In-place Excel (.xlsx) translation transcoder and table workbook builder for Sarathi | **Standard Logic** | `transform_xlsx_translation_artifact()`, `build_xlsx_from_tables()` |

## Yantra (Device Scheduling & Hardware Concurrency)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `yantra/devices.py` | Device inventory contracts for Yantra Resource Manager in Sarathi | **Multi-core CPU (Neural AVX2)** | `DeviceInfo`, `DeviceInventory` |
| `yantra/manager.py` | Yantra - Resource & Execution Manager for Sarathi | **Hardware Scheduling** | `Yantra` |
| `yantra/resources.py` | Resource allocation engine for Yantra in Sarathi | **Hardware Scheduling** | `Allocation`, `MemoryLease`, `MemoryLeaseGuard`, `get_system_memory()` |

## Kavacha (Security Boundaries & Privacy Enforcement)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `kavacha/policy.py` | Security Policy Definitions for Kavacha in Sarathi | **Security / Path Containment** | `SecurityDecision`, `SecurityPolicy` |
| `kavacha/service.py` | Kavacha — Security & Privacy Service for Sarathi | **Security / Path Containment** | `Kavacha` |

## Smriti (Deterministic Result Caching)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `smriti/key.py` | Contract 1: Stable Privacy-Safe Cache Key Computation for Smriti | **In-Memory / Disk Cache** | `CacheKey`, `compute_input_fingerprint()`, `compute_prior_result_digest()`, `compute_cache_key()` |
| `smriti/memory.py` | L1 In-Memory LRU Cache for Smriti | **In-Memory / Disk Cache** | `MemoryCacheEntry`, `MemoryCache` |
| `smriti/policy.py` | Contract 3 & 4: Validity, Invalidation, and Retention Policies | **In-Memory / Disk Cache** | `CachePolicy` |
| `smriti/serialization.py` | Contract 2: Serializable Canonical Result and Artifact Contract | **In-Memory / Disk Cache** | `is_cacheable_result()`, `serialize_result()`, `deserialize_result()` |
| `smriti/store.py` | L2 SQLite Persistent Cache and Unified Smriti Cache Service | **In-Memory / Disk Cache** | `SQLiteCacheStore`, `SmritiCache` |

## Darpana (Operational & Quality Telemetry)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `darpana/history.py` | Retained Safe Terminal Run History for Darpana in Sarathi | **Telemetry Telemetry Event Sink** | `TerminalRunSummary`, `TerminalRunHistoryStore` |
| `darpana/maruti.py` | Maruti - Runtime, Logging & Performance Telemetry for Darpana in Sarathi | **Telemetry Telemetry Event Sink** | `MarutiRecord` |
| `darpana/pramana.py` | Pramana — Confidence & Accuracy Telemetry for Darpana in Sarathi | **Telemetry Telemetry Event Sink** | `AccuracyValue`, `PramanaRecord`, `select_aggregate_confidence_records()` |
| `darpana/service.py` | Darpana - Telemetry & Tracing Service for Sarathi | **Telemetry Telemetry Event Sink** | `Darpana`, `record_maruti()` |

## Sutra (Configuration & Runtime Settings)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `sutra/loader.py` | TOML Configuration Loader for Sutra in Sarathi | **Standard Logic** | `load_settings()` |
| `sutra/settings.py` | Settings Contract for Sutra Configuration in Sarathi | **Standard Logic** | `Settings`, `get_canonical_data_root()`, `get_canonical_models_root()` |

## Mukha (UI, Presentation & Local Loopback Web)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `mukha/intake.py` | Mukha Intake — Canonical Input Discovery, Normalization, and Preflight | **Standard Logic** | `intake_from_paths()` |
| `mukha/presenter.py` | Mukha Presenter - Pure Presentation Logic and State Projection in Sarathi | **Standard Logic** | `MukhaPresenter`, `format_duration_ns()`, `format_bytes()`, `format_confidence()`, `status_badge()` |
| `mukha/state.py` | Typed Presentation State and Models for Mukha in Sarathi | **Standard Logic** | `ProgressKind`, `ProgressState`, `InputGroupView`, `InputItemView`, `InputSelectionView` |
| `mukha/web/app.py` | Starlette transport for the local Mukha web application | **Async Loopback ASGI (HTTP/SSE)** | `LoopbackSecurityMiddleware`, `create_mukha_app()` |
| `mukha/web/comparison.py` | Mukha Historical Run Comparator for Sarathi | **Async Loopback ASGI (HTTP/SSE)** | `compare_runs()` |
| `mukha/web/diagnostics.py` | Privacy-safe Mukha run diagnostics export for Sarathi | **Async Loopback ASGI (HTTP/SSE)** | `export_run_diagnostics()` |
| `mukha/web/native_picker.py` | Native Windows File and Folder Picker for Mukha Web Frontend | **Async Loopback ASGI (HTTP/SSE)** | `NativePickerResult`, `NativePicker` |
| `mukha/web/planner.py` | Mukha execution-plan preview for Sarathi | **Async Loopback ASGI (HTTP/SSE)** | `preview_execution_plan()` |
| `mukha/web/preview.py` | Document preview builder for the interactive Mukha presentation server | **Native PDF Vector / PyMuPDF** | `build_document_preview()`, `render_pdf_page()`, `build_input_preview()`, `build_artifact_preview()` |
| `mukha/web/runner.py` | Mukha Interactive Run Coordinator and Worker Lifecycle for Sarathi | **Async Loopback ASGI (HTTP/SSE)** | `StartRunStatus`, `StartRunResponse`, `ActiveRunSnapshot`, `RunCoordinator` |
| `mukha/web/security.py` | Security, sanitization, and serialization utilities for Mukha web server | **Async Loopback ASGI (HTTP/SSE)** | — |
| `mukha/web/server.py` | Mukha local web presentation façade backed by Starlette and Uvicorn | **Async Loopback ASGI (HTTP/SSE)** | `MukhaWebServer` |
| `mukha/web/state_builder.py` | Mukha Web Presentation State Builder for Sarathi | **Async Loopback ASGI (HTTP/SSE)** | `get_run_telemetry()`, `query_run_history()`, `is_reviewable_warning()`, `get_reviewable_warnings()`, `extract_review_items()` |

## Dosh (Error Taxonomy & Failure Classification)

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `dosh/errors.py` | Dosh — Error System for Sarathi | **Pure Data Contracts (Zero I/O)** | `FailureCode`, `DoshError` |

## Root Application Entry Points

| Component / Module | Responsibility | Compute / Optimization Profile | Key Symbols |
| :--- | :--- | :--- | :--- |
| `__main__.py` | Sarathi CLI and Non-Interactive Runtime Entry Point | **Multi-core CPU (Neural AVX2)** | `main()` |
