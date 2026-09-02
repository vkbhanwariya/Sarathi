"""Security Policy Definitions for Kavacha in Sarathi V2.

Defines:
- SecurityDecision: Immutable authorization outcome.
- SecurityPolicy: Immutable, explicitly constructed policy for authorization decisions.

Contains configuration contracts only: no filesystem I/O, environment reads,
or global singletons.
"""

from __future__ import annotations

from dataclasses import dataclass

from sarathi.sankalpa import SecurityDeclaration


@dataclass(frozen=True, slots=True)
class SecurityDecision:
    """Immutable authorization decision produced by SecurityPolicy evaluation."""

    allowed: bool
    message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise TypeError(f"allowed must be a bool, got {type(self.allowed).__name__}.")
        if self.message is not None and not isinstance(self.message, str):
            raise TypeError(f"message must be a str or None, got {type(self.message).__name__}.")


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
    """Explicit immutable security policy governing plugin and capability execution."""

    allow_pii_access: bool
    allow_network_access: bool
    allow_external_processing: bool
    allowed_secrets: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.allow_pii_access, bool):
            raise TypeError(f"allow_pii_access must be a bool, got {type(self.allow_pii_access).__name__}.")
        if not isinstance(self.allow_network_access, bool):
            raise TypeError(f"allow_network_access must be a bool, got {type(self.allow_network_access).__name__}.")
        if not isinstance(self.allow_external_processing, bool):
            raise TypeError(
                f"allow_external_processing must be a bool, got {type(self.allow_external_processing).__name__}."
            )

        if self.allow_external_processing and not self.allow_network_access:
            raise ValueError(
                "SecurityPolicy consistency error: allow_external_processing=True requires allow_network_access=True."
            )

        if isinstance(self.allowed_secrets, set):
            raise TypeError("allowed_secrets must be an ordered sequence (list or tuple), not a set.")
        if not isinstance(self.allowed_secrets, (list, tuple)):
            raise TypeError(
                f"allowed_secrets must be an ordered sequence of strings, got {type(self.allowed_secrets).__name__}."
            )

        cleaned_secrets: list[str] = []
        seen: set[str] = set()
        for s in self.allowed_secrets:
            if not isinstance(s, str):
                raise TypeError(f"allowed_secrets elements must be strings, got {type(s).__name__}.")
            trimmed = s.strip()
            if not trimmed:
                raise ValueError("allowed_secrets cannot contain empty or whitespace-only strings.")
            if trimmed in seen:
                raise ValueError(f"Duplicate secret in allowed_secrets: {trimmed!r}")
            seen.add(trimmed)
            cleaned_secrets.append(trimmed)

        object.__setattr__(self, "allowed_secrets", tuple(cleaned_secrets))

    def evaluate(self, declaration: SecurityDeclaration) -> SecurityDecision:
        """Evaluate a SecurityDeclaration against this policy and return a SecurityDecision."""
        if not isinstance(declaration, SecurityDeclaration):
            raise TypeError(f"declaration must be a SecurityDeclaration instance, got {type(declaration).__name__}.")

        # 1. PII access check
        if declaration.pii_access and not self.allow_pii_access:
            return SecurityDecision(
                allowed=False,
                message="PII access is not permitted by security policy.",
            )

        # 2. Network access check
        if declaration.network_access and not self.allow_network_access:
            return SecurityDecision(
                allowed=False,
                message="Network access is not permitted by security policy.",
            )

        # 3. External processing check
        if declaration.external_processing:
            if not self.allow_external_processing:
                return SecurityDecision(
                    allowed=False,
                    message="External processing is not permitted by security policy.",
                )
            if not self.allow_network_access:
                return SecurityDecision(
                    allowed=False,
                    message="External processing requires network access, which is not permitted by policy.",
                )

        # 4. Secret access check
        if declaration.required_secrets:
            allowed_set = set(self.allowed_secrets)
            for secret_name in declaration.required_secrets:
                if secret_name not in allowed_set:
                    return SecurityDecision(
                        allowed=False,
                        message="One or more required secrets are not permitted by security policy.",
                    )

        return SecurityDecision(allowed=True)
