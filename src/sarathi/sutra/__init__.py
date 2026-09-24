"""Sutra — Configuration for Sarathi.

Exposes:
- Settings: Immutable container for validated TOML configuration.
- load_settings: Public explicit loader for TOML configuration files.
"""

from __future__ import annotations

from sarathi.sutra.loader import load_settings
from sarathi.sutra.settings import (
    Settings,
    get_canonical_data_root,
    get_canonical_models_root,
)

__all__ = [
    "Settings",
    "get_canonical_data_root",
    "get_canonical_models_root",
    "load_settings",
]
