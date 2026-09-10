"""Kosh — plugin and capability registry for the Sarathi kernel.

Kosh owns declaration registration and lookup. Agni decides which providers are
active and passes them in; Kosh does not discover or import plugins itself.
"""

from __future__ import annotations

from collections.abc import Sequence

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import CapabilityDeclaration, PluginInfo, PluginProvider


class Kosh:
    """In-memory registry storing plugin and capability declarations."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginInfo] = {}
        self._capabilities: dict[str, CapabilityDeclaration] = {}
        self._plugin_capabilities: dict[str, list[str]] = {}

    def register_providers(self, providers: Sequence[PluginProvider]) -> tuple[str, ...]:
        """Atomically register declaration metadata from a provider batch.

        The complete batch is validated before registry state is mutated. Repeating
        the same batch is idempotent; conflicting existing declarations or duplicate
        IDs inside the incoming batch are rejected.
        """
        if not isinstance(providers, Sequence):
            raise TypeError(f"providers must be a sequence, got {type(providers).__name__}.")

        incoming: list[tuple[PluginInfo, tuple[CapabilityDeclaration, ...]]] = []
        seen_plugins: set[str] = set()
        seen_capabilities: set[str] = set()

        for provider in providers:
            plugin = provider.plugin_info
            declarations = tuple(provider.declarations)
            if not isinstance(plugin, PluginInfo):
                raise TypeError(
                    f"provider.plugin_info must be a PluginInfo instance, got {type(plugin).__name__}."
                )
            if not all(isinstance(declaration, CapabilityDeclaration) for declaration in declarations):
                raise TypeError("provider.declarations must contain only CapabilityDeclaration instances.")

            if plugin.plugin_id in seen_plugins:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Duplicate plugin ID '{plugin.plugin_id}' in provider batch.",
                )
            seen_plugins.add(plugin.plugin_id)

            declared_ids = tuple(declaration.capability_id for declaration in declarations)
            if set(declared_ids) != set(plugin.capabilities) or len(declared_ids) != len(plugin.capabilities):
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=(
                        f"Declared capabilities for plugin '{plugin.plugin_id}' do not exactly match "
                        "PluginInfo.capabilities."
                    ),
                )

            for declaration in declarations:
                if declaration.plugin_id != plugin.plugin_id:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=(
                            f"Capability '{declaration.capability_id}' declared with mismatched "
                            f"plugin_id '{declaration.plugin_id}'."
                        ),
                    )
                if declaration.capability_id in seen_capabilities:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Duplicate capability ID '{declaration.capability_id}' in provider batch.",
                    )
                seen_capabilities.add(declaration.capability_id)

            incoming.append((plugin, declarations))

        for plugin, declarations in incoming:
            existing_plugin = self._plugins.get(plugin.plugin_id)
            if existing_plugin is not None and existing_plugin != plugin:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Conflicting plugin declaration already registered for '{plugin.plugin_id}'.",
                )

            for declaration in declarations:
                existing_capability = self._capabilities.get(declaration.capability_id)
                if existing_capability is not None and existing_capability != declaration:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=(
                            "Conflicting capability declaration already registered for "
                            f"'{declaration.capability_id}'."
                        ),
                    )
                if existing_capability is not None and existing_capability.plugin_id != plugin.plugin_id:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=(
                            f"Capability '{declaration.capability_id}' is owned by another plugin "
                            f"'{existing_capability.plugin_id}'."
                        ),
                    )

        # Commit the already validated batch directly. Calling the public single-item
        # registration methods here would repeat owner/duplicate validation after the
        # atomic preflight above and create a second validation path for the same batch.
        for plugin, declarations in incoming:
            if plugin.plugin_id not in self._plugins:
                self._plugins[plugin.plugin_id] = plugin
                self._plugin_capabilities[plugin.plugin_id] = []
            for declaration in declarations:
                if declaration.capability_id not in self._capabilities:
                    self._capabilities[declaration.capability_id] = declaration
                    self._plugin_capabilities[plugin.plugin_id].append(declaration.capability_id)

        return tuple(plugin.plugin_id for plugin, _ in incoming)

    def register_plugin(self, plugin: PluginInfo) -> None:
        """Register a PluginInfo declaration."""
        if not isinstance(plugin, PluginInfo):
            raise TypeError(f"plugin must be a PluginInfo instance, got {type(plugin).__name__}.")

        plugin_id = plugin.plugin_id
        if plugin_id in self._plugins:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Plugin '{plugin_id}' is already registered.",
            )

        self._plugins[plugin_id] = plugin
        self._plugin_capabilities[plugin_id] = []

    def register_capability(self, capability: CapabilityDeclaration) -> None:
        """Register a CapabilityDeclaration after its owning plugin exists."""
        if not isinstance(capability, CapabilityDeclaration):
            raise TypeError(f"capability must be a CapabilityDeclaration instance, got {type(capability).__name__}.")

        cap_id = capability.capability_id
        plugin_id = capability.plugin_id

        if plugin_id not in self._plugins:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Owning plugin '{plugin_id}' is not registered for capability '{cap_id}'.",
            )

        owner_plugin = self._plugins[plugin_id]
        if cap_id not in owner_plugin.capabilities:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Capability '{cap_id}' is not declared by owning plugin '{plugin_id}'.",
            )

        if cap_id in self._capabilities:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Capability '{cap_id}' is already registered.",
            )

        self._capabilities[cap_id] = capability
        self._plugin_capabilities[plugin_id].append(cap_id)

    def get_plugin(self, plugin_id: str) -> PluginInfo | None:
        """Look up a registered plugin by plugin_id, or return None."""
        if not isinstance(plugin_id, str):
            raise TypeError(f"plugin_id must be a string, got {type(plugin_id).__name__}.")
        return self._plugins.get(plugin_id)

    def get_capability(self, capability_id: str) -> CapabilityDeclaration | None:
        """Look up a registered capability by capability_id, or return None."""
        if not isinstance(capability_id, str):
            raise TypeError(f"capability_id must be a string, got {type(capability_id).__name__}.")
        return self._capabilities.get(capability_id)

    def get_capabilities_for_plugin(self, plugin_id: str) -> tuple[CapabilityDeclaration, ...]:
        """Return all capabilities registered under plugin_id in registration order."""
        if not isinstance(plugin_id, str):
            raise TypeError(f"plugin_id must be a string, got {type(plugin_id).__name__}.")
        cap_ids = self._plugin_capabilities.get(plugin_id, [])
        return tuple(self._capabilities[cid] for cid in cap_ids)

    def has_plugin(self, plugin_id: str) -> bool:
        """Return whether a plugin is registered."""
        return plugin_id in self._plugins

    def has_capability(self, capability_id: str) -> bool:
        """Return whether a capability is registered."""
        return capability_id in self._capabilities

    def plugins(self) -> tuple[PluginInfo, ...]:
        """Return an immutable plugin snapshot in registration order."""
        return tuple(self._plugins.values())

    def capabilities(self) -> tuple[CapabilityDeclaration, ...]:
        """Return an immutable capability snapshot in registration order."""
        return tuple(self._capabilities.values())

    def __len__(self) -> int:
        return len(self._capabilities)
