"""Preflight validation of configuration, storage roots, security, and provider consistency."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha
from sarathi.nabhi import Kosh
from sarathi.sankalpa import Capability, ExecutionContext, PluginProvider
from sarathi.shakti.providers import BUILTIN_PLUGIN_PROVIDERS
from sarathi.sutra import Settings, load_settings
from sarathi.yantra import DeviceInventory, Yantra


def validate_and_resolve_context(context: ExecutionContext | None) -> tuple[ExecutionContext | None, ExecutionContext]:
    """Validate optional context and return (user_context, bootstrap_context)."""
    if context is not None and not isinstance(context, ExecutionContext):
        raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

    bootstrap_ctx = context or ExecutionContext(
        run_id="bootstrap",
        request_id="bootstrap",
        trace_id="bootstrap",
        span_id="bootstrap-001",
    )
    return context, bootstrap_ctx


def validate_and_resolve_settings(
    settings: Settings | Path | str | None,
    darpana: Darpana | None,
    bootstrap_ctx: ExecutionContext,
) -> Settings:
    """Validate settings argument and load if path or string."""
    match settings:
        case None:
            return Settings()
        case Settings():
            return settings
        case Path() | str():
            return load_settings(settings, darpana=darpana, context=bootstrap_ctx)
        case _:
            raise TypeError(f"settings must be Settings, Path, str, or None, got {type(settings).__name__}.")


def resolve_storage_roots(
    runtime_root: Path | str | None,
    output_root: Path | str | None,
    input_root: Path | str | None,
    settings: Settings,
) -> tuple[Path, Path, Path]:
    """Validate and resolve runtime, output, and input storage roots."""
    def _resolve_root(arg_val: Path | str | None, setting_val: Path, param_name: str) -> Path:
        if arg_val is not None:
            if not isinstance(arg_val, (Path, str)):
                raise TypeError(f"{param_name} must be a Path, str, or None, got {type(arg_val).__name__}.")
            if not str(arg_val).strip():
                raise DoshError(
                    code=FailureCode.INVALID_CONFIGURATION,
                    message=f"{param_name} cannot be empty.",
                )
            return Path(arg_val).resolve()
        return setting_val.resolve()

    return (
        _resolve_root(runtime_root, settings.storage_runtime_root, "runtime_root"),
        _resolve_root(output_root, settings.storage_output_root, "output_root"),
        _resolve_root(input_root, settings.storage_input_root, "input_root"),
    )


def resolve_darpana(
    darpana: Darpana | None,
    settings: Settings,
    runtime_root: Path,
) -> Darpana:
    """Validate Darpana telemetry instance and resolve bound history storage."""
    if darpana is not None and not isinstance(darpana, Darpana):
        raise TypeError(f"darpana must be a Darpana instance or None, got {type(darpana).__name__}.")

    hist_dir = (runtime_root / "Telemetry").resolve()
    if settings.telemetry_history_enabled:
        if settings.telemetry_history_path is not None:
            user_hist = Path(settings.telemetry_history_path)
            if user_hist.is_absolute():
                raise DoshError(
                    code=FailureCode.INVALID_CONFIGURATION,
                    message="telemetry.history_path cannot be an absolute path; it must be relative to Runtime/Telemetry.",
                )
            if len(user_hist.parts) >= 2 and user_hist.parts[0] == "Runtime" and user_hist.parts[1] == "Telemetry":
                user_hist = Path(*user_hist.parts[2:])
            elif len(user_hist.parts) >= 1 and user_hist.parts[0] == "Telemetry":
                user_hist = Path(*user_hist.parts[1:])

            resolved_hist = (hist_dir / user_hist).resolve()
            if not (resolved_hist == hist_dir or hist_dir in resolved_hist.parents):
                raise DoshError(
                    code=FailureCode.INVALID_CONFIGURATION,
                    message="telemetry.history_path escapes the Runtime/Telemetry directory.",
                )
            hist_path = resolved_hist
        else:
            hist_path = hist_dir / (
                "history.db" if settings.telemetry_history_format == "sqlite" else "history.jsonl"
            )
    else:
        hist_path = None

    return darpana or Darpana(
        capacity=settings.telemetry_live_buffer_capacity,
        history_path=hist_path,
        history_format=settings.telemetry_history_format,
        history_max_records=settings.telemetry_history_max_records,
    )


def resolve_kavacha(
    kavacha: Kavacha | None,
    settings: Settings,
    input_root: Path,
    runtime_root: Path,
    output_root: Path,
) -> Kavacha:
    """Validate and initialize Kavacha, ensuring root overlap separation."""
    if kavacha is not None:
        if not isinstance(kavacha, Kavacha):
            raise TypeError(f"kavacha must be a Kavacha instance or None, got {type(kavacha).__name__}.")
        active_kavacha = kavacha
    else:
        active_kavacha = Kavacha(settings.security_policy())

    active_kavacha.validate_source_destination_overlap(
        [input_root],
        (runtime_root, output_root),
    )
    active_kavacha.validate_source_destination_overlap(
        [runtime_root],
        output_root,
    )
    return active_kavacha


def resolve_yantra_and_inventory(
    inventory: DeviceInventory | None,
    settings: Settings,
    darpana: Darpana,
) -> tuple[Yantra, DeviceInventory]:
    """Validate or detect DeviceInventory, then instantiate Yantra compute resource manager."""
    if inventory is not None:
        if not isinstance(inventory, DeviceInventory):
            raise TypeError(
                f"inventory must be a DeviceInventory instance or None, got {type(inventory).__name__}."
            )
        active_inventory = inventory
    else:
        active_inventory = Yantra.default_inventory(
            detect_accelerators=settings.hardware_detect_accelerators,
            gpu_capacity_per_device=settings.hardware_gpu_capacity_per_device,
            npu_capacity_per_device=settings.hardware_npu_capacity_per_device,
        )

    active_yantra = Yantra(
        active_inventory,
        darpana=darpana,
        max_queue_depth=settings.hardware_max_queue_depth,
    )
    return active_yantra, active_inventory


def resolve_plugin_providers(
    plugin_providers: Sequence[PluginProvider] | None,
    extra_plugin_providers: Sequence[PluginProvider] | None,
    settings: Settings,
    capabilities: Mapping[str, Capability] | None,
) -> tuple[tuple[PluginProvider, ...], tuple[PluginProvider, ...]]:
    """Validate and preflight plugin providers against duplicates and disabled settings.

    Returns:
        (active_providers, all_candidate_providers)
    """
    active_providers_list: tuple[PluginProvider, ...]
    if plugin_providers is not None:
        if not isinstance(plugin_providers, (list, tuple)):
            raise TypeError(
                f"plugin_providers must be a sequence of PluginProvider or None, got {type(plugin_providers).__name__}."
            )
        for p in plugin_providers:
            if not isinstance(p, PluginProvider):
                raise TypeError(f"All items in plugin_providers must implement PluginProvider, got {type(p).__name__}.")
        active_providers_list = tuple(plugin_providers)
    else:
        active_providers_list = BUILTIN_PLUGIN_PROVIDERS

    if extra_plugin_providers is not None:
        if not isinstance(extra_plugin_providers, (list, tuple)):
            raise TypeError(
                f"extra_plugin_providers must be a sequence of PluginProvider or None, got {type(extra_plugin_providers).__name__}."
            )
        for p in extra_plugin_providers:
            if not isinstance(p, PluginProvider):
                raise TypeError(
                    f"All items in extra_plugin_providers must implement PluginProvider, got {type(p).__name__}."
                )
        active_providers_list = active_providers_list + tuple(extra_plugin_providers)

    # Preflight active providers for duplicate plugin IDs or capability IDs
    seen_plugin_ids: set[str] = set()
    seen_capability_ids: set[str] = set()
    for prov in active_providers_list:
        p_id = prov.plugin_info.plugin_id
        if p_id in seen_plugin_ids:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Duplicate plugin ID '{p_id}' detected across plugin providers.",
            )
        seen_plugin_ids.add(p_id)

        for decl in prov.declarations:
            c_id = decl.capability_id
            if c_id in seen_capability_ids:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Duplicate capability ID '{c_id}' declared across plugin providers.",
                )
            seen_capability_ids.add(c_id)

    all_candidate_providers = active_providers_list
    disabled_pids = set(settings.plugins_disabled)
    if disabled_pids and capabilities is None:
        active_providers_list = tuple(p for p in active_providers_list if p.plugin_info.plugin_id not in disabled_pids)

    return active_providers_list, all_candidate_providers


def validate_bootstrap_consistency(
    kosh: Kosh,
    capabilities: Mapping[str, Capability],
) -> None:
    """Validate 1-to-1 invariant between Kosh declarations and executable capability bindings."""
    # 1. Every Kosh declaration must have an executable binding
    for kosh_decl in kosh.capabilities():
        if kosh_decl.capability_id not in capabilities:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Registered capability '{kosh_decl.capability_id}' in Kosh has no matching executable binding in runtime.",
            )

    # 2. Every executable binding must have a matching declaration in Kosh
    for cap_id, cap_obj in capabilities.items():
        if not kosh.has_capability(cap_id):
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Executable capability '{cap_id}' has no matching declaration registered in Kosh.",
            )
        kosh_decl = kosh.get_capability(cap_id)
        if cap_obj.declaration != kosh_decl:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=(
                    f"Declaration mismatch for capability '{cap_id}': "
                    "executable declaration does not match Kosh declaration."
                ),
            )
