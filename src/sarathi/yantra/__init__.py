"""Yantra — Resource & Execution Manager for Sarathi V2.

Exposes:
- Allocation: Immutable record of an allocated hardware slot.
- DeviceInfo: Immutable record of an available device and capacity.
- DeviceInventory: Immutable collection of available devices.
- Yantra: Public resource management interface.
"""

from __future__ import annotations

from sarathi.yantra.devices import DeviceInfo, DeviceInventory
from sarathi.yantra.manager import Yantra
from sarathi.yantra.resources import Allocation

__all__ = [
    "Allocation",
    "DeviceInfo",
    "DeviceInventory",
    "Yantra",
]
