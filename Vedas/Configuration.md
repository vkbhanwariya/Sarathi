# Sarathi Configuration

Configuration is managed by the **Sutra** subsystem, loaded from `config/settings.toml` into immutable, typed `Settings`.

---

## Master Configuration Matrix

| Section | Key | Type | Default | Description & Security Impact |
| :--- | :--- | :--- | :--- | :--- |
| `[storage]` | `input_root` | `Path` | `"Input"` | Root directory containing raw input documents. |
| | `output_root` | `Path` | `"Output"` | Root directory for validated, committed output artifacts. |
| | `runtime_root` | `Path` | `"Runtime"` | Directory for scratch workspaces, staging, and temp files. |
| `[pipeline]` | `max_retries` | `int` | `0` | Automated retry limit for transient pipeline errors. |
| `[security]` | `allow_pii_access` | `bool` | `true` | Permits access to Personally Identifiable Information for local processing. |
| | `allow_network_access` | `bool` | `false` | **(External/Cloud)** Permits outbound socket/HTTP egress (disabled by default). |
| | `allow_external_processing`| `bool` | `false` | **(External/Cloud)** Permits transmitting document data to cloud APIs. |
| | `allowed_secrets` | `list[str]`| `["MISTRAL_API_KEY"]` | Environment variable names containing authorized API keys. |
| `[hardware]` | `detect_accelerators` | `bool` | `false` | Probes OpenVINO GPU and NPU devices when enabled. |
| | `gpu_capacity_per_device` | `int` | `4` | Max concurrent worker slots per GPU (clamped by OpenVINO runtime). |
| | `cpu_capacity` | `int \| None` | `None` | CPU concurrency slots (`None` auto-detects from CPU topology). |
| | `npu_capacity_per_device` | `int` | `2` | Concurrency slots allocated per NPU. |
| | `max_queue_depth` | `int` | `64` | Subtask queue depth for accelerator dispatch. |
| `[cache]` | `enabled` | `bool` | `true` | Enables deterministic result caching across runs. |
| | `dir` | `Path \| None`| `None` | Persistent L2 cache directory (`None` = memory-only L1). |
| | `ttl_seconds` | `int \| None`| `86400` | Result cache TTL in seconds (default 24h). |
| | `max_entries_l1` | `int` | `200` | In-memory L1 cache capacity. |
| | `max_entries_l2` | `int` | `2000` | Disk L2 cache capacity. |
| `[telemetry]` | `history_enabled` | `bool` | `false` | Enables persistent storage of terminal run records. |
| | `history_path` | `Path \| None`| `"history.jsonl"` | File path where terminal run history is stored. |
| | `history_format` | `str` | `"jsonl"` | Format for stored history (`"jsonl"` or `"sqlite"`). |
| | `live_buffer_capacity` | `int` | `1000` | In-memory live telemetry buffer capacity. |
| `[limits]` | `max_input_bytes` | `int` | `268435456` | Maximum allowed size of an uploaded input file (256 MiB). |
| | `max_uncompressed_bytes` | `int` | `1073741824`| Maximum allowed uncompressed size for zip/docx/xlsx (1 GiB). |
| | `max_compression_ratio` | `float` | `200.0` | Maximum compression ratio permitted (zip bomb protection). |
