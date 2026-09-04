"""Settings Contract for Sutra Configuration in Sarathi V2.

Defines:
- Settings: Immutable typed container for validated TOML configuration.

Sutra exposes read-only configuration only; policy decisions and secret
management remain with Kavacha.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from sarathi.dosh import DoshError, FailureCode

if TYPE_CHECKING:
    from sarathi.kavacha import SecurityPolicy
    from sarathi.smriti import CachePolicy


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

    def section(self, name: str) -> Mapping[str, Any] | None:
        """Alias for get_section."""
        return self.get_section(name)

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

    # --- Typed Sutra accessors with canonical defaults ---

    @property
    def storage_runtime_root(self) -> Path:
        """Return validated runtime root Path, defaulting to 'Runtime'."""
        sec = self.get_section("storage")
        raw = sec.get("runtime_root", "Runtime") if sec is not None else "Runtime"
        if not isinstance(raw, (str, Path)) or not str(raw).strip():
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="storage.runtime_root must be a non-empty string or Path.",
            )
        return Path(raw)

    @property
    def storage_output_root(self) -> Path:
        """Return validated output root Path, defaulting to 'Output'."""
        sec = self.get_section("storage")
        raw = sec.get("output_root", "Output") if sec is not None else "Output"
        if not isinstance(raw, (str, Path)) or not str(raw).strip():
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="storage.output_root must be a non-empty string or Path.",
            )
        return Path(raw)

    @property
    def storage_input_root(self) -> Path:
        """Return validated input root Path, defaulting to 'Input'."""
        sec = self.get_section("storage")
        raw = sec.get("input_root", "Input") if sec is not None else "Input"
        if not isinstance(raw, (str, Path)) or not str(raw).strip():
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="storage.input_root must be a non-empty string or Path.",
            )
        return Path(raw)

    @property
    def pipeline_max_retries(self) -> int:
        """Return validated pipeline max_retries count, defaulting to 0."""
        sec = self.get_section("pipeline")
        raw = sec.get("max_retries", 0) if sec is not None else 0
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"pipeline.max_retries must be a non-negative integer, got {raw!r}.",
            )
        return raw

    @property
    def allow_pii_access(self) -> bool:
        """Return validated allow_pii_access boolean, defaulting to True."""
        sec = self.get_section("security")
        raw = sec.get("allow_pii_access", True) if sec is not None else True
        if not isinstance(raw, bool):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="security.allow_pii_access must be a boolean.",
            )
        return raw

    @property
    def allow_network_access(self) -> bool:
        """Return validated allow_network_access boolean, defaulting to False."""
        sec = self.get_section("security")
        raw = sec.get("allow_network_access", False) if sec is not None else False
        if not isinstance(raw, bool):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="security.allow_network_access must be a boolean.",
            )
        return raw

    @property
    def allow_external_processing(self) -> bool:
        """Return validated allow_external_processing boolean, defaulting to False."""
        sec = self.get_section("security")
        raw = sec.get("allow_external_processing", False) if sec is not None else False
        if not isinstance(raw, bool):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="security.allow_external_processing must be a boolean.",
            )
        return raw

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
        sec = self.get_section("telemetry")
        raw = sec.get("history_enabled", False) if sec is not None else False
        if not isinstance(raw, bool):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="telemetry.history_enabled must be a boolean.",
            )
        return raw

    @property
    def telemetry_history_path(self) -> Path | None:
        """Return validated telemetry history path, defaulting to None."""
        sec = self.get_section("telemetry")
        raw = sec.get("history_path", None) if sec is not None else None
        if raw is None:
            return None
        if not isinstance(raw, (str, Path)) or not str(raw).strip():
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="telemetry.history_path must be a non-empty string or Path if specified.",
            )
        return Path(raw)

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
        sec = self.get_section("telemetry")
        raw = sec.get("live_buffer_capacity", 1000) if sec is not None else 1000
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"telemetry.live_buffer_capacity must be a positive integer, got {raw!r}.",
            )
        return raw

    @property
    def telemetry_history_max_records(self) -> int:
        """Return validated telemetry history maximum records, defaulting to 1000."""
        sec = self.get_section("telemetry")
        raw = sec.get("history_max_records", 1000) if sec is not None else 1000
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"telemetry.history_max_records must be a positive integer, got {raw!r}.",
            )
        return raw

    @property
    def hardware_detect_accelerators(self) -> bool:
        """Return validated hardware.detect_accelerators boolean, defaulting to False."""
        sec = self.get_section("hardware")
        raw = sec.get("detect_accelerators", False) if sec is not None else False
        if not isinstance(raw, bool):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="hardware.detect_accelerators must be a boolean.",
            )
        return raw

    @property
    def cache_enabled(self) -> bool:
        """Return validated cache.enabled boolean, defaulting to True."""
        sec = self.get_section("cache")
        raw = sec.get("enabled", True) if sec is not None else True
        if not isinstance(raw, bool):
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="cache.enabled must be a boolean.",
            )
        return raw

    @property
    def cache_dir(self) -> Path | None:
        """Return validated cache directory path, defaulting to None."""
        sec = self.get_section("cache")
        raw = sec.get("dir", None) if sec is not None else None
        if raw is None:
            return None
        if not isinstance(raw, (str, Path)) or not str(raw).strip():
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="cache.dir must be a non-empty string or Path if specified.",
            )
        return Path(raw)

    @property
    def cache_ttl_seconds(self) -> int | None:
        """Return validated cache TTL in seconds, defaulting to 86400 (None disables TTL)."""
        sec = self.get_section("cache")
        raw = sec.get("ttl_seconds", 86400) if sec is not None else 86400
        if raw is None:
            return None
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"cache.ttl_seconds must be a positive integer or None, got {raw!r}.",
            )
        return raw

    @property
    def cache_max_entries_l1(self) -> int:
        """Return validated cache max entries for L1 memory, defaulting to 200."""
        sec = self.get_section("cache")
        raw = sec.get("max_entries_l1", 200) if sec is not None else 200
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"cache.max_entries_l1 must be a positive integer, got {raw!r}.",
            )
        return raw

    @property
    def cache_max_entries_l2(self) -> int:
        """Return validated cache max entries for L2 persistent store, defaulting to 2000."""
        sec = self.get_section("cache")
        raw = sec.get("max_entries_l2", 2000) if sec is not None else 2000
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message=f"cache.max_entries_l2 must be a positive integer, got {raw!r}.",
            )
        return raw

    def cache_policy(self) -> CachePolicy:
        """Construct a validated CachePolicy from configuration."""
        from sarathi.smriti import CachePolicy

        return CachePolicy(
            ttl_seconds=self.cache_ttl_seconds,
            max_entries_l1=self.cache_max_entries_l1,
            max_entries_l2=self.cache_max_entries_l2,
        )

    def security_policy(self) -> SecurityPolicy:
        """Construct a validated SecurityPolicy from configuration."""
        from sarathi.kavacha import SecurityPolicy

        try:
            return SecurityPolicy(
                allow_pii_access=self.allow_pii_access,
                allow_network_access=self.allow_network_access,
                allow_external_processing=self.allow_external_processing,
                allowed_secrets=self.allowed_secrets,
            )
        except (ValueError, TypeError) as err:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="Invalid security policy configuration.",
            ) from err
