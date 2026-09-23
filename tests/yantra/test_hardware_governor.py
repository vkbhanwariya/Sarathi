"""Unit tests for Yantra Global Hardware Governor & MemoryLeaseGuard."""

from __future__ import annotations

import threading
import time

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import DeviceType
from sarathi.yantra import DeviceInfo, DeviceInventory, MemoryLease, MemoryLeaseGuard, Yantra


def test_memory_lease_guard_basic_lifecycle() -> None:
    """MemoryLeaseGuard successfully grants a lease within budget and releases it on exit."""
    guard = MemoryLeaseGuard(
        total_phys_bytes=16 * 1024 * 1024 * 1024,
        max_budget_bytes=8 * 1024 * 1024 * 1024,
        min_headroom_bytes=1024 * 1024,
    )

    lease_bytes = 512 * 1024 * 1024  # 512 MB
    assert guard.active_leased_bytes == 0

    with guard.lease(lease_bytes) as lease:
        assert isinstance(lease, MemoryLease)
        assert lease.bytes_granted == lease_bytes
        assert guard.active_leased_bytes == lease_bytes
        status = guard.get_status()
        assert status["active_leased_bytes"] == lease_bytes
        assert status["active_lease_count"] == 1

    assert guard.active_leased_bytes == 0
    status_after = guard.get_status()
    assert status_after["active_leased_bytes"] == 0
    assert status_after["active_lease_count"] == 0


def test_memory_lease_guard_rejects_exorbitant_request() -> None:
    """Requesting more memory than max_budget_bytes immediately raises RESOURCE_UNAVAILABLE."""
    guard = MemoryLeaseGuard(
        total_phys_bytes=8 * 1024 * 1024 * 1024,
        max_budget_bytes=4 * 1024 * 1024 * 1024,
    )

    with pytest.raises(DoshError) as exc_info:
        with guard.lease(5 * 1024 * 1024 * 1024):
            pass

    assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE
    assert "exceeds maximum configured budget" in str(exc_info.value)


def test_memory_lease_guard_invalid_inputs() -> None:
    """Non-positive or non-integer bytes_needed raise ValueError."""
    guard = MemoryLeaseGuard(max_budget_bytes=1024 * 1024 * 1024)

    with pytest.raises(ValueError):
        with guard.lease(0):
            pass

    with pytest.raises(ValueError):
        with guard.lease(-100):
            pass

    with pytest.raises(ValueError):
        with guard.lease(True):  # bool is subclass of int
            pass


def test_memory_lease_guard_saturation_and_timeout() -> None:
    """When budget is fully leased, subsequent request times out and raises RESOURCE_UNAVAILABLE."""
    budget = 100 * 1024 * 1024  # 100 MB
    guard = MemoryLeaseGuard(
        total_phys_bytes=1024 * 1024 * 1024,
        max_budget_bytes=budget,
        min_headroom_bytes=0,
    )

    with guard.lease(80 * 1024 * 1024):  # 80 MB leased, 20 MB remaining
        # Requesting 30 MB exceeds remaining 20 MB -> should time out
        with pytest.raises(DoshError) as exc_info:
            with guard.lease(30 * 1024 * 1024, timeout=0.1):
                pass

        assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE
        assert "Memory saturated" in str(exc_info.value)


def test_memory_lease_guard_concurrent_queue_and_release() -> None:
    """A waiter successfully acquires the lease as soon as a prior holder finishes."""
    budget = 100 * 1024 * 1024
    guard = MemoryLeaseGuard(
        total_phys_bytes=1024 * 1024 * 1024,
        max_budget_bytes=budget,
        min_headroom_bytes=0,
    )

    events: list[str] = []

    def task1() -> None:
        with guard.lease(80 * 1024 * 1024):
            events.append("t1_acquired")
            time.sleep(0.15)
            events.append("t1_releasing")

    def task2() -> None:
        time.sleep(0.03)  # Ensure task1 runs first
        with guard.lease(50 * 1024 * 1024, timeout=2.0):
            events.append("t2_acquired")

    th1 = threading.Thread(target=task1)
    th2 = threading.Thread(target=task2)
    th1.start()
    th2.start()
    th1.join(timeout=3.0)
    th2.join(timeout=3.0)

    assert events == ["t1_acquired", "t1_releasing", "t2_acquired"]
    assert guard.active_leased_bytes == 0


def test_memory_lease_guard_close_aborts_waiting() -> None:
    """Closing MemoryLeaseGuard wakes and aborts any waiting threads with RESOURCE_UNAVAILABLE."""
    guard = MemoryLeaseGuard(max_budget_bytes=50 * 1024 * 1024)
    guard.close()
    assert guard.is_closed is True

    with pytest.raises(DoshError) as exc_info:
        with guard.lease(10 * 1024 * 1024):
            pass
    assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE


def test_yantra_core_budget_and_memory_lease_integration() -> None:
    """Yantra exposes core budgets tailored to hardware profiles and memory lease manager."""
    inv = DeviceInventory([
        DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=14),
    ])
    yantra = Yantra(inv)

    try:
        # Silicon-aware core budget
        assert yantra.get_core_budget("translation") == 4  # P-cores
        assert yantra.get_core_budget("neural") == 4
        assert yantra.get_core_budget("layout") == 8  # E-cores
        assert yantra.get_core_budget("xberg") == 8
        assert yantra.get_core_budget("ocr") == 4  # Feeder threads
        assert yantra.get_core_budget("unknown_workload") == 4

        # Memory lease integration
        with yantra.lease_memory(100 * 1024 * 1024) as lease:
            assert isinstance(lease, MemoryLease)
            assert lease.bytes_granted == 100 * 1024 * 1024
            assert yantra.memory_guard.active_leased_bytes >= 100 * 1024 * 1024

        assert yantra.memory_guard.active_leased_bytes == 0
    finally:
        yantra.close()
        assert yantra.is_closed is True
        assert yantra.memory_guard.is_closed is True
