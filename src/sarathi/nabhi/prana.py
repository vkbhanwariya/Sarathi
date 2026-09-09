"""Deprecated compatibility view for the old Prana lifecycle API.

Lifecycle ownership moved to Agni. This adapter exists only so older callers can
transition without keeping a second lifecycle implementation.
"""

from __future__ import annotations

from typing import Any


class Prana:
    """Thin compatibility adapter delegating lifecycle operations to Agni."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    @property
    def _components(self) -> dict[str, Any]:
        return self._owner._components

    def register(self, component_id: str, component: Any) -> None:
        self._owner.register_component(component_id, component)

    def start_all(self) -> None:
        self._owner.start()

    def close_all(self) -> None:
        self._owner.close()

    def registered_ids(self) -> tuple[str, ...]:
        return self._owner.registered_component_ids()

    def started_ids(self) -> tuple[str, ...]:
        return self._owner.started_component_ids()

    def __len__(self) -> int:
        return len(self._owner._components)
