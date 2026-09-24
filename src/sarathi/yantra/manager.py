"""Yantra - Resource & Execution Manager for Sarathi.

Exposes:
- Yantra: Single public interface for compatible hardware allocation, release, and approved capability execution.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    Capability,
    DeviceRequirement,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    Request,
    Result,
)
from sarathi.yantra.devices import DeviceInventory
from sarathi.yantra.resources import (
    Allocation,
    MemoryLeaseGuard,
    _ResourceAllocator,
)

if TYPE_CHECKING:
    from sarathi.darpana import Darpana


def get_neural_thread_topology(
    execution_binding: ExecutionBinding | None = None,
    device: str = "cpu",
) -> tuple[int, int]:
    """Compute recommended (intra_threads, inter_threads) for neural inference.

    Tuned for the primary hardware profile (Intel Core Ultra 5 125H):
    - Multi-core P-core allocation (intra_threads=4 on AVX2/AVX-VNNI)
    - Clean fallbacks for generic CPU / GPU configurations.
    """
    if device is not None:
        dev_str = str(device).lower()
    elif execution_binding is not None and (
        execution_binding.device_type == DeviceType.GPU
        or (execution_binding.backend and "gpu" in execution_binding.backend.lower())
    ):
        dev_str = "gpu"
    else:
        dev_str = "cpu"

    approved = execution_binding.approved_concurrency if execution_binding is not None else 0

    if dev_str != "cpu":
        inter_threads = max(1, approved) if approved > 0 else 1
        return 0, inter_threads

    cpu_fn = getattr(os, "process_cpu_count", None)
    cpu_count = cpu_fn() if callable(cpu_fn) else os.cpu_count() or 4
    default_concurrency = max(1, min(4, cpu_count // 4))
    eff_approved = approved if approved > 0 else default_concurrency

    intra_threads = 4 if cpu_count >= 12 else max(2, min(4, (cpu_count + 1) // max(1, eff_approved)))
    inter_threads = max(1, min(2 if intra_threads >= 4 else 4, eff_approved))
    return intra_threads, inter_threads


class Yantra:
    """Resource and execution manager for hardware allocation and capability execution."""

    @classmethod
    def default_inventory(
        cls,
        detect_accelerators: bool = False,
        *,
        gpu_capacity_per_device: int = 4,
        npu_capacity_per_device: int = 2,
        cpu_capacity: int | None = None,
    ) -> DeviceInventory:
        """Return the factual default hardware inventory."""
        return DeviceInventory.default_inventory(
            detect_accelerators=detect_accelerators,
            gpu_capacity_per_device=gpu_capacity_per_device,
            npu_capacity_per_device=npu_capacity_per_device,
            cpu_capacity=cpu_capacity,
        )

    def __init__(
        self,
        inventory: DeviceInventory,
        darpana: Darpana | None = None,
        max_queue_depth: int = 64,
    ) -> None:
        if not isinstance(inventory, DeviceInventory):
            raise TypeError(f"inventory must be a DeviceInventory instance, got {type(inventory).__name__}.")
        if darpana is not None:
            from sarathi.darpana import Darpana as DarpanaService

            if not isinstance(darpana, DarpanaService):
                raise TypeError(f"darpana must be a Darpana instance or None, got {type(darpana).__name__}.")

        self._allocator = _ResourceAllocator(inventory, max_queue_depth=max_queue_depth)
        self._memory_guard = MemoryLeaseGuard()
        self._darpana: Darpana | None = darpana

        # Decouple host worker pool from accelerator capacities:
        # Size host Python thread pool to physical CPU capacity (bounded between 1 and 16).
        host_cpu = inventory.get_device("cpu-0")
        if host_cpu is not None:
            host_cap = host_cpu.capacity
        elif inventory.devices:
            host_cap = inventory.devices[0].capacity
        else:
            host_cap = 4
        self._max_workers: int = max(1, min(16, host_cap))
        self._executor: ThreadPoolExecutor | None = None
        self._is_started: bool = False
        self._is_closed: bool = False
        self._lifecycle_lock: threading.Lock = threading.Lock()

    @property
    def inventory(self) -> DeviceInventory:
        """Return the active immutable device inventory."""
        return self._allocator.inventory

    @property
    def darpana(self) -> Darpana | None:
        """Return the injected Darpana telemetry service, if present."""
        return self._darpana

    @property
    def max_workers(self) -> int:
        """Return the maximum worker concurrency capacity of the execution pool."""
        return self._max_workers

    @property
    def memory_guard(self) -> MemoryLeaseGuard:
        """Return the active global memory governor."""
        return self._memory_guard

    def lease_memory(self, bytes_needed: int, timeout: float | None = None):
        """Acquire a temporary memory reservation from the global hardware governor."""
        return self._memory_guard.lease(bytes_needed=bytes_needed, timeout=timeout)

    def get_core_budget(self, workload: str) -> int:
        """Return recommended concurrency budget tailored for the host silicon topology.

        Tuned for the primary hardware profile (Intel Core Ultra 5 125H: 14 cores, 4P + 8E + 2LPE):
        - 'translation' / 'neural': 4 cores (dedicated to P-cores for AVX2/AVX-VNNI throughput)
        - 'layout' / 'native' / 'xberg' / 'font_conversion': 8 cores (parallel Rayon/Rust or CPU processing on E-cores)
        - 'ocr' / 'openvino': 4 feeder threads (submitting inference frames to Intel Arc iGPU)
        - Fallback / default: min(self._max_workers, 4)
        """
        norm = str(workload).strip().lower()
        if norm in ("translation", "neural"):
            return max(1, min(self._max_workers, 4))
        if norm in ("layout", "native", "xberg", "font_conversion"):
            return max(1, min(self._max_workers, 8))
        if norm in ("ocr", "openvino"):
            return max(1, min(self._max_workers, 4))
        return max(1, min(self._max_workers, 4))

    def resolve_preferred_binding(
        self,
        capability: Any | None = None,
        requirement: DeviceRequirement | None = None,
    ) -> ExecutionBinding | None:
        """Resolve the preferred ExecutionBinding for a capability or device requirement."""
        req = requirement
        if req is None and capability is not None:
            req = getattr(getattr(capability, "declaration", None), "device_requirement", None)
        return self._allocator.resolve_preferred_binding(requirement=req)

    def get_thread_topology(
        self,
        workload: str = "translation",
        execution_binding: ExecutionBinding | None = None,
        device: str = "cpu",
    ) -> tuple[int, int]:
        """Compute recommended (intra_threads, inter_threads) for neural inference."""
        return get_neural_thread_topology(execution_binding=execution_binding, device=device)

    @property
    def is_started(self) -> bool:
        """Return True if Yantra execution pool has started."""
        with self._lifecycle_lock:
            return self._is_started

    @property
    def is_closed(self) -> bool:
        """Return True if Yantra has been closed."""
        with self._lifecycle_lock:
            return self._is_closed

    def start(self) -> None:
        """Start Yantra and initialize bounded execution pool under Agni lifecycle."""
        with self._lifecycle_lock:
            if self._is_closed:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Cannot start Yantra; resource manager is closed.",
                )
            if self._is_started:
                return
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers,
                    thread_name_prefix="yantra-worker",
                )
            self._is_started = True

    def close(self) -> None:
        """Gracefully close Yantra, shutting down worker pool and clearing allocator state.

        Yantra close is strictly terminal.
        """
        with self._lifecycle_lock:
            if self._is_closed:
                return
            self._is_closed = True
            self._is_started = False
            exec_to_close = self._executor
            self._executor = None

        # Close allocator FIRST so any pending/new admissions are rejected immediately
        self._allocator.close()
        self._memory_guard.close()

        if exec_to_close is not None:
            exec_to_close.shutdown(wait=True, cancel_futures=True)

    def allocate(
        self,
        requirement: DeviceRequirement,
        context: ExecutionContext | None = None,
        timeout: float | None = None,
    ) -> Allocation:
        """Allocate an execution device slot for a capability requirement.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If capacity is exhausted or timeout reached.
            DoshError(FailureCode.OPERATION_CANCELLED): If context cancellation is requested while queued.
            TypeError: If requirement is not a DeviceRequirement.
        """
        with self._lifecycle_lock:
            if self._is_closed:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Cannot allocate; Yantra is closed.",
                )
        if not isinstance(requirement, DeviceRequirement):
            raise TypeError(f"requirement must be a DeviceRequirement instance, got {type(requirement).__name__}.")
        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

        scope = (
            self._darpana.time_scope(
                context=context,
                phase_name="allocation",
                component="yantra.allocator",
                attributes={
                    "preferred_devices": tuple(d.value for d in requirement.preferred_devices),
                    "priority": requirement.priority,
                    "parallelizable": requirement.parallelizable,
                    "inference_slots": requirement.inference_slots,
                },
            )
            if self._darpana is not None and context is not None
            else nullcontext()
        )
        with scope:
            return self._allocator.allocate(requirement, context=context, timeout=timeout)

    def execute_subtasks(
        self,
        subtasks: Sequence[Callable[[], Any]],
        context: ExecutionContext | None = None,
        max_concurrency: int | None = None,
    ) -> list[Any]:
        """Execute independent subtasks concurrently using Yantra's bounded worker pool, preserving source order.

        Concurrency is bounded by the active execution binding when one is present.
        Uses bounded in-flight sliding window scheduling so large task sets do not submit unbounded futures.
        On child failure or cancellation, settles already-running work before returning or raising.

        Raises:
            DoshError(FailureCode.OPERATION_CANCELLED): If context cancellation is requested.
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If Yantra is closed.
        """
        if not isinstance(subtasks, (list, tuple)):
            raise TypeError(f"subtasks must be a sequence, got {type(subtasks).__name__}.")

        with self._lifecycle_lock:
            if self._is_closed:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Cannot execute subtasks; Yantra is closed.",
                )

        if not subtasks:
            return []

        if context is not None and context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        effective_concurrency = self._max_workers
        if (
            context is not None
            and context.execution_binding is not None
            and context.execution_binding.approved_concurrency > 0
        ):
            effective_concurrency = min(effective_concurrency, context.execution_binding.approved_concurrency)
        if max_concurrency is not None and max_concurrency > 0:
            effective_concurrency = min(effective_concurrency, max_concurrency)

        target_dev_id: str | None = None
        if context is not None and context.execution_binding is not None:
            target_dev_id = context.execution_binding.device_id

        # Sequential execution if only 1 task or effective_concurrency == 1
        if len(subtasks) == 1 or effective_concurrency == 1:
            results = []
            for task in subtasks:
                if (
                    context is not None
                    and context.cancellation_token is not None
                    and context.cancellation_token.is_cancelled
                ):
                    context.cancellation_token.check_cancelled()
                if target_dev_id is not None:
                    with self._allocator.device_permit(target_dev_id):
                        results.append(task())
                else:
                    results.append(task())
            return results

        with self._lifecycle_lock:
            if self._is_closed:
                raise DoshError(
                    code=FailureCode.RESOURCE_UNAVAILABLE,
                    message="Cannot execute subtasks; Yantra is closed.",
                )
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers,
                    thread_name_prefix="yantra-subtask",
                )
                self._is_started = True
            executor = self._executor

        # Bounded sliding window: at most effective_concurrency in flight
        window_size = max(1, min(len(subtasks), effective_concurrency))

        ordered_results: list[Any] = [None] * len(subtasks)
        in_flight: dict[Future[Any], int] = {}
        next_task_idx = 0
        terminal_error: BaseException | None = None

        def _cancel_and_drain(settle: bool = True) -> None:
            # Cancel all unstarted in-flight futures
            for fut in list(in_flight.keys()):
                fut.cancel()
            if settle:
                # Await all futures that were already running so device work settles completely
                for fut in list(in_flight.keys()):
                    try:
                        fut.result()
                    except BaseException:
                        pass
            in_flight.clear()

        try:
            while next_task_idx < len(subtasks) or in_flight:
                # 1. Check cancellation before submitting more work
                if (
                    context is not None
                    and context.cancellation_token is not None
                    and context.cancellation_token.is_cancelled
                ):
                    _cancel_and_drain(settle=True)
                    context.cancellation_token.check_cancelled()

                # 2. Fill window up to bounded limit
                while next_task_idx < len(subtasks) and len(in_flight) < window_size and terminal_error is None:
                    idx = next_task_idx
                    raw_fn = subtasks[idx]
                    if target_dev_id is not None:

                        def _make_runner(fn: Callable[[], Any], dev_key: str) -> Callable[[], Any]:
                            def _run() -> Any:
                                with self._allocator.device_permit(dev_key):
                                    return fn()

                            return _run

                        task_fn = _make_runner(raw_fn, target_dev_id)
                    else:
                        task_fn = raw_fn
                    try:
                        fut = executor.submit(task_fn)
                        in_flight[fut] = idx
                        next_task_idx += 1
                    except RuntimeError as re:
                        raise DoshError(
                            code=FailureCode.RESOURCE_UNAVAILABLE,
                            message="Cannot schedule subtasks; Yantra executor is shutting down.",
                        ) from re

                if not in_flight:
                    break

                # 3. Wait for at least one in-flight future to complete (poll boundedly to check cancellation)
                done, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED, timeout=0.05)
                for f in done:
                    task_idx = in_flight.pop(f)
                    try:
                        res = f.result()
                        ordered_results[task_idx] = res
                    except BaseException as exc:
                        if terminal_error is None:
                            terminal_error = exc

                if (
                    context is not None
                    and context.cancellation_token is not None
                    and context.cancellation_token.is_cancelled
                ):
                    _cancel_and_drain(settle=True)
                    context.cancellation_token.check_cancelled()

                if terminal_error is not None:
                    _cancel_and_drain(settle=True)
                    raise terminal_error

        except BaseException:
            _cancel_and_drain(settle=True)
            raise

        if context is not None and context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        return ordered_results

    def release(
        self,
        allocation: Allocation,
        context: ExecutionContext | None = None,
    ) -> None:
        """Release an allocated device slot back to the manager.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If allocation is unknown/foreign/tampered/double-released.
            TypeError: If allocation is not an Allocation instance.
        """
        if not isinstance(allocation, Allocation):
            raise TypeError(f"allocation must be an Allocation instance, got {type(allocation).__name__}.")
        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

        scope = (
            self._darpana.time_scope(
                context=context,
                phase_name="release",
                component="yantra.allocator",
                attributes={
                    "device_id": allocation.device_id,
                    "device_type": allocation.device_type.value,
                    "granted_units": allocation.granted_units,
                },
            )
            if self._darpana is not None and context is not None
            else nullcontext()
        )
        with scope:
            self._allocator.release(allocation)

    def execute(
        self,
        capability: Capability,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
        timeout: float | None = None,
    ) -> Result:
        """Execute a capability after allocating compatible hardware, releasing slot in finally.

        Args:
            capability: Conforming executable Capability instance.
            request: Canonical processing request.
            context: Runtime execution context.
            prior_result: Optional result from preceding pipeline stage.
            timeout: Optional allocation timeout in seconds (defaults to 30.0s).

        Returns:
            Canonical Result from capability execution.

        Raises:
            TypeError: If arguments are of invalid type or capability returns non-Result.
            DoshError: If hardware allocation fails or capability fails.
        """
        if not isinstance(capability, Capability):
            raise TypeError(f"capability must be a Capability instance, got {type(capability).__name__}.")
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")
        if prior_result is not None and not isinstance(prior_result, Result):
            raise TypeError(f"prior_result must be a Result instance or None, got {type(prior_result).__name__}.")

        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        alloc_timeout = timeout if timeout is not None else 30.0
        dev_req = getattr(getattr(capability, "declaration", None), "device_requirement", None)
        allocation = self.allocate(
            dev_req,
            context=context,
            timeout=alloc_timeout,
        )
        memory_lease = None
        if dev_req is not None and dev_req.estimated_memory_bytes and dev_req.estimated_memory_bytes > 0:
            try:
                memory_lease = self._memory_guard.lease(
                    bytes_needed=dev_req.estimated_memory_bytes,
                    timeout=alloc_timeout,
                )
            except Exception:
                pass

        exec_exc: BaseException | None = None
        try:
            if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            # Construct factual ExecutionBinding directly from allocator reservation
            binding = ExecutionBinding(
                device_id=allocation.device_id,
                device_type=allocation.device_type,
                backend=allocation.backend,
                backend_device_id=allocation.backend_device_id,
                is_spillover=allocation.is_spillover,
                approved_concurrency=allocation.granted_units,
            )
            bound_context = context.with_execution_binding(binding)

            scope = (
                self._darpana.time_scope(
                    context=bound_context,
                    phase_name="capability_execution",
                    component=capability.declaration.plugin_id,
                    attributes={
                        "capability_id": capability.declaration.capability_id,
                        "device_id": allocation.device_id,
                        "device_type": allocation.device_type.value,
                        "backend": binding.backend,
                        "is_spillover": binding.is_spillover,
                        "granted_units": allocation.granted_units,
                        "approved_concurrency": binding.approved_concurrency,
                    },
                )
                if self._darpana is not None
                else nullcontext()
            )
            with scope:
                result = capability.execute(request=request, context=bound_context, prior_result=prior_result)

            if not isinstance(result, Result):
                raise TypeError(
                    f"Capability '{capability.declaration.capability_id}' execute() must return a Result instance, "
                    f"got {type(result).__name__}."
                )
            return result

        except BaseException as exc:
            exec_exc = exc
            raise
        finally:
            if memory_lease is not None:
                try:
                    memory_lease.release()
                except Exception:
                    pass
            try:
                self.release(allocation, context=context)
            except Exception as rel_err:
                if exec_exc is not None:
                    exec_exc.add_note(f"Additionally, resource release failed: {type(rel_err).__name__}")
                    if self._darpana is not None:
                        from sarathi.darpana import MarutiRecord

                        self._darpana.record_maruti(
                            MarutiRecord(
                                run_id=context.run_id,
                                request_id=context.request_id,
                                trace_id=context.trace_id,
                                span_id=context.span_id,
                                phase_name="device_release_failure",
                                component="yantra.manager",
                                timestamp_utc=datetime.now(UTC).isoformat(),
                                duration_ns=0,
                                outcome="failure",
                                attributes={"error_type": type(rel_err).__name__},
                            )
                        )
                else:
                    raise rel_err
