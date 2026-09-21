"""Settings Contract for Sutra Configuration in Sarathi.

Defines:
- Settings: Immutable typed container for validated TOML configuration.

Sutra exposes read-only configuration only; policy decisions and secret
management remain with Kavacha.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sarathi.dosh import DoshError, FailureCode


def _freeze_value(value: Any) -> Any:
    """Recursively freeze mappings to MappingProxyType and collections to tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze_value(v) for k, v in value.items()})
    if isinstance(value, (list, tuple, set)):
        return tuple(_freeze_value(v) for v in value)
    return value


def get_canonical_data_root() -> Path:
    """Return the canonical base data root directory for Sarathi static domain assets.

    Resolution precedence:
    1. SARATHI_DATA_DIR environment variable (if set and directory exists).
    2. Package-internal data directory (sarathi/data if distributed in wheel).
    3. Source-tree repository data root (repository_root / data).
    """
    env_dir = os.environ.get("SARATHI_DATA_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        if p.is_dir():
            return p

    pkg_data = Path(__file__).resolve().parents[1] / "data"
    if pkg_data.is_dir():
        return pkg_data

    return Path(__file__).resolve().parents[3] / "data"


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable container for validated TOML configuration."""

    _data: Mapping[str, Any]

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        if data is None:
            frozen = MappingProxyType({})
        elif isinstance(data, Mapping):
            frozen = _freeze_value(dict(data))
        else:
            raise TypeError(f"Settings data must be a Mapping, got {type(data).__name__}.")
        object.__setattr__(self, "_data", frozen)

    def get_section(self, name: str) -> Mapping[str, Any] | None:
        """Return the named top-level section table as an immutable Mapping, or None if absent."""
        if not isinstance(name, str):
            raise TypeError(f"Section name must be a string, got {type(name).__name__}.")
        val = self._data.get(name)
        if val is None or not isinstance(val, Mapping):
            return None
        return val

    def __getitem__(self, key: str) -> Any:
        """Get a top-level configuration value by key."""
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        """Check if key exists in settings."""
        return key in self._data

    @property
    def sections(self) -> tuple[str, ...]:
        """Return names of all top-level table sections."""
        return tuple(k for k, v in self._data.items() if isinstance(v, Mapping))

    @property
    def data(self) -> Mapping[str, Any]:
        """Return the entire immutable root mapping."""
        return self._data

    # --- Internal Validation Helpers ---

    def _raw_value(self, section: str, key: str, default: Any) -> Any:
        sec = self.get_section(section)
        return sec.get(key, default) if sec is not None else default

    def _get_path(self, section: str, key: str, default: str | Path) -> Path:
        raw = self._raw_value(section, key, default)
        if not isinstance(raw, (str, Path)) or not str(raw).strip():
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"{section}.{key} must be a non-empty string or Path.",
            )
        return Path(raw)

    def _get_optional_path(self, section: str, key: str, default: str | Path | None = None) -> Path | None:
        raw = self._raw_value(section, key, default)
        if raw is None:
            return None
        if not isinstance(raw, (str, Path)) or not str(raw).strip():
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"{section}.{key} must be a non-empty string or Path if specified.",
            )
        return Path(raw)

    def _get_bool(self, section: str, key: str, default: bool) -> bool:
        raw = self._raw_value(section, key, default)
        if not isinstance(raw, bool):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"{section}.{key} must be a boolean.",
            )
        return raw

    def _get_int(self, section: str, key: str, default: int, *, min_val: int = 1) -> int:
        raw = self._raw_value(section, key, default)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < min_val:
            msg = (
                f"{section}.{key} must be a non-negative integer, got {raw!r}."
                if min_val == 0
                else f"{section}.{key} must be a positive integer, got {raw!r}."
            )
            raise DoshError(code=FailureCode.INVALID_CONFIGURATION, message=msg)
        return raw

    def _get_optional_int(self, section: str, key: str, default: int | None = None, *, min_val: int = 1) -> int | None:
        raw = self._raw_value(section, key, default)
        if raw is None:
            return None
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < min_val:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"{section}.{key} must be a positive integer or None, got {raw!r}.",
            )
        return raw

    def _get_float(self, section: str, key: str, default: float, *, min_val: float = 0.0) -> float:
        raw = self._raw_value(section, key, default)
        if not isinstance(raw, (int, float)) or isinstance(raw, bool) or raw <= min_val:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"{section}.{key} must be a positive number, got {raw!r}.",
            )
        return float(raw)

    # --- Typed Sutra accessors with canonical defaults ---

    @property
    def storage_runtime_root(self) -> Path:
        """Return validated runtime root Path, defaulting to 'Runtime'."""
        return self._get_path("storage", "runtime_root", "Runtime")

    @property
    def storage_output_root(self) -> Path:
        """Return validated output root Path, defaulting to 'Output'."""
        return self._get_path("storage", "output_root", "Output")

    @property
    def storage_input_root(self) -> Path:
        """Return validated input root Path, defaulting to 'Input'."""
        return self._get_path("storage", "input_root", "Input")

    @property
    def pipeline_max_retries(self) -> int:
        """Return validated pipeline max_retries count, defaulting to 0."""
        return self._get_int("pipeline", "max_retries", 0, min_val=0)

    @property
    def allow_pii_access(self) -> bool:
        """Return validated allow_pii_access boolean, defaulting to True."""
        return self._get_bool("security", "allow_pii_access", True)

    @property
    def allow_network_access(self) -> bool:
        """Return validated allow_network_access boolean, defaulting to False."""
        return self._get_bool("security", "allow_network_access", False)

    @property
    def allow_external_processing(self) -> bool:
        """Return validated allow_external_processing boolean, defaulting to False."""
        return self._get_bool("security", "allow_external_processing", False)

    @property
    def allowed_secrets(self) -> tuple[str, ...]:
        """Return validated allowed_secrets sequence, defaulting to ()."""
        sec = self.get_section("security")
        raw = sec.get("allowed_secrets", ()) if sec is not None else ()
        if not isinstance(raw, (list, tuple)) or not all(isinstance(s, str) for s in raw):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="security.allowed_secrets must be a sequence of strings.",
            )
        return tuple(raw)

    @property
    def telemetry_history_enabled(self) -> bool:
        """Return validated telemetry_history_enabled boolean, defaulting to False."""
        return self._get_bool("telemetry", "history_enabled", False)

    @property
    def telemetry_history_path(self) -> Path | None:
        """Return validated telemetry history path, defaulting to None."""
        return self._get_optional_path("telemetry", "history_path", None)

    @property
    def telemetry_history_format(self) -> str:
        """Return validated telemetry history format ('jsonl' or 'sqlite'), defaulting to 'jsonl'."""
        sec = self.get_section("telemetry")
        raw = sec.get("history_format", "jsonl") if sec is not None else "jsonl"
        if not isinstance(raw, str) or raw.lower() not in ("jsonl", "sqlite"):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"telemetry.history_format must be 'jsonl' or 'sqlite', got {raw!r}.",
            )
        return raw.lower()

    @property
    def telemetry_live_buffer_capacity(self) -> int:
        """Return validated telemetry live buffer capacity, defaulting to 1000."""
        return self._get_int("telemetry", "live_buffer_capacity", 1000)

    @property
    def telemetry_history_max_records(self) -> int:
        """Return validated telemetry history maximum records, defaulting to 1000."""
        return self._get_int("telemetry", "history_max_records", 1000)

    @property
    def hardware_detect_accelerators(self) -> bool:
        """Return validated hardware.detect_accelerators boolean, defaulting to False."""
        return self._get_bool("hardware", "detect_accelerators", False)

    @property
    def hardware_cpu_capacity(self) -> int | None:
        """Return validated hardware.cpu_capacity if specified, or None."""
        return self._get_optional_int("hardware", "cpu_capacity", None)

    @property
    def hardware_gpu_capacity_per_device(self) -> int:
        """Return validated hardware.gpu_capacity_per_device, defaulting to 4.

        Note: On Intel Arc iGPU (Meteor Lake), OpenVINO clamps effective streams to 2
        (via driver RANGE_FOR_STREAMS) to prevent context thrashing.
        """
        return self._get_int("hardware", "gpu_capacity_per_device", 4)

    @property
    def hardware_npu_capacity_per_device(self) -> int:
        """Return validated hardware.npu_capacity_per_device, defaulting to 2."""
        return self._get_int("hardware", "npu_capacity_per_device", 2)

    @property
    def hardware_max_queue_depth(self) -> int:
        """Return validated hardware.max_queue_depth, defaulting to 64."""
        return self._get_int("hardware", "max_queue_depth", 64)

    @property
    def cache_enabled(self) -> bool:
        """Return validated cache.enabled boolean, defaulting to True."""
        return self._get_bool("cache", "enabled", True)

    @property
    def cache_dir(self) -> Path | None:
        """Return validated cache directory path, defaulting to None."""
        return self._get_optional_path("cache", "dir", None)

    @property
    def cache_ttl_seconds(self) -> int | None:
        """Return validated cache TTL in seconds, defaulting to 86400 (None disables TTL)."""
        return self._get_optional_int("cache", "ttl_seconds", 86400)

    @property
    def cache_max_entries_l1(self) -> int:
        """Return validated cache max entries for L1 memory, defaulting to 200."""
        return self._get_int("cache", "max_entries_l1", 200)

    @property
    def cache_max_entries_l2(self) -> int:
        """Return validated cache max entries for L2 persistent store, defaulting to 2000."""
        return self._get_int("cache", "max_entries_l2", 2000)

    @property
    def plugins_disabled(self) -> tuple[str, ...]:
        """Return validated tuple of operator-disabled plugin IDs, defaulting to ()."""
        sec = self.get_section("plugins")
        raw = sec.get("disabled", ()) if sec is not None else ()
        if isinstance(raw, str):
            clean = raw.strip()
            return (clean,) if clean else ()
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if not isinstance(item, str) or not item.strip():
                    raise DoshError(
                        code=FailureCode.INVALID_CONFIGURATION,
                        message="plugins.disabled items must be non-empty strings.",
                    )
            return tuple(str(item).strip() for item in raw)
        raise DoshError(
            code=FailureCode.INVALID_CONFIGURATION,
            message="plugins.disabled must be a sequence of strings.",
        )

    @property
    def limits_max_input_bytes(self) -> int:
        """Return maximum allowed input file size in bytes, defaulting to 500 MB."""
        return self._get_int("limits", "max_input_bytes", 524_288_000)

    @property
    def limits_max_uncompressed_bytes(self) -> int:
        """Return maximum allowed total uncompressed ZIP bytes, defaulting to 1 GiB."""
        return self._get_int("limits", "max_uncompressed_bytes", 1_073_741_824)

    @property
    def limits_max_compression_ratio(self) -> float:
        """Return maximum allowed ZIP compression ratio, defaulting to 200.0."""
        return self._get_float("limits", "max_compression_ratio", 200.0)

    @property
    def limits_max_zip_members(self) -> int:
        """Return maximum allowed member files in a ZIP archive, defaulting to 10000."""
        return self._get_int("limits", "max_zip_members", 10_000)
