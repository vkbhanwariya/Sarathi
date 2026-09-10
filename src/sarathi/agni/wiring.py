"""Construction of Sarathi runtime services.

This module wires concrete services. Agni owns composition and lifecycle,
Kosh owns declaration registration, and Pravaha owns request execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha
from sarathi.nabhi import ArtifactBoundary, Kosh, Manthan, Pravaha, QuarantineStore, RetryPolicy
from sarathi.sankalpa import Capability, PluginInfo, PluginProvider, PluginServices
from sarathi.smriti import SmritiCache
from sarathi.sutra import Settings, get_canonical_data_root
from sarathi.yantra import Yantra


@dataclass(frozen=True)
class AssembledServices:
    """Runtime services assembled by the application composition root."""

    artifact_boundary: ArtifactBoundary
    kosh: Kosh
    manthan: Manthan
    quarantine_store: QuarantineStore
    smriti: SmritiCache | None
    retry_policy: RetryPolicy
    pravaha: Pravaha
    capabilities: dict[str, Capability]
    active_providers: tuple[PluginProvider, ...]


def assemble_platform_services(
    settings: Settings,
    runtime_root: Path,
    output_root: Path,
    input_root: Path,
    kavacha: Kavacha,
    darpana: Darpana,
    yantra: Yantra,
    active_providers: tuple[PluginProvider, ...],
    capabilities: Mapping[str, Capability] | None,
    plugins: Sequence[PluginInfo] | None,
    smriti: SmritiCache | None,
) -> AssembledServices:
    """Construct the services required by Agni and Pravaha."""
    if capabilities is not None:
        if not isinstance(capabilities, Mapping):
            raise TypeError(f"capabilities must be a Mapping or None, got {type(capabilities).__name__}.")
        for cap_id, capability in capabilities.items():
            if not isinstance(cap_id, str) or not cap_id.strip():
                raise TypeError("Capability mapping keys must be non-empty strings.")
            if not isinstance(capability, Capability):
                raise TypeError(f"Capability '{cap_id}' does not implement Capability protocol.")
            if cap_id != capability.declaration.capability_id:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=(
                        f"Capability mapping key '{cap_id}' does not match declaration "
                        f"capability_id '{capability.declaration.capability_id}'."
                    ),
                )
        active_capabilities = dict(capabilities)
        replacement_plugin_ids = {cap.declaration.plugin_id for cap in active_capabilities.values()}
        registry_providers = tuple(
            provider for provider in active_providers if provider.plugin_info.plugin_id in replacement_plugin_ids
        )
    else:
        plugin_services = PluginServices(
            yantra=yantra,
            darpana=darpana,
            kavacha=kavacha,
            settings=settings,
            data_root=get_canonical_data_root(),
        )
        active_capabilities: dict[str, Capability] = {}
        for provider in active_providers:
            for cap_id, capability in provider.create_capabilities(plugin_services).items():
                if cap_id in active_capabilities:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Duplicate capability ID '{cap_id}' returned by provider '{provider.plugin_info.plugin_id}'.",
                    )
                active_capabilities[cap_id] = capability
        registry_providers = active_providers

    retry_policy = RetryPolicy(max_retries=settings.pipeline_max_retries)
    artifact_boundary = ArtifactBoundary(
        runtime_root=runtime_root,
        output_root=output_root,
        kavacha=kavacha,
        darpana=darpana,
    )

    kosh = Kosh()
    kosh.register_providers(registry_providers)

    if plugins is not None:
        if not isinstance(plugins, (list, tuple)):
            raise TypeError(f"plugins must be a sequence of PluginInfo or None, got {type(plugins).__name__}.")
        for plugin in plugins:
            if not isinstance(plugin, PluginInfo):
                raise TypeError(f"All items in plugins must be PluginInfo instances, got {type(plugin).__name__}.")
            if not kosh.has_plugin(plugin.plugin_id):
                kosh.register_plugin(plugin)

    for cap_id, capability in active_capabilities.items():
        if kosh.has_capability(cap_id):
            continue
        plugin_id = capability.declaration.plugin_id
        if not kosh.has_plugin(plugin_id):
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=(
                    f"Cannot register capability '{cap_id}': owning plugin '{plugin_id}' is not registered in Kosh. "
                    "Pass explicit PluginInfo via the 'plugins' argument."
                ),
            )
        kosh.register_capability(capability.declaration)

    manthan = Manthan(registry=kosh)
    quarantine_store = QuarantineStore(root=runtime_root / "Quarantine")

    active_smriti: SmritiCache | None = None
    if smriti is not None:
        if not isinstance(smriti, SmritiCache):
            raise TypeError(f"smriti must be a SmritiCache instance or None, got {type(smriti).__name__}.")
        active_smriti = smriti
    elif settings.cache_enabled:
        cache_dir = settings.cache_dir or (runtime_root / "Cache")
        active_smriti = SmritiCache(cache_dir=cache_dir, policy=settings.cache_policy())

    pravaha = Pravaha(
        manthan=manthan,
        yantra=yantra,
        capabilities=active_capabilities,
        quarantine_store=quarantine_store,
        retry_policy=retry_policy,
        darpana=darpana,
        kavacha=kavacha,
        smriti=active_smriti,
    )

    return AssembledServices(
        artifact_boundary=artifact_boundary,
        kosh=kosh,
        manthan=manthan,
        quarantine_store=quarantine_store,
        smriti=active_smriti,
        retry_policy=retry_policy,
        pravaha=pravaha,
        capabilities=active_capabilities,
        active_providers=registry_providers,
    )
