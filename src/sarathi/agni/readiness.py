"""Capability and plugin provider readiness audit probe coordination."""

from __future__ import annotations

import threading
from types import MappingProxyType
from typing import Mapping, Sequence

from sarathi.darpana import Darpana
from sarathi.kavacha import Kavacha
from sarathi.sankalpa import (
    Capability,
    CapabilityReadiness,
    PluginProvider,
    PluginServices,
    ReadinessStatus,
)
from sarathi.sutra import Settings, get_canonical_data_root
from sarathi.yantra import Yantra


class ReadinessAuditor:
    """Thread-safe capability and plugin readiness auditor with memoization."""

    def __init__(
        self,
        active_providers: Sequence[PluginProvider],
        all_candidate_providers: Sequence[PluginProvider],
        disabled_plugins: Sequence[str],
        capabilities: Mapping[str, Capability],
        yantra: Yantra,
        darpana: Darpana,
        kavacha: Kavacha,
        settings: Settings,
    ) -> None:
        self._active_providers = tuple(active_providers)
        self._all_candidate_providers = tuple(all_candidate_providers)
        self._disabled_plugins = tuple(disabled_plugins)
        self._capabilities = capabilities
        self._yantra = yantra
        self._darpana = darpana
        self._kavacha = kavacha
        self._settings = settings
        self._lock = threading.Lock()
        self._cache: dict[str, CapabilityReadiness] | None = None

    def audit(self, force_refresh: bool = False) -> Mapping[str, CapabilityReadiness]:
        """Audit operational readiness of all active capabilities across plugin providers."""
        with self._lock:
            if self._cache is not None and not force_refresh:
                return MappingProxyType(self._cache)

            services = PluginServices(
                yantra=self._yantra,
                darpana=self._darpana,
                kavacha=self._kavacha,
                settings=self._settings,
                data_root=get_canonical_data_root(),
            )

            results: dict[str, CapabilityReadiness] = {}
            for prov in self._active_providers:
                try:
                    prov_readiness = prov.readiness(services)
                    results.update(prov_readiness)
                except Exception as exc:
                    for decl in prov.declarations:
                        results[decl.capability_id] = CapabilityReadiness(
                            ready=False,
                            status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                            reason=f"Readiness probe error: {type(exc).__name__}",
                        )

            for cap_k in self._capabilities:
                if cap_k not in results:
                    results[cap_k] = CapabilityReadiness(
                        ready=True,
                        status=ReadinessStatus.READY,
                        reason="Capability ready",
                    )

            # Record disabled status for operator-disabled plugins
            for prov in self._all_candidate_providers:
                if prov.plugin_info.plugin_id in self._disabled_plugins:
                    for decl in prov.declarations:
                        results[decl.capability_id] = CapabilityReadiness(
                            ready=False,
                            status=ReadinessStatus.DISABLED,
                            reason="Disabled by operator configuration (plugins.disabled)",
                        )

            self._cache = results
            return MappingProxyType(self._cache)
