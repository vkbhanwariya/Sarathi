"""Deterministic Concurrency, Race Condition, and Resource Hardening Tests for Yantra."""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    Capability,
    CapabilityDeclaration,
    DeviceRequirement,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.yantra import Allocation, DeviceInfo, DeviceInventory, Yantra
from sarathi.yantra.resources import _ResourceAllocator


class DummyCapability:
    def __init__(self, requirement: DeviceRequirement, capability_id: str = "test_cap") -> None:
        self.declaration = CapabilityDeclaration(
            capability_id=capability_id,
            plugin_id="test.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            device_requirement=requirement,
        )

    def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
        return Result(data=None)


def test_allocator_cancellation_after_dispatch_cleans_active_and_dispatches_next() -> None:
    """Proves that when a queued waiter is cancelled after dispatch, its active allocation is cleaned up
    and the next eligible waiter is immediately dispatched without leaking capacity or ghost allocations."""
    inv = DeviceInventory([DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=1)])
    allocator = _ResourceAllocator(inv, max_queue_depth=10)

    # 1. Acquire the only GPU slot
    req_gpu = DeviceRequirement(preferred_devices=(DeviceType.GPU,), supported_devices=(DeviceType.GPU,))
    alloc1 = allocator.allocate(req_gpu)
    assert alloc1.device_id == "gpu-0"
    assert allocator._used_slots["gpu-0"] == 1

    token_waiter1 = CancellationToken()
    ctx_waiter1 = ExecutionContext("r1", "req1", "t1", "s1", cancellation_token=token_waiter1)
    token_waiter2 = CancellationToken()
    ctx_waiter2 = ExecutionContext("r2", "req2", "t2", "s2", cancellation_token=token_waiter2)

    waiter1_result: list[Any] = []
    waiter2_result: list[Any] = []
    waiter2_acquired_event = threading.Event()

    def _waiter1_thread() -> None:
        try:
            alloc = allocator.allocate(req_gpu, context=ctx_waiter1, timeout=2.0)
            waiter1_result.append(alloc)
        except DoshError as e:
            waiter1_result.append(e)

    def _waiter2_thread() -> None:
        try:
            alloc = allocator.allocate(req_gpu, context=ctx_waiter2, timeout=2.0)
            waiter2_result.append(alloc)
            waiter2_acquired_event.set()
        except DoshError as e:
            waiter2_result.append(e)

    t1 = threading.Thread(target=_waiter1_thread)
    t2 = threading.Thread(target=_waiter2_thread)
    t1.start()
    t2.start()

    # Wait until both are in waiting queue
    while True:
        with allocator._lock:
            if len(allocator._waiting_queue) == 2:
                break
        time.sleep(0.01)

    # Now cancel waiter1 and release alloc1.
    token_waiter1.cancel()
    allocator.release(alloc1)

    t1.join(timeout=3.0)
    t2.join(timeout=3.0)

    # Waiter 1 must have raised EXECUTION_FAILED with cancelled=True
    assert len(waiter1_result) == 1
    assert isinstance(waiter1_result[0], DoshError)
    assert waiter1_result[0].code == FailureCode.OPERATION_CANCELLED
    assert waiter1_result[0].context.get("cancelled") is True

    # Waiter 2 must have successfully received an Allocation because waiter 1 cleaned up & dispatched next!
    assert len(waiter2_result) == 1
    assert isinstance(waiter2_result[0], Allocation)
    assert waiter2_result[0].device_id == "gpu-0"

    # Verify no ghost active allocations remain
    with allocator._lock:
        assert len(allocator._active_allocations) == 1
        assert waiter2_result[0].allocation_id in allocator._active_allocations
        assert allocator._used_slots["gpu-0"] == 1

    allocator.release(waiter2_result[0])
    with allocator._lock:
        assert len(allocator._active_allocations) == 0
        assert allocator._used_slots["gpu-0"] == 0


def test_yantra_lifecycle_is_terminal_and_rejects_restart() -> None:
    """Proves Yantra close is strictly terminal and rejects start() or execute() after close."""
    inv = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2)])
    yantra = Yantra(inv)
    yantra.start()
    assert yantra.is_started is True
    assert yantra.is_closed is False

    yantra.close()
    assert yantra.is_closed is True
    assert yantra.is_started is False

    with pytest.raises(DoshError) as exc_info:
        yantra.start()
    assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE

    with pytest.raises(DoshError) as exc_info2:
        yantra.execute_subtasks([lambda: 42])
    assert exc_info2.value.code == FailureCode.RESOURCE_UNAVAILABLE


def test_yantra_execute_subtasks_bounded_sliding_window_and_order_preservation() -> None:
    """Proves execute_subtasks maintains exact source order and bounds in-flight executions."""
    inv = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2)])
    yantra = Yantra(inv)

    active_count = 0
    max_active_observed = 0
    lock = threading.Lock()

    def make_task(i: int):
        def _task():
            nonlocal active_count, max_active_observed
            with lock:
                active_count += 1
                if active_count > max_active_observed:
                    max_active_observed = active_count
            time.sleep(0.02)
            with lock:
                active_count -= 1
            return i * 10
        return _task

    tasks = [make_task(i) for i in range(20)]
    results = yantra.execute_subtasks(tasks, max_concurrency=2)

    assert results == [i * 10 for i in range(20)]
    # Approved concurrency was 2; sliding window bounds in-flight at 2*2 = 4
    assert max_active_observed <= 4
    yantra.close()


def test_yantra_execute_subtasks_settles_running_work_on_child_failure() -> None:
    """Proves that when one subtask fails, all other in-flight subtasks are allowed to settle
    before the method returns or releases parent leases."""
    inv = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2)])
    yantra = Yantra(inv)

    child_started = threading.Event()
    child_finished = threading.Event()

    def _failing_task():
        child_started.wait()
        raise ValueError("Controlled child failure")

    def _slow_task():
        child_started.set()
        time.sleep(0.05)
        child_finished.set()
        return "slow_done"

    tasks = [_slow_task, _failing_task]
    with pytest.raises(ValueError, match="Controlled child failure"):
        yantra.execute_subtasks(tasks)

    # Slow child must have finished before execute_subtasks re-raised!
    assert child_finished.is_set()
    yantra.close()


def test_backend_compatibility_filtering_prevents_mismatch() -> None:
    """Proves that a requirement for openvino backend will not match a CUDA-only GPU device."""
    inv = DeviceInventory(
        [
            DeviceInfo(
                device_id="gpu-cuda-0",
                device_type=DeviceType.GPU,
                capacity=1,
                supported_backends=("cuda",),
            ),
            DeviceInfo(
                device_id="cpu-0",
                device_type=DeviceType.CPU,
                capacity=2,
                supported_backends=("cpu", "openvino"),
            ),
        ]
    )
    allocator = _ResourceAllocator(inv)

    # Requirement asks for GPU with OpenVINO only
    req = DeviceRequirement(
        preferred_devices=(DeviceType.GPU,),
        supported_devices=(DeviceType.GPU, DeviceType.CPU),
        supported_backends=("openvino",),
    )

    # gpu-cuda-0 does NOT support openvino, so it must spillover to cpu-0
    alloc = allocator.allocate(req)
    assert alloc.device_id == "cpu-0"
    assert alloc.is_spillover is True
    assert alloc.backend == "openvino"
    allocator.release(alloc)


def test_estimated_memory_bounds_rejection() -> None:
    """Proves factual memory capacity rejects allocation if requirement exceeds device memory."""
    inv = DeviceInventory(
        [
            DeviceInfo(
                device_id="gpu-small",
                device_type=DeviceType.GPU,
                capacity=1,
                supported_backends=("openvino",),
                memory_bytes=1000,
            ),
        ]
    )
    allocator = _ResourceAllocator(inv)

    # Asks for 5000 bytes on device that has only 1000 bytes
    req = DeviceRequirement(
        preferred_devices=(DeviceType.GPU,),
        supported_devices=(DeviceType.GPU,),
        estimated_memory_bytes=5000,
    )

    with pytest.raises(DoshError) as exc:
        allocator.allocate(req)
    assert exc.value.code == FailureCode.RESOURCE_UNAVAILABLE
