"""Yantra - Resource & Execution Manager for Sarathi V2.

Exposes:
- Yantra: Single public interface for compatible hardware allocation, release, and approved capability execution.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING

from sarathi.sankalpa import (
    Capability,
    DeviceRequirement,
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
    def default_inventory(cls) -> DeviceInventory:
        """Return the factual default hardware inventory."""
        return DeviceInventory.default_inventory()

    def __init__(self, inventory: DeviceInventory, darpana: Darpana | None = None) -> None:
        if not isinstance(inventory, DeviceInventory):
            raise TypeError(f"inventory must be a DeviceInventory instance, got {type(inventory).__name__}.")
        if darpana is not None:
            from sarathi.darpana import Darpana as DarpanaService

            if not isinstance(darpana, DarpanaService):
                raise TypeError(f"darpana must be a Darpana instance or None, got {type(darpana).__name__}.")

        self._allocator = _ResourceAllocator(inventory)
        self._darpana: Darpana | None = darpana

    @property
    def inventory(self) -> DeviceInventory:
        """Return the active immutable device inventory."""
        return self._allocator.inventory

    @property
    def darpana(self) -> Darpana | None:
        """Return the injected Darpana telemetry service, if present."""
        return self._darpana

    def allocate(
        self,
        requirement: DeviceRequirement,
        context: ExecutionContext | None = None,
    ) -> Allocation:
        """Allocate an execution device slot for a capability requirement.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If capacity is exhausted.
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
            return self._allocator.allocate(requirement)

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
        try:
            if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            scope = (
                self._darpana.time_scope(
                    context=context,
                    phase_name="capability_execution",
                    component=capability.declaration.plugin_id,
                    attributes={
                        "capability_id": capability.declaration.capability_id,
                        "device_id": allocation.device_id,
                        "device_type": allocation.device_type.value,
                    },
                )
                if self._darpana is not None
                else nullcontext()
            )
            with scope:
                result = capability.execute(request=request, context=context, prior_result=prior_result)

            if not isinstance(result, Result):
                raise TypeError(
                    f"Capability '{capability.declaration.capability_id}' execute() must return a Result instance, "
                    f"got {type(result).__name__}."
                )
            return result
        finally:
            self.release(allocation, context=context)
