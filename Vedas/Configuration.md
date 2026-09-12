# Sarathi Configuration

Sarathi configuration is managed by the **Sutra** subsystem. Configuration is read from an explicit TOML file (default: `config/settings.toml`) into immutable, typed `Settings`.

---

## Configuration Sections

### `[storage]`

Configures filesystem boundaries for data ingestion, staging, and artifact storage.

| Key | Type | Code Default | Config Default | Description |
| --- | --- | --- | --- | --- |
| `input_root` | `Path` | `"Input"` | `"Input"` | Root directory containing input documents. |
| `output_root` | `Path` | `"Output"` | `"Output"` | Root directory for validated, committed output artifacts. |
| `runtime_root` | `Path` | `"Runtime"` | `"Runtime"` | Directory for scratch workspaces, staging, and temp files. |

---

### `[pipeline]`

Controls execution workflow behavior.

| Key | Type | Code Default | Config Default | Description |
| --- | --- | --- | --- | --- |
| `max_retries` | `int` | `0` | `0` | Maximum automated retry attempts for transient pipeline execution failures. |

---

### `[security]`

Defines Kavacha authorization rules and network boundaries.

> [!IMPORTANT]
> Settings that enable external or cloud processing are marked with **(Enables External/Cloud)**.

| Key | Type | Code Default | Config Default | Description |
| --- | --- | --- | --- | --- |
| `allow_pii_access` | `bool` | `true` | `true` | Permits capabilities to access Personally Identifiable Information. |
| `allow_network_access` | `bool` | `false` | `true` | **(Enables External/Cloud)** Permits outbound network socket and HTTP communication. |
| `allow_external_processing` | `bool` | `false` | `true` | **(Enables External/Cloud)** Permits transmitting document data to third-party cloud APIs. |
| `allowed_secrets` | `list[str]` | `()` | See below | List of environment variable names containing secrets that Kavacha authorizes capabilities to access. |

Default `allowed_secrets` in `config/settings.toml`:
```toml
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

---

### `[telemetry]`

Configures Darpana execution and quality telemetry.

| Key | Type | Code Default | Config Default | Description |
| --- | --- | --- | --- | --- |
| `history_enabled` | `bool` | `false` | `false` | Enables persistent disk storage of terminal run records. |
| `history_path` | `Path \| None` | `None` | `"history.jsonl"` | File path where terminal run history is stored. |
| `history_format` | `str` | `"jsonl"` | `"jsonl"` | Format for stored history (`"jsonl"` or `"sqlite"`). |
| `live_buffer_capacity` | `int` | `1000` | `256` | Maximum number of in-memory live telemetry records retained. |
| `history_max_records` | `int` | `1000` | `1000` | Maximum historical records retained in queries. |

---

### `[hardware]`

Configures Yantra hardware resource detection and execution concurrency.

| Key | Type | Code Default | Config Default | Description |
| --- | --- | --- | --- | --- |
| `detect_accelerators` | `bool` | `false` | `true` | Enables OpenVINO probing for local GPU and NPU devices. |
| `gpu_capacity_per_device` | `int` | `4` | `4` | Scheduler concurrency slot budget allocated per GPU. |
| `npu_capacity_per_device` | `int` | `2` | `2` | Scheduler concurrency slot budget allocated per NPU. |
| `max_queue_depth` | `int` | `64` | `64` | Maximum pending subtask queue depth for accelerator dispatch. |

---

### `[cache]`

Configures Smriti deterministic result caching.

| Key | Type | Code Default | Config Default | Description |
| --- | --- | --- | --- | --- |
| `enabled` | `bool` | `true` | `true` | Enables result caching across requests. |
| `dir` | `Path \| None` | `None` | `None` | Directory path for persistent L2 cache (memory-only if `None`). |
| `ttl_seconds` | `int \| None` | `86400` | `86400` | Cache time-to-live in seconds (24 hours; `None` disables expiry). |
| `max_entries_l1` | `int` | `200` | `200` | In-memory L1 cache capacity. |
| `max_entries_l2` | `int` | `2000` | `2000` | Persistent L2 cache entry capacity. |

---

### `[plugins]`

Controls plugin registration during bootstrap.

| Key | Type | Code Default | Config Default | Description |
| --- | --- | --- | --- | --- |
| `disabled` | `list[str]` | `()` | `()` | Sequence of plugin IDs to disable during bootstrap. |

---

## Cloud Provider Configuration

The following sections configure external cloud adapters. These settings are consulted only when external processing and network access are enabled in `[security]`.

### `[mistral]`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `api_key` | `str \| None` | `None` | Mistral API key (overrides `MISTRAL_API_KEY` env var). |
| `base_url` | `str` | `"https://api.mistral.ai/v1"` | Base endpoint URL for Mistral API. |
| `model_ocr` | `str` | `"mistral-ocr-latest"` | Model identifier for Mistral OCR. |
| `model_translation` | `str` | `"mistral-large-latest"` | Model identifier for Mistral translation. |
| `timeout_seconds` | `float` | `60.0` | HTTP request timeout in seconds. |

### `[gemini]`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `api_key` | `str \| None` | `None` | Gemini API key (overrides `GEMINI_API_KEY` env var). |
| `base_url` | `str` | `"https://generativelanguage.googleapis.com/v1beta"` | Base endpoint URL for Gemini API. |
| `model_ocr` | `str` | `"gemini-2.5-flash"` | Model identifier for Gemini OCR. |
| `model_translation` | `str` | `"gemini-2.5-flash"` | Model identifier for Gemini translation. |
| `timeout_seconds` | `float` | `60.0` | HTTP request timeout in seconds. |

### `[azure]`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `api_key` | `str \| None` | `None` | Azure Document Intelligence key (overrides `AZURE_API_KEY`). |
| `endpoint` | `str \| None` | `None` | Azure Document Intelligence endpoint (overrides `AZURE_ENDPOINT`). |
| `translator_key` | `str \| None` | `None` | Azure Translator key (overrides `AZURE_TRANSLATOR_KEY`). |
| `translator_region` | `str \| None` | `None` | Azure Translator region (overrides `AZURE_TRANSLATOR_REGION`). |
| `translator_endpoint` | `str` | `"https://api.cognitive.microsofttranslator.com"` | Endpoint URL for Azure Translator. |
| `api_version` | `str` | `"2024-11-30"` | Azure Document Intelligence API version. |
| `timeout_seconds` | `float` | `60.0` | HTTP request timeout in seconds. |

### `[bhashini]`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `user_id` | `str \| None` | `None` | Bhashini user ID (overrides `BHASHINI_USER_ID`). |
| `api_key` | `str \| None` | `None` | Bhashini API key (overrides `BHASHINI_API_KEY`). |
| `inference_key` | `str \| None` | `None` | Bhashini inference key (overrides `BHASHINI_INFERENCE_KEY`). |
| `pipeline_url` | `str` | `"https://dhruva-api.bhashini.gov.in/services/inference/pipeline"` | Inference pipeline endpoint URL. |
| `timeout_seconds` | `float` | `60.0` | HTTP request timeout in seconds. |
