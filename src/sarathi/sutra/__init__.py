"""Sutra — Configuration for Sarathi V2.

Exposes:
- Settings: Immutable container for validated TOML configuration.
- load_settings: Public explicit loader for TOML configuration files.
"""

from __future__ import annotations

from sarathi.sutra.loader import load_settings
from sarathi.sutra.settings import Settings

__all__ = [
    "Settings",
    "load_settings",
]
