"""Resource allocation engine for Yantra in Sarathi V2.

Defines:
- Allocation: Immutable record of an allocated hardware slot.
- ResourceAllocator: Thread-safe slot allocator and releaser.

Contains reservation and capacity logic only; performs no queuing, priority scheduling,
benchmarking, or execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import uuid
from typing import Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import DeviceRequirement, DeviceType
from sarathi.yantra.devices import DeviceInventory


@dataclass(frozen=True, slots=True)
class Allocation:
    """Immutable reservation record for a single execution device slot."""

    allocation_id: str
    device_id: str
    device_type: DeviceType
    is_spillover: bool
    allocator_id: str

    def __post_init__(self) -> None:
        if not self.allocation_id or not isinstance(self.allocation_id, str):
            raise ValueError("allocation_id must be a non-empty string.")
        if not self.device_id or not isinstance(self.device_id, str):
            raise ValueError("device_id must be a non-empty string.")
        if not isinstance(self.device_type, DeviceType):
            raise TypeError(f"device_type must be a DeviceType, got {type(self.device_type).__name__}.")
        if not isinstance(self.is_spillover, bool):
            raise TypeError(f"is_spillover must be a bool, got {type(self.is_spillover).__name__}.")
        if not self.allocator_id or not isinstance(self.allocator_id, str):
            raise ValueError("allocator_id must be a non-empty string.")


class ResourceAllocator:
    """Thread-safe hardware resource allocator managing capacity across a DeviceInventory."""

    def __init__(self, inventory: DeviceInventory) -> None:
        if not isinstance(inventory, DeviceInventory):
            raise TypeError(f"inventory must be a DeviceInventory instance, got {type(inventory).__name__}.")

        self._inventory: DeviceInventory = inventory
        self._allocator_id: str = uuid.uuid4().hex[:12]
        self._lock: threading.Lock = threading.Lock()
        self._used_slots: dict[str, int] = {dev.device_id: 0 for dev in inventory.devices}
        self._active_allocations: dict[str, Allocation] = {}
        self._counter: int = 0

    @property
    def inventory(self) -> DeviceInventory:
        """Return the immutable device inventory."""
        return self._inventory

    @property
    def allocator_id(self) -> str:
        """Return the unique allocator instance identifier."""
        return self._allocator_id

    def allocate(self, requirement: DeviceRequirement) -> Allocation:
        """Allocate a single slot matching device requirements, respecting preference and spillover.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If no matching device has available capacity.
            TypeError: If requirement is not a DeviceRequirement.
        """
        if not isinstance(requirement, DeviceRequirement):
            raise TypeError(f"requirement must be a DeviceRequirement, got {type(requirement).__name__}.")

        with self._lock:
            # 1. Check preferred devices in order
            for pref_type in requirement.preferred_devices:
                for dev in self._inventory.devices:
                    if dev.device_type == pref_type and self._used_slots[dev.device_id] < dev.capacity:
                        return self._create_allocation(dev.device_id, dev.device_type, is_spillover=False)

            # 2. Spill over through supported devices in order
            for supp_type in requirement.supported_devices:
                if supp_type in requirement.preferred_devices:
                    continue  # Already checked and exhausted
                for dev in self._inventory.devices:
                    if dev.device_type == supp_type and self._used_slots[dev.device_id] < dev.capacity:
                        return self._create_allocation(dev.device_id, dev.device_type, is_spillover=True)

            # 3. No compatible capacity available
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message="No compatible device capacity is currently available.",
            )

    def release(self, allocation: Allocation) -> None:
        """Release a previously acquired allocation back to the inventory.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If allocation is foreign, unknown, or already released.
            TypeError: If allocation is not an Allocation instance.
        """
        if not isinstance(allocation, Allocation):
            raise TypeError(f"allocation must be an Allocation instance, got {type(allocation).__name__}.")

        with self._lock:
            if allocation.allocator_id != self._allocator_id:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Cannot release foreign allocation created by a different allocator.",
                )

            if allocation.allocation_id not in self._active_allocations:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Allocation not found or already released.",
                )

            self._used_slots[allocation.device_id] -= 1
            del self._active_allocations[allocation.allocation_id]

    def _create_allocation(self, device_id: str, device_type: DeviceType, *, is_spillover: bool) -> Allocation:
        self._used_slots[device_id] += 1
        self._counter += 1
        alloc_id = f"alloc-{self._allocator_id}-{self._counter}"
        allocation = Allocation(
            allocation_id=alloc_id,
            device_id=device_id,
            device_type=device_type,
            is_spillover=is_spillover,
            allocator_id=self._allocator_id,
        )
        self._active_allocations[alloc_id] = allocation
        return allocation
