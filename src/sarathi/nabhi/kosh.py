"""Kosh — Plugin and Capability Registry for Nabhi Kernel in Sarathi V2.

Defines:
- Kosh: In-memory registry for PluginInfo and CapabilityDeclaration metadata.

Maintains declaration records only; contains no discovery, import/loading, execution,
device allocation, security enforcement, or pipeline logic.
"""

from __future__ import annotations

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import CapabilityDeclaration, PluginInfo


class Kosh:
    """In-memory registry storing registered plugins and capabilities."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginInfo] = {}
        self._capabilities: dict[str, CapabilityDeclaration] = {}
        self._plugin_capabilities: dict[str, list[str]] = {}

    def register_plugin(self, plugin: PluginInfo) -> None:
        """Register a PluginInfo declaration.

        Raises:
            DoshError(FailureCode.VALIDATION_FAILED): If plugin_id is already registered.
            TypeError: If plugin is not a PluginInfo instance.
        """
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
        """Register a CapabilityDeclaration after its owning plugin exists.

        Raises:
            DoshError(FailureCode.VALIDATION_FAILED): If capability_id already exists or owning plugin is missing.
            TypeError: If capability is not a CapabilityDeclaration instance.
        """
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
        """Return all capabilities registered under the given plugin_id in registration order."""
        if not isinstance(plugin_id, str):
            raise TypeError(f"plugin_id must be a string, got {type(plugin_id).__name__}.")
        cap_ids = self._plugin_capabilities.get(plugin_id, [])
        return tuple(self._capabilities[cid] for cid in cap_ids)

    def has_plugin(self, plugin_id: str) -> bool:
        """Check if plugin is registered."""
        return plugin_id in self._plugins

    def has_capability(self, capability_id: str) -> bool:
        """Check if capability is registered."""
        return capability_id in self._capabilities

    def plugins(self) -> tuple[PluginInfo, ...]:
        """Return an immutable snapshot of all registered plugins in registration order."""
        return tuple(self._plugins.values())

    def capabilities(self) -> tuple[CapabilityDeclaration, ...]:
        """Return an immutable snapshot of all registered capabilities in registration order."""
        return tuple(self._capabilities.values())

    def __len__(self) -> int:
        return len(self._capabilities)
