"""Dvara - Canonical Built-in Plugin Discovery and Registration for Sarathi V2.

Provides one canonical built-in registration path into Kosh.
Preflights all declarations before mutation to ensure atomic consistency.
Contains no import magic, filesystem scanning, external download, or second registry.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.kosh import Kosh
from sarathi.sankalpa import CapabilityDeclaration, ExecutionContext, PluginInfo
from sarathi.shakti.darshana.plugin import (
    CAPABILITY_DECLARATION as DARSHANA_CAPABILITY,
    PLUGIN_INFO as DARSHANA_PLUGIN,
)
from sarathi.shakti.native_extraction.plugin import (
    CAPABILITY_DECLARATION as NATIVE_CAPABILITY,
    PLUGIN_INFO as NATIVE_PLUGIN,
)
from sarathi.shakti.ocr.plugin import (
    CAPABILITY_DECLARATION as OCR_CAPABILITY,
    PLUGIN_INFO as OCR_PLUGIN,
)

if TYPE_CHECKING:
    from sarathi.darpana import Darpana


class Dvara:
    """Canonical built-in plugin discovery and registration manager."""

    def __init__(self, registry: Kosh, darpana: Darpana | None = None) -> None:
        """Initialize Dvara with an injected Kosh registry instance and optional Darpana telemetry service.

        Args:
            registry: The single canonical Kosh registry.
            darpana: Optional injected Darpana telemetry service.

        Raises:
            TypeError: If registry is not a Kosh instance, or darpana is not a Darpana instance.
        """
        if not isinstance(registry, Kosh):
            raise TypeError(f"registry must be a Kosh instance, got {type(registry).__name__}.")
        if darpana is not None:
            from sarathi.darpana import Darpana as DarpanaService

            if not isinstance(darpana, DarpanaService):
                raise TypeError(f"darpana must be a Darpana instance or None, got {type(darpana).__name__}.")

        self._registry: Kosh = registry
        self._darpana: Darpana | None = darpana

    @property
    def registry(self) -> Kosh:
        """Return the injected canonical Kosh registry."""
        return self._registry

    @property
    def darpana(self) -> Darpana | None:
        """Return the injected Darpana telemetry service, if present."""
        return self._darpana

    def register_builtins(self, context: ExecutionContext | None = None) -> tuple[str, ...]:
        """Register all built-in Shakti capability plugins into the injected Kosh registry.

        Preflights all declarations against existing registry state before mutating Kosh.
        Idempotent if identical declarations are already registered. If conflicting or
        tampered declarations are present, raises DoshError before performing any mutation.

        Args:
            context: Optional runtime ExecutionContext for telemetry correlation.

        Returns:
            Tuple of registered plugin IDs.

        Raises:
            TypeError: If context is not an ExecutionContext instance or None.
            DoshError(FailureCode.VALIDATION_FAILED): On conflicting or invalid declarations.
        """
        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

        scope = (
            self._darpana.time_scope(
                context=context,
                phase_name="bootstrap",
                component="nabhi.dvara",
                attributes={"action": "register_builtins"},
            )
            if self._darpana is not None and context is not None
            else nullcontext()
        )
        with scope:
            return self._register_builtins_internal()

    def _register_builtins_internal(self) -> tuple[str, ...]:
        builtins: list[tuple[PluginInfo, tuple[CapabilityDeclaration, ...]]] = [
            (DARSHANA_PLUGIN, (DARSHANA_CAPABILITY,)),
            (NATIVE_PLUGIN, (NATIVE_CAPABILITY,)),
            (OCR_PLUGIN, (OCR_CAPABILITY,)),
        ]

        # 1. Preflight all built-ins against existing Kosh state
        for plugin, caps in builtins:
            cap_ids = tuple(c.capability_id for c in caps)
            if set(cap_ids) != set(plugin.capabilities) or len(cap_ids) != len(plugin.capabilities):
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Declared capabilities for plugin '{plugin.plugin_id}' do not exactly match PluginInfo.capabilities.",
                )

            for cap in caps:
                if cap.plugin_id != plugin.plugin_id:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Capability '{cap.capability_id}' declared with mismatched plugin_id '{cap.plugin_id}'.",
                    )
                if cap.capability_id not in plugin.capabilities:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Capability '{cap.capability_id}' is not declared in plugin '{plugin.plugin_id}'.",
                    )

            if self._registry.has_plugin(plugin.plugin_id):
                existing_p = self._registry.get_plugin(plugin.plugin_id)
                if existing_p != plugin:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Conflicting plugin declaration already registered for '{plugin.plugin_id}'.",
                    )

            for cap in caps:
                existing_cap = self._registry.get_capability(cap.capability_id)
                if existing_cap is not None:
                    if existing_cap != cap:
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message=f"Conflicting capability declaration already registered for '{cap.capability_id}'.",
                        )
                    if existing_cap.plugin_id != plugin.plugin_id:
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message=f"Capability '{cap.capability_id}' is owned by another plugin '{existing_cap.plugin_id}'.",
                        )

        # 2. Only after the entire preflight succeeds, perform mutations
        registered_ids: list[str] = []
        for plugin, caps in builtins:
            if not self._registry.has_plugin(plugin.plugin_id):
                self._registry.register_plugin(plugin)
            for cap in caps:
                if self._registry.get_capability(cap.capability_id) is None:
                    self._registry.register_capability(cap)
            registered_ids.append(plugin.plugin_id)

        return tuple(registered_ids)
