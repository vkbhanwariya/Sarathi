"""Unit and concurrency tests for Yantra bounded queueing, priority, cancellation, and lifecycle."""

from __future__ import annotations

import threading
import time

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    DeviceRequirement,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
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
        assert caught_error.code == FailureCode.OPERATION_CANCELLED
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
        assert exc_info.value.code == FailureCode.OPERATION_CANCELLED
        assert exc_info.value.context.get("cancelled") is True

    def test_subtasks_cancellation_settles_running_tasks(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2)])
        yantra = Yantra(inventory)

        cancel_token = CancellationToken()
        ctx = ExecutionContext(run_id="r1", request_id="req1", trace_id="t1", span_id="s1", cancellation_token=cancel_token)

        started = threading.Event()
        finished = threading.Event()

        def slow_task() -> int:
            started.set()
            for _ in range(50):
                if cancel_token.is_cancelled:
                    time.sleep(0.05)
                    finished.set()
                    return 42
                time.sleep(0.01)
            finished.set()
            return 42

        def unstarted_task() -> int:
            return 99

        def cancel_trigger() -> None:
            started.wait(timeout=1.0)
            time.sleep(0.02)
            cancel_token.cancel()

        threading.Thread(target=cancel_trigger, daemon=True).start()

        with pytest.raises(DoshError) as exc_info:
            yantra.execute_subtasks([slow_task, unstarted_task], context=ctx)

        assert exc_info.value.code == FailureCode.OPERATION_CANCELLED
        # Running task MUST have settled before execute_subtasks returned!
        assert finished.is_set() is True

    def test_subtasks_concurrency_capped_by_approved_concurrency(self) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=8)])
        yantra = Yantra(inventory)

        binding = ExecutionBinding(
            device_id="cpu-0",
            device_type=DeviceType.CPU,
            backend="cpu",
            backend_device_id="cpu",
            approved_concurrency=2,
        )
        ctx = ExecutionContext(
            run_id="r1",
            request_id="req1",
            trace_id="t1",
            span_id="s1",
            execution_binding=binding,
        )

        lock = threading.Lock()
        active = 0
        max_active = 0

        def task() -> int:
            nonlocal active, max_active
            with lock:
                active += 1
                if active > max_active:
                    max_active = active
            time.sleep(0.05)
            with lock:
                active -= 1
            return 1

        results = yantra.execute_subtasks([task for _ in range(8)], context=ctx, max_concurrency=6)
        assert results == [1] * 8
        assert max_active <= 2


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

    def test_aggregate_concurrency_across_parallel_capabilities_never_exceeds_capacity(self) -> None:
        """Proves that multiple concurrent capabilities executing subtasks on the same device
        strictly share device permits and never exceed aggregate device capacity."""
        from pathlib import Path

        from sarathi.sankalpa import (
            Capability,
            CapabilityDeclaration,
            ExecutionProfile,
            InputRef,
            Request,
            Result,
        )

        inv = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4)])
        yantra = Yantra(inv)

        active_subtasks = 0
        peak_subtasks = 0
        lock = threading.Lock()

        def make_subtask(ident: str):
            def _subtask():
                nonlocal active_subtasks, peak_subtasks
                with lock:
                    active_subtasks += 1
                    if active_subtasks > peak_subtasks:
                        peak_subtasks = active_subtasks
                time.sleep(0.04)
                with lock:
                    active_subtasks -= 1
                return ident

            return _subtask

        class SubtaskRunningCapability(Capability):
            def __init__(self, cap_id: str) -> None:
                self._declaration = CapabilityDeclaration(
                    capability_id=cap_id,
                    plugin_id="test.plugin",
                    version="1.0.0",
                    supported_profiles=(ExecutionProfile.INSTANT,),
                    device_requirement=DeviceRequirement(
                        preferred_devices=(DeviceType.CPU,),
                        supported_devices=(DeviceType.CPU,),
                        parallelizable=True,
                    ),
                )

            @property
            def declaration(self) -> CapabilityDeclaration:
                return self._declaration

            def execute(
                self,
                request: Request,
                context: ExecutionContext,
                prior_result: Result | None = None,
            ) -> Result:
                tasks = [make_subtask(f"{self.declaration.capability_id}-{i}") for i in range(8)]
                results = yantra.execute_subtasks(tasks, context=context)
                return Result(data=results)

        cap_a = SubtaskRunningCapability("cap-a")
        cap_b = SubtaskRunningCapability("cap-b")

        req_a = Request(request_id="req-a", requirement="cap-a", inputs=[InputRef("in-a", Path("a.txt"), "a.txt", 1)])
        req_b = Request(request_id="req-b", requirement="cap-b", inputs=[InputRef("in-b", Path("b.txt"), "b.txt", 1)])
        ctx_a = ExecutionContext(run_id="run-a", request_id="req-a", trace_id="t-a", span_id="s-a")
        ctx_b = ExecutionContext(run_id="run-b", request_id="req-b", trace_id="t-b", span_id="s-b")

        errors: list[BaseException] = []

        def run_cap(cap, req, ctx):
            try:
                yantra.execute(cap, req, ctx)
            except BaseException as e:
                errors.append(e)

        t1 = threading.Thread(target=run_cap, args=(cap_a, req_a, ctx_a))
        t2 = threading.Thread(target=run_cap, args=(cap_b, req_b, ctx_b))

        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)

        assert not t1.is_alive()
        assert not t2.is_alive()
        assert not errors
        # Invariant: Peak concurrent subtasks across both capabilities must NEVER exceed device capacity (4)
        assert peak_subtasks <= 4
        assert peak_subtasks >= 2  # Proves parallel overlap was active
        yantra.close()
