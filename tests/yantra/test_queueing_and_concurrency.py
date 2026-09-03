"""Unit and concurrency tests for Yantra bounded queueing, priority, cancellation, and lifecycle."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    DeviceRequirement,
    DeviceType,
    ExecutionContext,
    ExecutionProfile,
)
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class TestQueueingAndWaiting:
    def test_queue_waits_and_wakes_on_release(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=1)])
        yantra = Yantra(inventory)
        req = DeviceRequirement(preferred_devices=(DeviceType.CPU,), supported_devices=(DeviceType.CPU,))

        alloc1 = yantra.allocate(req)
        assert alloc1.device_id == "cpu-0"

        thread2_alloc = None
        thread2_error = None

        def worker() -> None:
            nonlocal thread2_alloc, thread2_error
            try:
                thread2_alloc = yantra.allocate(req, timeout=2.0)
            except Exception as e:
                thread2_error = e

        t = threading.Thread(target=worker)
        t.start()

        # Brief delay to allow worker to queue and enter wait state
        time.sleep(0.1)
        assert t.is_alive()
        assert thread2_alloc is None

        # Release alloc1 -> worker thread should be dispatched
        yantra.release(alloc1)
        t.join(timeout=2.0)

        assert not t.is_alive()
        assert thread2_error is None
        assert thread2_alloc is not None
        assert thread2_alloc.device_id == "cpu-0"

        # Cleanup
        yantra.release(thread2_alloc)

    def test_bounded_queue_depth_exceeded_raises_immediately(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=1)])
        yantra = Yantra(inventory, max_queue_depth=2)
        req = DeviceRequirement(preferred_devices=(DeviceType.CPU,), supported_devices=(DeviceType.CPU,))

        # Fill capacity
        alloc1 = yantra.allocate(req)

        waiters = []
        def wait_worker() -> None:
            try:
                alloc = yantra.allocate(req, timeout=0.5)
                yantra.release(alloc)
            except Exception:
                pass

        for _ in range(2):
            w = threading.Thread(target=wait_worker)
            w.start()
            waiters.append(w)

        time.sleep(0.1)

        # 4th allocation exceeds max_queue_depth=2
        with pytest.raises(DoshError) as exc_info:
            yantra.allocate(req, timeout=1.0)
        assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE
        assert "capacity exceeded" in exc_info.value.message

        # Release to let background threads finish
        yantra.release(alloc1)
        for w in waiters:
            w.join(timeout=2.0)

    def test_priority_queueing_dispatches_higher_priority_first(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=1)])
        yantra = Yantra(inventory)
        req_low = DeviceRequirement(preferred_devices=(DeviceType.CPU,), supported_devices=(DeviceType.CPU,), priority=0)
        req_high = DeviceRequirement(preferred_devices=(DeviceType.CPU,), supported_devices=(DeviceType.CPU,), priority=10)

        alloc_initial = yantra.allocate(req_low)

        dispatch_order: list[str] = []

        def worker(req: DeviceRequirement, tag: str) -> None:
            alloc = yantra.allocate(req, timeout=2.0)
            dispatch_order.append(tag)
            yantra.release(alloc)

        t_low = threading.Thread(target=worker, args=(req_low, "low"))
        t_low.start()
        time.sleep(0.05)  # Ensure t_low queues first

        t_high = threading.Thread(target=worker, args=(req_high, "high"))
        t_high.start()
        time.sleep(0.05)  # Ensure t_high queues second

        # Release initial allocation
        yantra.release(alloc_initial)

        t_high.join(timeout=2.0)
        t_low.join(timeout=2.0)

        # High priority waiter must have been dispatched before low priority waiter!
        assert dispatch_order == ["high", "low"]

    def test_cancellation_while_waiting_in_queue(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=1)])
        yantra = Yantra(inventory)
        req = DeviceRequirement(preferred_devices=(DeviceType.CPU,), supported_devices=(DeviceType.CPU,))

        alloc_blocker = yantra.allocate(req)

        cancel_token = CancellationToken()
        ctx = ExecutionContext(
            run_id="r1",
            request_id="req1",
            trace_id="t1",
            span_id="s1",
            cancellation_token=cancel_token,
        )

        caught_error: Exception | None = None

        def worker() -> None:
            nonlocal caught_error
            try:
                yantra.allocate(req, context=ctx, timeout=3.0)
            except Exception as exc:
                caught_error = exc

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.1)

        # Cancel while waiting
        cancel_token.cancel()
        t.join(timeout=2.0)

        assert not t.is_alive()
        assert isinstance(caught_error, DoshError)
        assert caught_error.code == FailureCode.EXECUTION_FAILED
        assert caught_error.context.get("cancelled") is True

        # Verify allocator didn't leak slots
        yantra.release(alloc_blocker)
        alloc_fresh = yantra.allocate(req)
        assert alloc_fresh.device_id == "cpu-0"
        yantra.release(alloc_fresh)

    def test_allocation_timeout_raises_resource_unavailable(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=1)])
        yantra = Yantra(inventory)
        req = DeviceRequirement(preferred_devices=(DeviceType.CPU,), supported_devices=(DeviceType.CPU,))

        alloc = yantra.allocate(req)
        try:
            with pytest.raises(DoshError) as exc_info:
                yantra.allocate(req, timeout=0.1)
            assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE
            assert "Timed out" in exc_info.value.message
        finally:
            yantra.release(alloc)


class TestYantraExecuteSubtasks:
    def test_subtasks_empty_and_single(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2)])
        yantra = Yantra(inventory)

        assert yantra.execute_subtasks([]) == []
        assert yantra.execute_subtasks([lambda: 42]) == [42]

    def test_subtasks_parallel_execution_preserves_source_order(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4)])
        yantra = Yantra(inventory)

        def slow_task(val: int, delay: float) -> int:
            time.sleep(delay)
            return val

        # Tasks with variable delays: task 0 takes longest, task 3 finishes fastest
        tasks = [
            lambda: slow_task(0, 0.15),
            lambda: slow_task(1, 0.10),
            lambda: slow_task(2, 0.05),
            lambda: slow_task(3, 0.01),
        ]

        results = yantra.execute_subtasks(tasks)
        # Results MUST strictly preserve source order [0, 1, 2, 3]!
        assert results == [0, 1, 2, 3]

    def test_subtasks_cancellation(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2)])
        yantra = Yantra(inventory)

        cancel_token = CancellationToken()
        cancel_token.cancel()
        ctx = ExecutionContext(run_id="r1", request_id="req1", trace_id="t1", span_id="s1", cancellation_token=cancel_token)

        with pytest.raises(DoshError) as exc_info:
            yantra.execute_subtasks([lambda: 1, lambda: 2], context=ctx)
        assert exc_info.value.code == FailureCode.EXECUTION_FAILED
        assert exc_info.value.context.get("cancelled") is True


class TestYantraLifecycle:
    def test_yantra_start_and_close(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2)])
        yantra = Yantra(inventory)
        assert yantra.is_started is False
        assert yantra.is_closed is False

        yantra.start()
        assert yantra.is_started is True
        assert yantra.is_closed is False

        yantra.close()
        assert yantra.is_started is False
        assert yantra.is_closed is True

        # Operations after close are rejected
        req = DeviceRequirement(preferred_devices=(DeviceType.CPU,), supported_devices=(DeviceType.CPU,))
        with pytest.raises(DoshError) as exc_info:
            yantra.allocate(req)
        assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE

        with pytest.raises(DoshError) as exc_info:
            yantra.execute_subtasks([lambda: 1])
        assert exc_info.value.code == FailureCode.RESOURCE_UNAVAILABLE
