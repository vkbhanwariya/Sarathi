"""Agni - Runtime Bootstrap and Composition Root for Sarathi V2.

Composes configuration, global shared services, core kernel components, plugin discovery/registration,
lifecycle management, and canonical request execution. Wires owners together; does not absorb their logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from sarathi.agni.dispatcher import execute_request
from sarathi.agni.preflight import (
    resolve_darpana,
    resolve_kavacha,
    resolve_plugin_providers,
    resolve_storage_roots,
    resolve_yantra_and_inventory,
    validate_and_resolve_context,
    validate_and_resolve_settings,
    validate_bootstrap_consistency,
)
from sarathi.agni.readiness import ReadinessAuditor
from sarathi.agni.wiring import assemble_platform_services
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
    CapabilityReadiness,
    ExecutionContext,
    PluginInfo,
    PluginProvider,
    Request,
    Result,
)
from sarathi.smriti import SmritiCache
from sarathi.sutra import Settings
from sarathi.yantra import DeviceInventory, Yantra


class Agni:
    """Composition root for Sarathi V2 runtime services and execution lifecycle."""

    def __init__(
        self,
        settings: Settings | Path | str | None = None,
        *,
        runtime_root: Path | str | None = None,
        output_root: Path | str | None = None,
        input_root: Path | str | None = None,
        capabilities: Mapping[str, Capability] | None = None,
        plugins: Sequence[PluginInfo] | None = None,
        plugin_providers: Sequence[PluginProvider] | None = None,
        extra_plugin_providers: Sequence[PluginProvider] | None = None,
        inventory: DeviceInventory | None = None,
        darpana: Darpana | None = None,
        kavacha: Kavacha | None = None,
        smriti: SmritiCache | None = None,
        context: ExecutionContext | None = None,
    ) -> None:
        """Initialize Agni composition root and construct global services in dependency order."""
        # --- Preflight Phase: Strict argument and type validation BEFORE side effects ---
        _user_ctx, bootstrap_ctx = validate_and_resolve_context(context)
        active_settings = validate_and_resolve_settings(settings, darpana=darpana, bootstrap_ctx=bootstrap_ctx)
        val_runtime, val_output, val_input = resolve_storage_roots(
            runtime_root, output_root, input_root, active_settings
        )
        active_darpana = resolve_darpana(darpana, active_settings, val_runtime)
        active_kavacha = resolve_kavacha(kavacha, active_settings, val_input, val_runtime, val_output)
        active_yantra, active_inventory = resolve_yantra_and_inventory(inventory, active_settings, active_darpana)

        active_providers, all_candidate_providers = resolve_plugin_providers(
            plugin_providers, extra_plugin_providers, active_settings, capabilities
        )

        # --- Assembly Phase: Topological platform service wiring ---
        services = assemble_platform_services(
            settings=active_settings,
            runtime_root=val_runtime,
            output_root=val_output,
            input_root=val_input,
            kavacha=active_kavacha,
            darpana=active_darpana,
            yantra=active_yantra,
            active_providers=active_providers,
            capabilities=capabilities,
            plugins=plugins,
            smriti=smriti,
            bootstrap_ctx=bootstrap_ctx,
        )

        # Bootstrap Consistency Validation
        validate_bootstrap_consistency(
            kosh=services.kosh,
            capabilities=services.capabilities,
        )

        self._settings: Settings = active_settings
        self._darpana: Darpana = active_darpana
        self._runtime_root: Path = val_runtime
        self._output_root: Path = val_output
        self._input_root: Path = val_input
        self._kavacha: Kavacha = active_kavacha
        self._inventory: DeviceInventory = active_inventory
        self._yantra: Yantra = active_yantra
        self._capabilities: dict[str, Capability] = services.capabilities
        self._retry_policy: RetryPolicy = services.retry_policy
        self._artifact_boundary: ArtifactBoundary = services.artifact_boundary
        self._kosh: Kosh = services.kosh
        self._dvara: Dvara = services.dvara
        self._active_providers: tuple[PluginProvider, ...] = services.active_providers
        self._disabled_plugins: tuple[str, ...] = tuple(active_settings.plugins_disabled)
        self._all_candidate_providers: tuple[PluginProvider, ...] = all_candidate_providers
        self._manthan: Manthan = services.manthan
        self._prana: Prana = services.prana
        self._quarantine_store: QuarantineStore = services.quarantine_store
        self._smriti: SmritiCache | None = services.smriti
        self._pravaha: Pravaha = services.pravaha

        self._readiness_auditor = ReadinessAuditor(
            active_providers=self._active_providers,
            all_candidate_providers=self._all_candidate_providers,
            disabled_plugins=self._disabled_plugins,
            capabilities=self._capabilities,
            yantra=self._yantra,
            darpana=self._darpana,
            kavacha=self._kavacha,
            settings=self._settings,
        )

        self._is_started: bool = False
        self._is_closed: bool = False

    @property
    def is_started(self) -> bool:
        """Return True if runtime lifecycle has started and not closed."""
        return self._is_started

    @property
    def is_closed(self) -> bool:
        """Return True if runtime lifecycle has been closed."""
        return self._is_closed

    @property
    def settings(self) -> Settings:
        """Return the active Settings."""
        return self._settings

    @property
    def darpana(self) -> Darpana:
        """Return the injected Darpana telemetry service."""
        return self._darpana

    @property
    def smriti(self) -> SmritiCache | None:
        """Return the injected SmritiCache service if configured."""
        return self._smriti

    @property
    def runtime_root(self) -> Path:
        """Return the effective validated runtime root."""
        return self._runtime_root

    @property
    def output_root(self) -> Path:
        """Return the effective validated output root."""
        return self._output_root

    @property
    def input_root(self) -> Path:
        """Return the effective validated input root."""
        return self._input_root

    @property
    def kavacha(self) -> Kavacha:
        """Return the injected Kavacha security service."""
        return self._kavacha

    @property
    def artifact_boundary(self) -> ArtifactBoundary:
        """Return the injected ArtifactBoundary."""
        return self._artifact_boundary

    @property
    def kosh(self) -> Kosh:
        """Return the canonical Kosh registry."""
        return self._kosh

    @property
    def dvara(self) -> Dvara:
        """Return the Dvara registration manager."""
        return self._dvara

    @property
    def yantra(self) -> Yantra:
        """Return the Yantra execution manager."""
        return self._yantra

    @property
    def manthan(self) -> Manthan:
        """Return the Manthan capability resolver."""
        return self._manthan

    @property
    def prana(self) -> Prana:
        """Return the Prana lifecycle manager."""
        return self._prana

    @property
    def quarantine_store(self) -> QuarantineStore:
        """Return the QuarantineStore."""
        return self._quarantine_store

    @property
    def retry_policy(self) -> RetryPolicy:
        """Return the active RetryPolicy."""
        return self._retry_policy

    @property
    def pravaha(self) -> Pravaha:
        """Return the Pravaha pipeline engine."""
        return self._pravaha

    @property
    def capabilities(self) -> Mapping[str, Capability]:
        """Return an immutable snapshot of configured executable capabilities."""
        return dict(self._capabilities)

    @property
    def plugin_providers(self) -> tuple[PluginProvider, ...]:
        """Return active plugin providers configured for this runtime."""
        return self._active_providers

    @property
    def disabled_plugins(self) -> tuple[str, ...]:
        """Return operator-disabled plugin IDs configured for this runtime."""
        return self._disabled_plugins

    @staticmethod
    def _validate_bootstrap_consistency(
        kosh: Kosh,
        capabilities: Mapping[str, Capability],
    ) -> None:
        """Validate 1-to-1 invariant between Kosh declarations and executable capability bindings."""
        validate_bootstrap_consistency(kosh=kosh, capabilities=capabilities)

    def audit_readiness(self, force_refresh: bool = False) -> Mapping[str, CapabilityReadiness]:
        """Audit operational readiness of all active capabilities across plugin providers."""
        return self._readiness_auditor.audit(force_refresh=force_refresh)

    def register_component(self, component_id: str, component: Any) -> None:
        """Register a runtime component with Prana for lifecycle coordination."""
        self._prana.register(component_id, component)

    def start(self) -> None:
        """Start registered runtime components in dependency order via Prana."""
        if self._is_closed:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Agni runtime instance cannot be restarted after close.",
            )
        if not self._is_started:
            self._prana.start_all()
            self._is_started = True

    def close(self) -> None:
        """Close registered runtime components in reverse dependency order via Prana."""
        if self._is_closed:
            return
        self._is_closed = True
        try:
            self._prana.close_all()
        finally:
            self._is_started = False

    def stop(self) -> None:
        """Alias for close()."""
        self.close()

    def __enter__(self) -> Agni:
        """Context manager entry: starts runtime lifecycle."""
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit: stops runtime lifecycle."""
        self.close()

    def execute(
        self,
        request: Request,
        context: ExecutionContext | None = None,
    ) -> Result:
        """Execute a canonical Request through the full Agni-wired runtime path."""
        return execute_request(
            request=request,
            context=context,
            artifact_boundary=self._artifact_boundary,
            output_root=self._output_root,
            runtime_root=self._runtime_root,
            kavacha=self._kavacha,
            darpana=self._darpana,
            manthan=self._manthan,
            pravaha=self._pravaha,
            settings=self._settings,
        )
