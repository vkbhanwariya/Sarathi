"""Nabhi — Core Kernel for Sarathi V2.

Exposes:
- Kosh: Plugin and capability declaration registry.
- Prana: Runtime component lifecycle coordinator.
"""

from __future__ import annotations

from sarathi.nabhi.kosh import Kosh
from sarathi.nabhi.prana import Prana

__all__ = [
    "Kosh",
    "Prana",
]
