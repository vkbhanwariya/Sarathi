"""Prana — Runtime Component Lifecycle Manager for Nabhi Kernel in Sarathi V2.

Defines:
- Prana: Explicit lifecycle coordinator for registered runtime components.

Coordinates startup and shutdown lifecycles only; contains no discovery, imports,
plugin registration, execution, worker management, telemetry, security decisions,
or global singletons.
"""

from __future__ import annotations

from typing import Any

from sarathi.dosh import DoshError, FailureCode


class Prana:
    """Explicit runtime component lifecycle coordinator."""

    def __init__(self) -> None:
        self._components: dict[str, Any] = {}
        self._attempted_ids: set[str] = set()
        self._started_ids: list[str] = []
        self._closed_ids: set[str] = set()

    def register(self, component_id: str, component: Any) -> None:
        """Register a runtime component by a stable component_id.

        The component must expose callable `start()` and `close()` methods.

        Raises:
            TypeError: If component_id is not a string, or component lacks callable start/close.
            ValueError: If component_id is empty or blank.
            DoshError(FailureCode.VALIDATION_FAILED): If component_id is already registered.
        """
        if not isinstance(component_id, str):
            raise TypeError(f"component_id must be a string, got {type(component_id).__name__}.")

        cleaned_id = component_id.strip()
        if not cleaned_id:
            raise ValueError("component_id must be a non-empty string.")

        start_fn = getattr(component, "start", None)
        close_fn = getattr(component, "close", None)
        if not callable(start_fn) or not callable(close_fn):
            raise TypeError(
                f"Component '{cleaned_id}' must expose callable 'start()' and 'close()' methods, "
                f"got {type(component).__name__}."
            )

        if cleaned_id in self._components:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Component '{cleaned_id}' is already registered.",
            )

        self._components[cleaned_id] = component

    def start_all(self) -> None:
        """Start registered components in registration order.

        A component start may be attempted only once per Prana instance.
        If a component fails to start:
        - Closes already-started components in reverse start order.
        - Re-raises the original exception unchanged with traceback preserved.
        """
        for comp_id, comp in self._components.items():
            if comp_id in self._attempted_ids:
                continue
            self._attempted_ids.add(comp_id)
            try:
                comp.start()
                self._started_ids.append(comp_id)
            except BaseException:
                self._cleanup_on_start_failure()
                raise

    def _cleanup_on_start_failure(self) -> None:
        """Close already-started components in reverse start order upon start failure."""
        for comp_id in reversed(self._started_ids):
            if comp_id in self._closed_ids:
                continue
            self._closed_ids.add(comp_id)
            comp = self._components.get(comp_id)
            if comp is not None:
                try:
                    comp.close()
                except BaseException:
                    # During start failure rollback, continue closing remaining started components
                    # while preserving the original start exception at the caller boundary.
                    pass

    def close_all(self) -> None:
        """Close only successfully started components in reverse start order.

        Calling close_all more than once is safe and does not close a component twice.
        If a component close fails:
        - Continues closing remaining started components.
        - After cleanup, raises the first close failure unchanged.
        """
        first_error: BaseException | None = None

        for comp_id in reversed(self._started_ids):
            if comp_id in self._closed_ids:
                continue
            self._closed_ids.add(comp_id)
            comp = self._components.get(comp_id)
            if comp is not None:
                try:
                    comp.close()
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc

        if first_error is not None:
            raise first_error

    def registered_ids(self) -> tuple[str, ...]:
        """Return an immutable snapshot of registered component IDs in registration order."""
        return tuple(self._components.keys())

    def started_ids(self) -> tuple[str, ...]:
        """Return an immutable snapshot of started component IDs in start order."""
        return tuple(self._started_ids)

    def __len__(self) -> int:
        return len(self._components)
