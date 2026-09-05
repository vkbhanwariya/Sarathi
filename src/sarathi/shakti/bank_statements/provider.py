"""Provider implementation for Bank Statement Consolidation."""

from __future__ import annotations

from typing import Mapping

from sarathi.sankalpa import (
    Capability,
    CapabilityDeclaration,
    CapabilityReadiness,
    PluginInfo,
    PluginProvider,
    PluginServices,
    ReadinessStatus,
)
from sarathi.shakti.bank_statements.plugin import (
    CAPABILITY_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.sutra import get_canonical_data_root


class BankStatementsProvider(PluginProvider):
    """Canonical provider for Bank Statement Consolidation."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (CAPABILITY_DECLARATION,)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        from sarathi.shakti.bank_statements.capability import (
            BankStatementCapability,
        )

        return {"bank_statements": BankStatementCapability(darpana=services.darpana)}

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        base_data = (services.data_root if services and services.data_root else get_canonical_data_root()) / "banks"
        try:
            from sarathi.shakti.bank_statements.detector import load_bank_profiles

            bank_profs = load_bank_profiles(base_data)
            if bank_profs:
                prof_ids = [str(p.get("profile_id", "")).upper() for p in bank_profs if p.get("profile_id")]
                return {
                    "bank_statements": CapabilityReadiness(
                        ready=True,
                        status=ReadinessStatus.READY,
                        reason=f"Ready ({', '.join(prof_ids)} profiles)",
                    )
                }
            return {
                "bank_statements": CapabilityReadiness(
                    ready=False,
                    status=ReadinessStatus.INVALID_CONFIGURATION,
                    reason="Unavailable (No bank profiles loaded)",
                )
            }
        except Exception as exc:
            return {
                "bank_statements": CapabilityReadiness(
                    ready=False,
                    status=ReadinessStatus.INVALID_CONFIGURATION,
                    reason=f"Unavailable (Failed to load bank profiles: {exc})",
                )
            }
