"""Yantra — Resource & Execution Manager for Sarathi V2.

Exposes:
- Yantra: Single public interface managing hardware slot allocation and release.

Does NOT contain executor or execution APIs yet.
"""

from __future__ import annotations

from sarathi.sankalpa import (
    Capability,
    DeviceRequirement,
    ExecutionContext,
    Request,
    Result,
)
from sarathi.yantra.devices import DeviceInventory
from sarathi.yantra.resources import Allocation, _ResourceAllocator


class Yantra:
    """Resource and execution manager for hardware allocation and capability execution."""

    def __init__(self, inventory: DeviceInventory) -> None:
        if not isinstance(inventory, DeviceInventory):
            raise TypeError(f"inventory must be a DeviceInventory instance, got {type(inventory).__name__}.")
        self._allocator = _ResourceAllocator(inventory)

    @property
    def inventory(self) -> DeviceInventory:
        """Return the active immutable device inventory."""
        return self._allocator.inventory

    def allocate(self, requirement: DeviceRequirement) -> Allocation:
        """Allocate an execution device slot for a capability requirement.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If capacity is exhausted.
            TypeError: If requirement is not a DeviceRequirement.
        """
        return self._allocator.allocate(requirement)

    def release(self, allocation: Allocation) -> None:
        """Release an allocated device slot back to the manager.

        Raises:
            DoshError(FailureCode.RESOURCE_UNAVAILABLE): If allocation is unknown/foreign/tampered/double-released.
            TypeError: If allocation is not an Allocation instance.
        """
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
            DoshError: If hardware allocation fails.
        """
        if not isinstance(capability, Capability):
            raise TypeError(f"capability must be a Capability instance, got {type(capability).__name__}.")
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")
        if prior_result is not None and not isinstance(prior_result, Result):
            raise TypeError(f"prior_result must be a Result instance or None, got {type(prior_result).__name__}.")

        allocation = self.allocate(capability.declaration.device_requirement)
        try:
            result = capability.execute(request=request, context=context, prior_result=prior_result)
            if not isinstance(result, Result):
                raise TypeError(
                    f"Capability '{capability.declaration.capability_id}' execute() must return a Result instance, "
                    f"got {type(result).__name__}."
                )
            return result
        finally:
            self.release(allocation)
