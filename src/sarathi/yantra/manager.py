"""Yantra - Resource & Execution Manager for Sarathi V2.

Exposes:
- Yantra: Single public interface for compatible hardware allocation, release, and approved capability execution.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
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
from sarathi.yantra.resources import Allocation, _ResourceAllocator

if TYPE_CHECKING:
    from sarathi.darpana import Darpana


class Yantra:
    """Resource and execution manager for hardware allocation and capability execution."""

    @classmethod
    def default_inventory(cls, detect_accelerators: bool = False) -> DeviceInventory:
        """Return the factual default hardware inventory."""
        return DeviceInventory.default_inventory(detect_accelerators=detect_accelerators)

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
        self._darpana: Darpana | None = darpana
        self._max_workers: int = max(1, sum(dev.capacity for dev in inventory.devices))
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
        """Start Yantra and initialize bounded execution pool under Prana lifecycle."""
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

        if exec_to_close is not None:
            exec_to_close.shutdown(wait=True, cancel_futures=True)
        self._allocator.close()

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

        # Sequential execution if only 1 task or max_concurrency == 1
        if len(subtasks) == 1 or max_concurrency == 1:
            results = []
            for task in subtasks:
                if context is not None and context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                    context.cancellation_token.check_cancelled()
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

        effective_concurrency = self._max_workers
        if max_concurrency is not None and max_concurrency > 0:
            effective_concurrency = min(effective_concurrency, max_concurrency)
        elif (
            context is not None
            and context.execution_binding is not None
            and context.execution_binding.approved_concurrency > 0
        ):
            effective_concurrency = min(effective_concurrency, context.execution_binding.approved_concurrency)

        # Bounded sliding window: at most effective_concurrency in flight
        window_size = max(1, min(len(subtasks), effective_concurrency))

        ordered_results: list[Any] = [None] * len(subtasks)
        in_flight: dict[Future[Any], int] = {}
        next_task_idx = 0
        terminal_error: BaseException | None = None

        def _cancel_and_drain() -> None:
            # Cancel all unstarted in-flight futures
            for fut in in_flight:
                fut.cancel()
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
                if context is not None and context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                    _cancel_and_drain()
                    context.cancellation_token.check_cancelled()

                # 2. Fill window up to bounded limit
                while next_task_idx < len(subtasks) and len(in_flight) < window_size and terminal_error is None:
                    idx = next_task_idx
                    task_fn = subtasks[idx]
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

                # 3. Wait for at least one in-flight future to complete
                from concurrent.futures import FIRST_COMPLETED, wait

                done, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED)
                for f in done:
                    task_idx = in_flight.pop(f)
                    try:
                        res = f.result()
                        ordered_results[task_idx] = res
                    except BaseException as exc:
                        if terminal_error is None:
                            terminal_error = exc

                if terminal_error is not None:
                    _cancel_and_drain()
                    raise terminal_error

        except BaseException:
            _cancel_and_drain()
            raise

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
    ) -> Result:
        """Execute a capability after allocating compatible hardware, releasing slot in finally.

        Args:
            capability: Conforming executable Capability instance.
            request: Canonical processing request.
            context: Runtime execution context.
            prior_result: Optional result from preceding pipeline stage.

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

        allocation = self.allocate(capability.declaration.device_requirement, context=context)
        exec_exc: BaseException | None = None
        try:
            if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            # Construct factual ExecutionBinding directly from allocator reservation
            dev = self.inventory.get(allocation.device_id)
            approved_concurrency = dev.capacity if dev is not None else 1
            binding = ExecutionBinding(
                device_id=allocation.device_id,
                device_type=allocation.device_type,
                backend=allocation.backend,
                backend_device_id=allocation.backend_device_id,
                is_spillover=allocation.is_spillover,
                approved_concurrency=approved_concurrency,
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
                                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                                duration_ns=0,
                                outcome="failure",
                                attributes={"error_type": type(rel_err).__name__},
                            )
                        )
                else:
                    raise rel_err
