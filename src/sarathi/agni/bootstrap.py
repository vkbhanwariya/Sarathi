"""Agni - application composition root for Sarathi.

Agni constructs the runtime, owns process-level lifecycle, and delegates request
execution to Pravaha. It intentionally avoids a separate lifecycle-manager layer.
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
from sarathi.nabhi import ArtifactBoundary, Dvara, Kosh, Manthan, Pravaha, QuarantineStore, RetryPolicy
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
    """Application runtime and composition root."""

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
        validate_bootstrap_consistency(kosh=services.kosh, capabilities=services.capabilities)

        self._settings = active_settings
        self._darpana = active_darpana
        self._runtime_root = val_runtime
        self._output_root = val_output
        self._input_root = val_input
        self._kavacha = active_kavacha
        self._inventory = active_inventory
        self._yantra = active_yantra
        self._capabilities = services.capabilities
        self._retry_policy = services.retry_policy
        self._artifact_boundary = services.artifact_boundary
        self._kosh = services.kosh
        self._dvara = services.dvara
        self._active_providers = services.active_providers
        self._disabled_plugins = tuple(active_settings.plugins_disabled)
        self._all_candidate_providers = all_candidate_providers
        self._manthan = services.manthan
        self._quarantine_store = services.quarantine_store
        self._smriti = services.smriti
        self._pravaha = services.pravaha

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

        self._components: dict[str, Any] = {
            "yantra": self._yantra,
            "darpana": self._darpana,
        }
        if self._smriti is not None:
            self._components["smriti"] = self._smriti
        self._attempted_component_ids: set[str] = set()
        self._started_component_ids: list[str] = []
        self._closed_component_ids: set[str] = set()
        self._is_started = False
        self._is_closed = False

    @property
    def is_started(self) -> bool:
        return self._is_started

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def darpana(self) -> Darpana:
        return self._darpana

    @property
    def smriti(self) -> SmritiCache | None:
        return self._smriti

    @property
    def runtime_root(self) -> Path:
        return self._runtime_root

    @property
    def output_root(self) -> Path:
        return self._output_root

    @property
    def input_root(self) -> Path:
        return self._input_root

    @property
    def kavacha(self) -> Kavacha:
        return self._kavacha

    @property
    def artifact_boundary(self) -> ArtifactBoundary:
        return self._artifact_boundary

    @property
    def kosh(self) -> Kosh:
        return self._kosh

    @property
    def dvara(self) -> Dvara:
        return self._dvara

    @property
    def yantra(self) -> Yantra:
        return self._yantra

    @property
    def manthan(self) -> Manthan:
        return self._manthan

    @property
    def quarantine_store(self) -> QuarantineStore:
        return self._quarantine_store

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    @property
    def pravaha(self) -> Pravaha:
        return self._pravaha

    @property
    def capabilities(self) -> Mapping[str, Capability]:
        return dict(self._capabilities)

    @property
    def plugin_providers(self) -> tuple[PluginProvider, ...]:
        return self._active_providers

    @property
    def disabled_plugins(self) -> tuple[str, ...]:
        return self._disabled_plugins

    @staticmethod
    def _validate_bootstrap_consistency(kosh: Kosh, capabilities: Mapping[str, Capability]) -> None:
        validate_bootstrap_consistency(kosh=kosh, capabilities=capabilities)

    def audit_readiness(self, force_refresh: bool = False) -> Mapping[str, CapabilityReadiness]:
        return self._readiness_auditor.audit(force_refresh=force_refresh)

    def register_component(self, component_id: str, component: Any) -> None:
        """Register a process-level component that exposes start() and close()."""
        if not isinstance(component_id, str):
            raise TypeError(f"component_id must be a string, got {type(component_id).__name__}.")
        component_id = component_id.strip()
        if not component_id:
            raise ValueError("component_id must be a non-empty string.")
        if not callable(getattr(component, "start", None)) or not callable(getattr(component, "close", None)):
            raise TypeError(
                f"Component '{component_id}' must expose callable 'start()' and 'close()' methods, "
                f"got {type(component).__name__}."
            )
        if component_id in self._components:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Component '{component_id}' is already registered.",
            )
        if self._is_started:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Cannot register lifecycle components after Agni has started.",
            )
        self._components[component_id] = component

    def registered_component_ids(self) -> tuple[str, ...]:
        return tuple(self._components)

    def started_component_ids(self) -> tuple[str, ...]:
        return tuple(self._started_component_ids)

    def start(self) -> None:
        """Start process-level components in registration order."""
        if self._is_closed:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Agni runtime instance cannot be restarted after close.",
            )
        if self._is_started:
            return

        for component_id, component in self._components.items():
            if component_id in self._attempted_component_ids:
                continue
            self._attempted_component_ids.add(component_id)
            try:
                component.start()
                self._started_component_ids.append(component_id)
            except BaseException:
                self._rollback_started_components()
                raise
        self._is_started = True

    def _rollback_started_components(self) -> None:
        for component_id in reversed(self._started_component_ids):
            if component_id in self._closed_component_ids:
                continue
            self._closed_component_ids.add(component_id)
            try:
                self._components[component_id].close()
            except BaseException:
                pass

    def close(self) -> None:
        """Close started components in reverse order, preserving the first close error."""
        if self._is_closed:
            return
        self._is_closed = True
        first_error: BaseException | None = None
        for component_id in reversed(self._started_component_ids):
            if component_id in self._closed_component_ids:
                continue
            self._closed_component_ids.add(component_id)
            try:
                self._components[component_id].close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        self._is_started = False
        if first_error is not None:
            raise first_error

    def stop(self) -> None:
        self.close()

    def __enter__(self) -> Agni:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def execute(self, request: Request, context: ExecutionContext | None = None) -> Result:
        """Execute a canonical request through the configured runtime."""
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
