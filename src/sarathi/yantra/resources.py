"""Resource allocation engine for Yantra in Sarathi.

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
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import DeviceRequirement, DeviceType, ExecutionContext
from sarathi.yantra.devices import DeviceInfo, DeviceInventory

# Global re-entrant lock guarding PyMuPDF (MuPDF) C-level calls across concurrent worker threads.
GLOBAL_PYMUPDF_LOCK: threading.RLock = threading.RLock()


@dataclass(frozen=True, slots=True)
class Allocation:
    """Immutable reservation record for a single execution device slot."""

    allocation_id: str
    device_id: str
    device_type: DeviceType
    is_spillover: bool
    allocator_id: str
    backend: str = "cpu"
    backend_device_id: str = "CPU"
    granted_units: int = 1
    _allocator: Any = field(default=None, repr=False, compare=False)

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
        if not self.backend or not isinstance(self.backend, str):
            raise ValueError("backend must be a non-empty string.")
        if not self.backend_device_id or not isinstance(self.backend_device_id, str):
            raise ValueError("backend_device_id must be a non-empty string.")
        if not isinstance(self.granted_units, int) or isinstance(self.granted_units, bool) or self.granted_units < 1:
            raise ValueError("granted_units must be a positive integer >= 1.")

    @contextmanager
    def child_permit(self, timeout: float | None = None):
        """Acquire an elastic child execution permit from the allocated device's capacity pool."""
        if self._allocator is None:
            yield
            return
        with self._allocator.device_permit(self.device_id, timeout=timeout):
            yield


def get_system_memory() -> tuple[int, int]:
    """Return factual (total_physical_bytes, available_physical_bytes) for the host system."""
    import os

    # 1. Windows kernel32 GlobalMemoryStatusEx
    try:
        import ctypes

        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "kernel32"):
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullTotalPhys), int(stat.ullAvailPhys)
    except Exception:
        pass

    # 2. POSIX sysconf fallback
    if hasattr(os, "sysconf"):
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            avail_pages = os.sysconf("SC_AVPHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if (
                isinstance(pages, int)
                and isinstance(avail_pages, int)
                and isinstance(page_size, int)
                and pages > 0
                and page_size > 0
            ):
                return pages * page_size, avail_pages * page_size
        except Exception:
            pass

    # 3. Reference hardware default (24 GB physical, 12 GB available)
    return 24 * 1024 * 1024 * 1024, 12 * 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class MemoryLease:
    """Immutable record of an approved memory lease."""

    lease_id: str
    bytes_granted: int
    created_at_mono: float


class MemoryLeaseGuard:
    """Thread-safe global memory governor preventing process crash and out-of-memory errors.

    Guards against memory saturation across concurrent rasterization, neural translation
    inference, large tabular Polars extractions, and OCR operations.
    Enforces an upper process memory budget (default 75% of physical RAM, or ~18 GiB on 24 GB host)
    and preserves strict minimum headroom for the OS and background services.
    """

    def __init__(
        self,
        total_phys_bytes: int | None = None,
        max_budget_bytes: int | None = None,
        min_headroom_bytes: int = 3 * 1024 * 1024 * 1024,
    ) -> None:
        tot, _ = get_system_memory()
        self._total_phys: int = total_phys_bytes if total_phys_bytes is not None else tot
        if max_budget_bytes is not None:
            self._max_budget: int = max_budget_bytes
        else:
            self._max_budget = int(self._total_phys * 0.75)

        self._min_headroom: int = min_headroom_bytes
        self._lock: threading.Lock = threading.Lock()
        self._cv: threading.Condition = threading.Condition(self._lock)
        self._active_leases: dict[str, int] = {}
        self._counter: int = 0
        self._is_closed: bool = False

    @property
    def total_physical_bytes(self) -> int:
        """Return total physical system RAM in bytes."""
        return self._total_phys

    @property
    def max_budget_bytes(self) -> int:
        """Return maximum allowable process memory budget in bytes."""
        return self._max_budget

    @property
    def min_headroom_bytes(self) -> int:
        """Return minimum required free physical memory headroom in bytes."""
        return self._min_headroom

    @property
    def active_leased_bytes(self) -> int:
        """Return total bytes currently leased across active operations."""
        with self._lock:
            return sum(self._active_leases.values())

    @property
    def is_closed(self) -> bool:
        """Return True if memory guard is closed."""
        with self._lock:
            return self._is_closed

    def get_status(self) -> dict[str, int]:
        """Return current factual memory governor metrics."""
        _, avail = get_system_memory()
        with self._lock:
            leased = sum(self._active_leases.values())
            return {
                "total_physical_bytes": self._total_phys,
                "available_physical_bytes": avail,
                "active_leased_bytes": leased,
                "max_budget_bytes": self._max_budget,
                "min_headroom_bytes": self._min_headroom,
                "active_lease_count": len(self._active_leases),
            }

    @contextmanager
    def lease(self, bytes_needed: int, timeout: float | None = None):
        """Acquire a temporary memory reservation, automatically releasing on context exit.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If memory limit reached or timeout elapsed.
            ValueError: If bytes_needed <= 0.
        """
        if not isinstance(bytes_needed, int) or isinstance(bytes_needed, bool) or bytes_needed <= 0:
            raise ValueError("bytes_needed must be a positive integer.")

        if bytes_needed > self._max_budget:
            raise DoshError(
                code=FailureCode.RESOURCE_UNAVAILABLE,
                message=(
                    f"Requested memory lease ({bytes_needed / (1024 * 1024):.1f} MB) exceeds maximum "
                    f"configured budget ({self._max_budget / (1024 * 1024):.1f} MB)."
                ),
            )

        start_time = time.monotonic()
        with self._cv:
            while True:
                if self._is_closed:
                    raise DoshError(
                        code=FailureCode.RESOURCE_UNAVAILABLE,
                        message="MemoryLeaseGuard is closed.",
                    )

                curr_leased = sum(self._active_leases.values())
                _, avail_phys = get_system_memory()
                headroom_ok = (avail_phys - bytes_needed) >= self._min_headroom if avail_phys > 0 else True
                budget_ok = (curr_leased + bytes_needed) <= self._max_budget

                if budget_ok and headroom_ok:
                    self._counter += 1
                    lease_id = f"lease-{self._counter}"
                    self._active_leases[lease_id] = bytes_needed
                    break

                if timeout is not None:
                    remaining = timeout - (time.monotonic() - start_time)
                    if remaining <= 0:
                        raise DoshError(
                            code=FailureCode.RESOURCE_UNAVAILABLE,
                            message=(
                                f"Memory saturated; timed out waiting for {bytes_needed / (1024 * 1024):.1f} MB lease."
                            ),
                        )
                    self._cv.wait(timeout=remaining)
                else:
                    self._cv.wait(timeout=0.2)

        try:
            yield MemoryLease(
                lease_id=lease_id,
                bytes_granted=bytes_needed,
                created_at_mono=time.monotonic(),
            )
        finally:
            with self._cv:
                self._active_leases.pop(lease_id, None)
                self._cv.notify_all()

    def close(self) -> None:
        """Close memory guard, waking all waiting lease requests."""
        with self._cv:
            self._is_closed = True
            self._cv.notify_all()


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
        self._cv: threading.Condition = threading.Condition(self._lock)
        self._used_units: dict[str, int] = {dev.device_id: 0 for dev in inventory.devices}
        self._active_device_permits: dict[str, int] = {dev.device_id: 0 for dev in inventory.devices}
        self._active_allocations: dict[str, Allocation] = {}
        self._waiting_queue: list[_WaitEntry] = []
        self._counter: int = 0
        self._is_closed: bool = False

    @contextmanager
    def device_permit(self, device_id: str, timeout: float | None = None):
        """Acquire an elastic execution permit for the device, strictly bounded by capacity."""
        start_time = time.monotonic()
        with self._cv:
            dev = self._inventory.get_device(device_id)
            if dev is None:
                yield
                return

            while self._active_device_permits[device_id] >= dev.capacity:
                if self._is_closed:
                    raise DoshError(
                        code=FailureCode.RESOURCE_UNAVAILABLE,
                        message="Allocator is closed.",
                    )
                if timeout is not None:
                    elapsed = time.monotonic() - start_time
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        raise DoshError(
                            code=FailureCode.RESOURCE_UNAVAILABLE,
                            message=f"Device '{device_id}' capacity saturated; timed out waiting for permit.",
                        )
                    self._cv.wait(timeout=remaining)
                else:
                    self._cv.wait()

            if self._is_closed:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Allocator is closed.",
                )

            self._active_device_permits[device_id] += 1

        try:
            yield
        finally:
            with self._cv:
                curr = self._active_device_permits.get(device_id, 0)
                self._active_device_permits[device_id] = max(0, curr - 1)
                self._cv.notify_all()

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

    def get_available_capacity(self, device_id: str) -> int:
        """Return currently available unallocated slots for the given device."""
        with self._lock:
            dev = self._inventory.get_device(device_id)
            if dev is None:
                return 0
            used = self._used_units.get(device_id, 0)
            return max(0, dev.capacity - used)

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
            if (
                context is not None
                and context.cancellation_token is not None
                and context.cancellation_token.is_cancelled
            ):
                context.cancellation_token.check_cancelled()

            # 1. Check if slots are currently available (preferred then supported)
            alloc = self._try_allocate_unlocked(requirement)
            if alloc is not None:
                return alloc

            # 2. Check if ANY device in inventory could EVER satisfy this requirement
            has_compatible_device = any(self._is_device_compatible(dev, requirement) for dev in self._inventory.devices)
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
            if (
                context is not None
                and context.cancellation_token is not None
                and context.cancellation_token.is_cancelled
            ):
                with self._lock:
                    self._cleanup_abandoned_waiter_unlocked(entry)
                context.cancellation_token.check_cancelled()

            # Check timeout
            step_timeout = 0.05
            if timeout is not None:
                remaining = timeout - (time.monotonic() - start_time)
                if remaining <= 0:
                    with self._lock:
                        self._cleanup_abandoned_waiter_unlocked(entry)
                    raise DoshError(
                        code=FailureCode.RESOURCE_UNAVAILABLE,
                        message="Timed out waiting for device capacity.",
                    )
                step_timeout = min(step_timeout, remaining)

            if entry.event.wait(timeout=step_timeout):
                if (
                    context is not None
                    and context.cancellation_token is not None
                    and context.cancellation_token.is_cancelled
                ):
                    with self._lock:
                        self._cleanup_abandoned_waiter_unlocked(entry)
                    context.cancellation_token.check_cancelled()

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

    def _cleanup_abandoned_waiter_unlocked(self, entry: _WaitEntry) -> None:
        """Clean up waiter that timed out or cancelled, reclaiming dispatched slot if necessary."""
        if entry in self._waiting_queue:
            self._waiting_queue.remove(entry)
        if entry.allocation is not None:
            # Reclaim active allocation record and decrement slot count safely
            alloc_id = entry.allocation.allocation_id
            self._active_allocations.pop(alloc_id, None)
            self._release_slot_unlocked(entry.allocation)
            entry.allocation = None
            # Immediately dispatch next waiting entry that can use this capacity
            self._dispatch_waiting_unlocked()

    def release(self, allocation: Allocation) -> None:
        """Release a previously acquired allocation back to the inventory safely, dispatching next queued waiter.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If allocation is unknown, tampered, foreign, or already released.
            TypeError: If allocation is not an Allocation instance.
        """
        if not isinstance(allocation, Allocation):
            raise TypeError(f"allocation must be an Allocation instance, got {type(allocation).__name__}.")

        with self._cv:
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
            self._cv.notify_all()

    def close(self) -> None:
        """Close allocator, rejecting any queued waiters."""
        with self._cv:
            self._is_closed = True
            for entry in self._waiting_queue:
                entry.error = DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Yantra resource allocator is closed.",
                )
                entry.event.set()
            self._waiting_queue.clear()
            self._cv.notify_all()

    def _is_device_compatible(self, dev: DeviceInfo, requirement: DeviceRequirement) -> bool:
        """Check factual compatibility between device and requirement."""
        if dev.device_type not in requirement.supported_devices:
            return False

        # Check backend compatibility if requirement specifies backends
        if requirement.supported_backends:
            dev_backends = dev.supported_backends or ()
            if not any(req_b in dev_backends for req_b in requirement.supported_backends):
                return False

        # Check estimated memory capacity if device exposes memory_bytes
        if (
            requirement.estimated_memory_bytes is not None
            and dev.memory_bytes is not None
            and requirement.estimated_memory_bytes > dev.memory_bytes
        ):
            return False

        return True

    def _resolve_backend_for_device(self, dev: DeviceInfo, requirement: DeviceRequirement) -> tuple[str, str]:
        """Resolve backend and backend_device_id factually for a device."""
        dev_backends = dev.supported_backends or ()
        if requirement.supported_backends:
            # Pick first matching backend
            chosen_backend = next(
                (b for b in requirement.supported_backends if b in dev_backends),
                dev_backends[0] if dev_backends else "cpu",
            )
        else:
            chosen_backend = dev_backends[0] if dev_backends else "cpu"

        locators = dev.backend_locators
        if locators and chosen_backend in locators:
            backend_dev_id = locators[chosen_backend]
        elif dev.device_type == DeviceType.GPU:
            import re

            m = re.search(r"(\d+)", dev.device_id)
            idx_str = m.group(1) if m else "0"
            backend_dev_id = f"GPU.{idx_str}" if chosen_backend == "openvino" else idx_str
        elif dev.device_type == DeviceType.NPU:
            import re

            m = re.search(r"(\d+)", dev.device_id)
            idx_str = m.group(1) if m else ""
            backend_dev_id = f"NPU.{idx_str}" if idx_str else "NPU"
        elif dev.device_type == DeviceType.NETWORK:
            backend_dev_id = "NETWORK"
        else:
            backend_dev_id = "CPU"

        return chosen_backend, backend_dev_id

    def _try_allocate_unlocked(self, requirement: DeviceRequirement) -> Allocation | None:
        # 1. Check preferred devices in order
        for pref_type in requirement.preferred_devices:
            for dev in self._inventory.devices:
                if dev.device_type == pref_type and self._is_device_compatible(dev, requirement):
                    avail = dev.capacity - self._used_units[dev.device_id]
                    if avail > 0:
                        requested = (
                            (requirement.inference_slots if requirement.inference_slots > 1 else dev.capacity)
                            if requirement.parallelizable
                            else 1
                        )
                        granted = min(avail, requested)
                        backend, backend_dev_id = self._resolve_backend_for_device(dev, requirement)
                        return self._create_allocation(
                            dev.device_id,
                            dev.device_type,
                            is_spillover=False,
                            backend=backend,
                            backend_device_id=backend_dev_id,
                            granted_units=granted,
                        )

        # 2. Spill over through supported devices in order
        for supp_type in requirement.supported_devices:
            if supp_type in requirement.preferred_devices:
                continue
            for dev in self._inventory.devices:
                if dev.device_type == supp_type and self._is_device_compatible(dev, requirement):
                    avail = dev.capacity - self._used_units[dev.device_id]
                    if avail > 0:
                        requested = (
                            (requirement.inference_slots if requirement.inference_slots > 1 else dev.capacity)
                            if requirement.parallelizable
                            else 1
                        )
                        granted = min(avail, requested)
                        backend, backend_dev_id = self._resolve_backend_for_device(dev, requirement)
                        return self._create_allocation(
                            dev.device_id,
                            dev.device_type,
                            is_spillover=True,
                            backend=backend,
                            backend_device_id=backend_dev_id,
                            granted_units=granted,
                        )

        return None

    def _release_slot_unlocked(self, registered: Allocation) -> None:
        curr = self._used_units.get(registered.device_id, 0)
        self._used_units[registered.device_id] = max(0, curr - registered.granted_units)

    def _dispatch_waiting_unlocked(self) -> None:
        while self._waiting_queue:
            dispatched = False
            for i, entry in enumerate(self._waiting_queue):
                alloc = self._try_allocate_unlocked(entry.requirement)
                if alloc is not None:
                    self._waiting_queue.pop(i)
                    entry.allocation = alloc
                    entry.event.set()
                    dispatched = True
                    break
            if not dispatched:
                break

    def _create_allocation(
        self,
        device_id: str,
        device_type: DeviceType,
        *,
        is_spillover: bool,
        backend: str = "cpu",
        backend_device_id: str = "CPU",
        granted_units: int = 1,
    ) -> Allocation:
        self._used_units[device_id] += granted_units
        self._counter += 1
        alloc_id = f"alloc-{self._allocator_id}-{self._counter}"
        allocation = Allocation(
            allocation_id=alloc_id,
            device_id=device_id,
            device_type=device_type,
            is_spillover=is_spillover,
            allocator_id=self._allocator_id,
            backend=backend,
            backend_device_id=backend_device_id,
            granted_units=granted_units,
            _allocator=self,
        )
        self._active_allocations[alloc_id] = allocation
        return allocation
