"""Yantra — Resource & Execution Manager for Sarathi V2.

Exposes:
- Yantra: Single public interface managing hardware slot allocation and release.

Does NOT contain executor or execution APIs yet.
"""

from __future__ import annotations

from sarathi.sankalpa import DeviceRequirement
from sarathi.yantra.devices import DeviceInventory
from sarathi.yantra.resources import Allocation, _ResourceAllocator


class Yantra:
    """Resource manager for hardware allocation and release."""

    def __init__(self, inventory: DeviceInventory) -> None:
        if not isinstance(inventory, DeviceInventory):
            raise TypeError(f"inventory must be a DeviceInventory instance, got {type(inventory).__name__}.")
        self._allocator = _ResourceAllocator(inventory)

    @property
    def inventory(self) -> DeviceInventory:
        """Return the active immutable device inventory."""
        return self._allocator.inventory

    def allocate(self, requirement: DeviceRequirement) -> Allocation:
        """Allocate an execution device slot for a capability requirement.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If capacity is exhausted.
            TypeError: If requirement is not a DeviceRequirement.
        """
        return self._allocator.allocate(requirement)

    def release(self, allocation: Allocation) -> None:
        """Release an allocated device slot back to the manager.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If allocation is unknown/foreign/tampered/double-released.
            TypeError: If allocation is not an Allocation instance.
        """
        self._allocator.release(allocation)
