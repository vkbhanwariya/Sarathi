"""Plugin Contracts and Security Declarations for Sarathi V2.

Defines:
- SecurityDeclaration: Reviewable security and privacy requirements declared by plugins.
- PluginInfo: Metadata and declared capabilities of a registered plugin.

Sankalpa only defines the contract shape; Kavacha enforces security policy.
Contains metadata only; performs no policy decisions, authorization, or enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SecurityDeclaration:
    """Declarative security requirements declared by a plugin or capability."""

    pii_access: bool = False
    local_processing_only: bool = True
    network_access: bool = False
    external_processing: bool = False
    required_secrets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.external_processing:
            if not self.network_access:
                raise ValueError("external_processing=True requires network_access=True in SecurityDeclaration.")
            if self.local_processing_only:
                raise ValueError(
                    "external_processing=True cannot coexist with local_processing_only=True in SecurityDeclaration."
                )

        if isinstance(self.required_secrets, (list, tuple, set)):
            # Ensure unique sorted tuple of non-empty secret names
            cleaned = tuple(sorted({s.strip() for s in self.required_secrets if s and s.strip()}))
            object.__setattr__(self, "required_secrets", cleaned)
        else:
            raise TypeError(f"required_secrets must be a sequence of strings, got {type(self.required_secrets)}.")


@dataclass(frozen=True, slots=True)
class PluginInfo:
    """Canonical plugin metadata contract."""

    plugin_id: str
    name: str
    version: str
    description: str = ""
    security: SecurityDeclaration = field(default_factory=SecurityDeclaration)
    capabilities: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plugin_id or not self.plugin_id.strip():
            raise ValueError("plugin_id must be a non-empty string.")
        if not self.name or not self.name.strip():
            raise ValueError("name must be a non-empty string.")
        if not self.version or not self.version.strip():
            raise ValueError("version must be a non-empty string.")
        if not isinstance(self.security, SecurityDeclaration):
            raise TypeError(f"security must be a SecurityDeclaration, got {type(self.security)}.")
        if isinstance(self.capabilities, (list, tuple, set)):
            cleaned_caps = tuple(c.strip() for c in self.capabilities if c and c.strip())
            object.__setattr__(self, "capabilities", cleaned_caps)
        else:
            raise TypeError(f"capabilities must be a sequence of strings, got {type(self.capabilities)}.")
        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")
