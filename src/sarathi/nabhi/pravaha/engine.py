"""Canonical Dynamic Pipeline Engine for Nabhi Kernel in Sarathi V2."""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.kosh import Kosh
from sarathi.nabhi.manthan import CapabilityPlan, Manthan
from sarathi.nabhi.pravaha.common import (
    authorize_capability,
    compute_input_hash,
    quarantine_transition_scope,
    record_pramana_if_available,
)
from sarathi.nabhi.pravaha.lifecycle import (
    apply_lifecycle_action as _apply_lifecycle_action,
)
from sarathi.nabhi.pravaha.lifecycle import (
    execute_retry_attempt as _execute_retry_attempt_impl,
)
from sarathi.nabhi.pravaha.pipeline import execute_pipeline
from sarathi.nabhi.quarantine import (
    LifecycleAction,
    QuarantineRecord,
    QuarantineStore,
    RetryPolicy,
)
from sarathi.sankalpa import Capability, ExecutionContext, Request, Result
from sarathi.smriti import SmritiCache
from sarathi.yantra import Yantra

if TYPE_CHECKING:
    from sarathi.darpana import Darpana
    from sarathi.kavacha import Kavacha


class Pravaha:
    """Dynamic Pipeline Engine for Nabhi Kernel owning execution and failure lifecycle."""

    def __init__(
        self,
        manthan: Manthan,
        yantra: Yantra,
        capabilities: Mapping[str, Capability],
        quarantine_store: QuarantineStore | None = None,
        retry_policy: RetryPolicy | None = None,
        darpana: Darpana | None = None,
        kavacha: Kavacha | None = None,
        smriti: SmritiCache | None = None,
    ) -> None:
        """Initialize Pravaha with resolver, execution manager, capabilities, optional quarantine, and telemetry."""
        if not isinstance(manthan, Manthan):
            raise TypeError(f"manthan must be a Manthan instance, got {type(manthan).__name__}.")
        if not isinstance(yantra, Yantra):
            raise TypeError(f"yantra must be a Yantra instance, got {type(yantra).__name__}.")
        if not isinstance(capabilities, Mapping):
            raise TypeError(f"capabilities must be a Mapping, got {type(capabilities).__name__}.")
        if quarantine_store is not None and not isinstance(quarantine_store, QuarantineStore):
            raise TypeError(
                f"quarantine_store must be a QuarantineStore instance or None, got {type(quarantine_store).__name__}."
            )
        if retry_policy is not None and not isinstance(retry_policy, RetryPolicy):
            raise TypeError(f"retry_policy must be a RetryPolicy instance or None, got {type(retry_policy).__name__}.")
        if darpana is not None:
            from sarathi.darpana import Darpana as DarpanaService

            if not isinstance(darpana, DarpanaService):
                raise TypeError(f"darpana must be a Darpana instance or None, got {type(darpana).__name__}.")
        if kavacha is not None:
            from sarathi.kavacha import Kavacha as KavachaService

            if not isinstance(kavacha, KavachaService):
                raise TypeError(f"kavacha must be a Kavacha instance or None, got {type(kavacha).__name__}.")

        self._manthan: Manthan = manthan
        self._registry: Kosh = manthan.registry
        self._yantra: Yantra = yantra
        self._capabilities: Mapping[str, Capability] = dict(capabilities)
        self._quarantine_store: QuarantineStore | None = quarantine_store
        self._retry_policy: RetryPolicy = retry_policy if retry_policy is not None else RetryPolicy(max_retries=0)
        self._darpana: Darpana | None = darpana
        self._kavacha: Kavacha | None = kavacha
        if smriti is not None and not isinstance(smriti, SmritiCache):
            raise TypeError(f"smriti must be a SmritiCache instance or None, got {type(smriti).__name__}.")
        self._smriti: SmritiCache | None = smriti

        if self._retry_policy.max_retries > 0 and self._quarantine_store is None:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="Automatic retry policy requires a configured QuarantineStore.",
            )

    @property
    def quarantine_store(self) -> QuarantineStore | None:
        """Return the injected QuarantineStore, if configured."""
        return self._quarantine_store

    @property
    def retry_policy(self) -> RetryPolicy:
        """Return the active RetryPolicy."""
        return self._retry_policy

    @property
    def darpana(self) -> Darpana | None:
        """Return the injected Darpana telemetry service, if configured."""
        return self._darpana

    @property
    def kavacha(self) -> Kavacha | None:
        """Return the injected Kavacha security service, if configured."""
        return self._kavacha

    def _authorize_capability(self, cap: Capability) -> None:
        """Authorize capability's owning plugin security declaration via Kavacha if configured."""
        authorize_capability(self._kavacha, self._registry, cap)

    def _compute_input_hash(self, request: Request, capability: Capability, context: ExecutionContext) -> str:
        """Compute a deterministic, privacy-safe hash identifying the canonical execution attempt."""
        return compute_input_hash(request, capability, context)

    def _record_pramana_if_available(
        self,
        capability: Capability,
        result: Result,
        context: ExecutionContext,
    ) -> None:
        """Record quality observation to Darpana Pramana telemetry if evidence-backed facts exist."""
        record_pramana_if_available(self._darpana, capability, result, context)

    def _quarantine_transition_scope(
        self,
        context: ExecutionContext,
        capability_id: str,
        lifecycle_status: str,
        attempt_count: int,
        max_retries: int,
    ):
        """Timing scope for actual quarantine lifecycle state transitions."""
        return quarantine_transition_scope(
            self._darpana, context, capability_id, lifecycle_status, attempt_count, max_retries
        )

    def _execute_retry_attempt(
        self,
        cap: Capability,
        request: Request,
        context: ExecutionContext,
        record: QuarantineRecord,
        prior_result: Result | None = None,
    ) -> tuple[Result | None, QuarantineRecord]:
        """Execute one retry attempt through Yantra with full failure lifecycle handling."""
        return _execute_retry_attempt_impl(
            cap=cap,
            request=request,
            context=context,
            record=record,
            prior_result=prior_result,
            quarantine_store=self._quarantine_store,
            retry_policy=self._retry_policy,
            yantra=self._yantra,
            darpana=self._darpana,
            kavacha=self._kavacha,
            registry=self._registry,
        )

    def execute(
        self,
        plan: CapabilityPlan,
        request: Request,
        context: ExecutionContext,
    ) -> Result:
        """Execute a resolved capability plan across configured capabilities through Yantra."""
        return execute_pipeline(
            plan=plan,
            request=request,
            context=context,
            manthan=self._manthan,
            registry=self._registry,
            yantra=self._yantra,
            capabilities=self._capabilities,
            quarantine_store=self._quarantine_store,
            retry_policy=self._retry_policy,
            darpana=self._darpana,
            kavacha=self._kavacha,
            smriti=self._smriti,
        )

    def apply_lifecycle_action(
        self,
        action: LifecycleAction,
        *,
        request: Request | None = None,
        context: ExecutionContext | None = None,
    ) -> QuarantineRecord:
        """Apply a validated lifecycle transition (release, retry, terminate) to a quarantined item."""
        return _apply_lifecycle_action(
            action=action,
            request=request,
            context=context,
            quarantine_store=self._quarantine_store,
            retry_policy=self._retry_policy,
            yantra=self._yantra,
            darpana=self._darpana,
            kavacha=self._kavacha,
            registry=self._registry,
            capabilities=self._capabilities,
        )
