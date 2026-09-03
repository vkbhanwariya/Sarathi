"""Resource allocation engine for Yantra in Sarathi V2.

Defines:
- Allocation: Immutable record of an allocated hardware slot.
- _ResourceAllocator: Internal thread-safe slot allocator and releaser.

Contains reservation and capacity logic only; performs no queuing, priority scheduling,
benchmarking, or execution.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import DeviceRequirement, DeviceType, ExecutionContext
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


@dataclass
class _WaitEntry:
    entry_id: str
    requirement: DeviceRequirement
    event: threading.Event
    allocation: Allocation | None = None
    error: BaseException | None = None


class _ResourceAllocator:
    """Internal thread-safe hardware resource allocator managing capacity and bounded queueing across a DeviceInventory."""

    def __init__(self, inventory: DeviceInventory, max_queue_depth: int = 64) -> None:
        if not isinstance(inventory, DeviceInventory):
            raise TypeError(f"inventory must be a DeviceInventory instance, got {type(inventory).__name__}.")
        if not isinstance(max_queue_depth, int) or isinstance(max_queue_depth, bool) or max_queue_depth <= 0:
            raise ValueError("max_queue_depth must be a positive integer.")

        self._inventory: DeviceInventory = inventory
        self._max_queue_depth: int = max_queue_depth
        self._allocator_id: str = uuid.uuid4().hex[:12]
        self._lock: threading.Lock = threading.Lock()
        self._used_slots: dict[str, int] = {dev.device_id: 0 for dev in inventory.devices}
        self._active_allocations: dict[str, Allocation] = {}
        self._waiting_queue: list[_WaitEntry] = []
        self._counter: int = 0
        self._is_closed: bool = False

    @property
    def inventory(self) -> DeviceInventory:
        """Return the immutable device inventory."""
        return self._inventory

    @property
    def allocator_id(self) -> str:
        """Return the unique allocator instance identifier."""
        return self._allocator_id

    @property
    def max_queue_depth(self) -> int:
        """Return the maximum allowed waiting queue depth."""
        return self._max_queue_depth

    @property
    def is_closed(self) -> bool:
        """Return True if allocator is closed."""
        return self._is_closed

    def allocate(
        self,
        requirement: DeviceRequirement,
        context: ExecutionContext | None = None,
        timeout: float | None = None,
    ) -> Allocation:
        """Allocate a single slot matching device requirements, respecting preference, spillover, and queueing.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If no compatible capacity is available or timeout reached.
            DoshError(FailureCode.OPERATION_CANCELLED): If context cancellation is detected while queued.
            TypeError: If requirement is not a DeviceRequirement.
        """
        if not isinstance(requirement, DeviceRequirement):
            raise TypeError(f"requirement must be a DeviceRequirement, got {type(requirement).__name__}.")
        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")
        if timeout is not None and (not isinstance(timeout, (int, float)) or timeout < 0):
            raise ValueError("timeout must be a non-negative number or None.")

        with self._lock:
            if self._is_closed:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Allocator is closed.",
                )

            # Check immediate cancellation
            if context is not None and context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            # 1. Check if slots are currently available (preferred then supported)
            alloc = self._try_allocate_unlocked(requirement)
            if alloc is not None:
                return alloc

            # 2. Check if ANY device in inventory could EVER satisfy this requirement
            has_compatible_device = any(
                dev.device_type in requirement.supported_devices
                for dev in self._inventory.devices
            )
            if not has_compatible_device:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="No compatible device exists in inventory for this requirement.",
                )

            # If no timeout is specified or timeout <= 0, do not wait in queue
            if timeout is None or timeout <= 0:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="No compatible device capacity is currently available.",
                )

            # 3. Check queue capacity
            if len(self._waiting_queue) >= self._max_queue_depth:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Execution queue capacity exceeded; all compatible devices are busy.",
                )

            # 4. Enqueue waiter entry sorted by priority descending (higher priority first; FIFO for equal priority)
            self._counter += 1
            entry = _WaitEntry(
                entry_id=f"wait-{self._allocator_id}-{self._counter}",
                requirement=requirement,
                event=threading.Event(),
            )
            insert_idx = len(self._waiting_queue)
            for i, queued in enumerate(self._waiting_queue):
                if requirement.priority > queued.requirement.priority:
                    insert_idx = i
                    break
            self._waiting_queue.insert(insert_idx, entry)

        # Wait outside lock
        start_time = time.monotonic()
        while True:
            # Check cooperative cancellation
            if context is not None and context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                with self._lock:
                    if entry in self._waiting_queue:
                        self._waiting_queue.remove(entry)
                    if entry.allocation is not None:
                        self._release_slot_unlocked(entry.allocation)
                context.cancellation_token.check_cancelled()

            # Check timeout
            step_timeout = 0.05
            if timeout is not None:
                remaining = timeout - (time.monotonic() - start_time)
                if remaining <= 0:
                    with self._lock:
                        if entry in self._waiting_queue:
                            self._waiting_queue.remove(entry)
                        if entry.allocation is not None:
                            self._release_slot_unlocked(entry.allocation)
                    raise DoshError(
                        code=FailureCode.RESOURCE_UNAVAILABLE,
                        message="Timed out waiting for device capacity.",
                    )
                step_timeout = min(step_timeout, remaining)

            if entry.event.wait(timeout=step_timeout):
                with self._lock:
                    if entry.error is not None:
                        raise entry.error
                    if entry.allocation is not None:
                        return entry.allocation
                    if self._is_closed:
                        raise DoshError(
                            code=FailureCode.RESOURCE_UNAVAILABLE,
                            message="Allocator was closed while waiting.",
                        )

    def release(self, allocation: Allocation) -> None:
        """Release a previously acquired allocation back to the inventory safely, dispatching next queued waiter.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If allocation is unknown, tampered, foreign, or already released.
            TypeError: If allocation is not an Allocation instance.
        """
        if not isinstance(allocation, Allocation):
            raise TypeError(f"allocation must be an Allocation instance, got {type(allocation).__name__}.")

        with self._lock:
            registered = self._active_allocations.get(allocation.allocation_id)
            if registered is None:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Allocation not found or already released.",
                )

            if allocation != registered:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Allocation integrity verification failed; record does not match registered allocation.",
                )

            self._release_slot_unlocked(registered)
            del self._active_allocations[registered.allocation_id]

            # Dispatch next compatible queued waiter
            self._dispatch_waiting_unlocked()

    def close(self) -> None:
        """Close allocator, rejecting any queued waiters."""
        with self._lock:
            self._is_closed = True
            for entry in self._waiting_queue:
                entry.error = DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Yantra resource allocator is closed.",
                )
                entry.event.set()
            self._waiting_queue.clear()

    def _try_allocate_unlocked(self, requirement: DeviceRequirement) -> Allocation | None:
        # 1. Check preferred devices in order
        for pref_type in requirement.preferred_devices:
            for dev in self._inventory.devices:
                if dev.device_type == pref_type and self._used_slots[dev.device_id] < dev.capacity:
                    return self._create_allocation(dev.device_id, dev.device_type, is_spillover=False)

        # 2. Spill over through supported devices in order
        for supp_type in requirement.supported_devices:
            if supp_type in requirement.preferred_devices:
                continue
            for dev in self._inventory.devices:
                if dev.device_type == supp_type and self._used_slots[dev.device_id] < dev.capacity:
                    return self._create_allocation(dev.device_id, dev.device_type, is_spillover=True)

        return None

    def _release_slot_unlocked(self, registered: Allocation) -> None:
        self._used_slots[registered.device_id] -= 1

    def _dispatch_waiting_unlocked(self) -> None:
        for i, entry in enumerate(self._waiting_queue):
            alloc = self._try_allocate_unlocked(entry.requirement)
            if alloc is not None:
                self._waiting_queue.pop(i)
                entry.allocation = alloc
                entry.event.set()
                return

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
