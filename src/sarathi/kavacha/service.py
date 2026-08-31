"""Kavacha — Security & Privacy Service for Sarathi V2.

Evaluates Sankalpa SecurityDeclarations against an explicit SecurityPolicy.
Contains no filesystem I/O, secret storage, PII scanning, network clients,
logging, or telemetry.
"""

from __future__ import annotations

from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha.policy import SecurityPolicy
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

        # 1. PII access check
        if declaration.pii_access and not self._policy.allow_pii_access:
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="PII access is not permitted by security policy.",
            )

        # 2. Network access check
        if declaration.network_access and not self._policy.allow_network_access:
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message="Network access is not permitted by security policy.",
            )

        # 3. External processing check (requires external permission AND network permission)
        if declaration.external_processing:
            if not self._policy.allow_external_processing:
                raise DoshError(
                    code=FailureCode.SECURITY_DENIED,
                    message="External processing is not permitted by security policy.",
                )
            if not self._policy.allow_network_access:
                raise DoshError(
                    code=FailureCode.SECURITY_DENIED,
                    message="External processing requires network access, which is not permitted by policy.",
                )

        # 4. Secret access check
        if declaration.required_secrets:
            allowed_set = set(self._policy.allowed_secrets)
            for secret_name in declaration.required_secrets:
                if secret_name not in allowed_set:
                    raise DoshError(
                        code=FailureCode.SECURITY_DENIED,
                        message="One or more required secrets are not permitted by security policy.",
                    )
