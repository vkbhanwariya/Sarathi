"""Settings Contract for Sutra Configuration in Sarathi V2.

Defines:
- Settings: Immutable typed container for validated TOML configuration.

Sutra exposes read-only configuration only; policy decisions and secret
management remain with Kavacha.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


def _freeze_value(value: Any) -> Any:
    """Recursively freeze mappings to MappingProxyType and collections to tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze_value(v) for k, v in value.items()})
    if isinstance(value, (list, tuple, set)):
        return tuple(_freeze_value(v) for v in value)
    return value


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
