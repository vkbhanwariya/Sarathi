"""Kavacha — Security & Privacy Service for Sarathi V2.

Delegates authorization decisions to SecurityPolicy.
Contains no filesystem I/O, secret storage, PII scanning, network clients,
logging, or telemetry.
"""

from __future__ import annotations

from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha.policy import SecurityDecision, SecurityPolicy
from sarathi.sankalpa import SecurityDeclaration


class Kavacha:
    """Security authorization service for Sarathi runtime."""

    def __init__(self, policy: SecurityPolicy) -> None:
        if not isinstance(policy, SecurityPolicy):
            raise TypeError(f"policy must be a SecurityPolicy instance, got {type(policy).__name__}.")
        self._policy: SecurityPolicy = policy

    @property
    def policy(self) -> SecurityPolicy:
        """Return the active immutable SecurityPolicy."""
        return self._policy

    def authorize(self, declaration: SecurityDeclaration) -> None:
        """Authorize a plugin/capability security declaration against the active policy.

        Raises:
            DoshError(FailureCode.SECURITY_DENIED): If any declared requirement violates policy.
            TypeError: If declaration is not a SecurityDeclaration.
        """
        if not isinstance(declaration, SecurityDeclaration):
            raise TypeError(
                f"declaration must be a SecurityDeclaration instance, got {type(declaration).__name__}."
            )

        decision = self._policy.evaluate(declaration)
        if not decision.allowed:
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message=decision.message or "Security policy denied authorization.",
            )
