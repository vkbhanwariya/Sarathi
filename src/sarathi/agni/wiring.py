"""Topological assembly and construction of core platform services for Sarathi V2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha
from sarathi.nabhi import (
    ArtifactBoundary,
    Dvara,
    Kosh,
    Manthan,
    Prana,
    Pravaha,
    QuarantineStore,
    RetryPolicy,
)
from sarathi.sankalpa import (
    Capability,
    ExecutionContext,
    PluginInfo,
    PluginProvider,
    PluginServices,
)
from sarathi.smriti import SmritiCache
from sarathi.sutra import Settings, get_canonical_data_root
from sarathi.yantra import Yantra


@dataclass(frozen=True)
class AssembledServices:
    """Immutable container holding all assembled runtime platform services."""

    artifact_boundary: ArtifactBoundary
    kosh: Kosh
    dvara: Dvara
    manthan: Manthan
    prana: Prana
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
    bootstrap_ctx: ExecutionContext,
) -> AssembledServices:
    """Construct and wire all core services in strict dependency order."""
    # 1. Resolve capabilities and active dvara providers
    active_capabilities: dict[str, Capability]
    dvara_providers: tuple[PluginProvider, ...]
    if capabilities is not None:
        if not isinstance(capabilities, Mapping):
            raise TypeError(f"capabilities must be a Mapping or None, got {type(capabilities).__name__}.")
        for cap_k, cap_v in capabilities.items():
            if not isinstance(cap_k, str) or not cap_k.strip():
                raise TypeError("Capability mapping keys must be non-empty strings.")
            if not isinstance(cap_v, Capability):
                raise TypeError(f"Capability '{cap_k}' does not implement Capability protocol.")
            if cap_k != cap_v.declaration.capability_id:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=(
                        f"Capability mapping key '{cap_k}' does not match declaration "
                        f"capability_id '{cap_v.declaration.capability_id}'."
                    ),
                )
        active_capabilities = dict(capabilities)
        replacement_plugin_ids = {c.declaration.plugin_id for c in active_capabilities.values()}
        dvara_providers = tuple(p for p in active_providers if p.plugin_info.plugin_id in replacement_plugin_ids)
    else:
        services = PluginServices(
            yantra=yantra,
            darpana=darpana,
            kavacha=kavacha,
            settings=settings,
            data_root=get_canonical_data_root(),
        )
        active_capabilities = {}
        for prov in active_providers:
            prov_caps = prov.create_capabilities(services)
            for cap_k, cap_v in prov_caps.items():
                if cap_k in active_capabilities:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Duplicate capability ID '{cap_k}' returned by provider '{prov.plugin_info.plugin_id}'.",
                    )
                active_capabilities[cap_k] = cap_v
        dvara_providers = active_providers

    # 2. Retry Policy
    retry_policy = RetryPolicy(max_retries=settings.pipeline_max_retries)

    # 3. Artifact Boundary
    artifact_boundary = ArtifactBoundary(
        runtime_root=runtime_root,
        output_root=output_root,
        kavacha=kavacha,
        darpana=darpana,
    )

    # 4. Kosh & Dvara
    kosh = Kosh()
    dvara = Dvara(registry=kosh, darpana=darpana, providers=dvara_providers)
    dvara.register_builtins(context=bootstrap_ctx)

    # 5. Register explicit plugins if supplied
    if plugins is not None:
        if not isinstance(plugins, (list, tuple)):
            raise TypeError(f"plugins must be a sequence of PluginInfo or None, got {type(plugins).__name__}.")
        for p in plugins:
            if not isinstance(p, PluginInfo):
                raise TypeError(f"All items in plugins must be PluginInfo instances, got {type(p).__name__}.")
            if not kosh.has_plugin(p.plugin_id):
                kosh.register_plugin(p)

    # 6. Register capabilities with Kosh; require that owning plugins are registered
    for cap_k, cap_v in active_capabilities.items():
        if not kosh.has_capability(cap_k):
            p_id = cap_v.declaration.plugin_id
            if not kosh.has_plugin(p_id):
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=(
                        f"Cannot register capability '{cap_k}': owning plugin '{p_id}' is not registered in Kosh. "
                        "Pass explicit PluginInfo via the 'plugins' argument."
                    ),
                )
            dvara.register_capability(cap_v.declaration)

    # 7. Manthan
    manthan = Manthan(registry=kosh)

    # 8. Prana & QuarantineStore
    prana = Prana()
    prana.register("yantra", yantra)
    if darpana is not None:
        prana.register("darpana", darpana)
    quarantine_store = QuarantineStore(root=runtime_root / "Quarantine")

    # 9. Smriti Cache
    active_smriti: SmritiCache | None = None
    if smriti is not None:
        if not isinstance(smriti, SmritiCache):
            raise TypeError(f"smriti must be a SmritiCache instance or None, got {type(smriti).__name__}.")
        active_smriti = smriti
    elif settings.cache_enabled:
        cache_dir = settings.cache_dir or (runtime_root / "Cache")
        active_smriti = SmritiCache(cache_dir=cache_dir)

    if active_smriti is not None:
        prana.register("smriti", active_smriti)

    # 10. Pravaha Pipeline Engine
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
        dvara=dvara,
        manthan=manthan,
        prana=prana,
        quarantine_store=quarantine_store,
        smriti=active_smriti,
        retry_policy=retry_policy,
        pravaha=pravaha,
        capabilities=active_capabilities,
        active_providers=dvara_providers,
    )
