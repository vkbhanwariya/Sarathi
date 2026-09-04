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
class OutboundRequest:
    """Specification of an outbound network or external operation to be authorized."""

    destination: str
    payload_classification: str = "public"
    requires_external_processing: bool = False
    required_secrets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.destination or not isinstance(self.destination, str) or not self.destination.strip():
            raise ValueError("destination must be a non-empty string.")
        if not isinstance(self.payload_classification, str):
            raise TypeError(f"payload_classification must be a str, got {type(self.payload_classification).__name__}.")
        if not isinstance(self.requires_external_processing, bool):
            raise TypeError(
                f"requires_external_processing must be a bool, got {type(self.requires_external_processing).__name__}."
            )
        if not isinstance(self.required_secrets, (list, tuple)):
            raise TypeError(f"required_secrets must be a sequence of strings, got {type(self.required_secrets).__name__}.")
        cleaned: list[str] = []
        for s in self.required_secrets:
            if not isinstance(s, str) or not s.strip():
                raise ValueError("required_secrets elements must be non-empty strings.")
            cleaned.append(s.strip())
        object.__setattr__(self, "required_secrets", tuple(cleaned))


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

    def evaluate_outbound(self, request: OutboundRequest) -> SecurityDecision:
        """Evaluate an OutboundRequest against this policy and return a SecurityDecision."""
        if not isinstance(request, OutboundRequest):
            raise TypeError(f"request must be an OutboundRequest instance, got {type(request).__name__}.")

        # 1. Network access check
        if not self.allow_network_access:
            return SecurityDecision(
                allowed=False,
                message="Outbound network access is not permitted by security policy.",
            )

        # 2. External processing check
        if request.requires_external_processing and not self.allow_external_processing:
            return SecurityDecision(
                allowed=False,
                message="Outbound external processing is not permitted by security policy.",
            )

        # 3. Payload classification / privacy check
        if request.payload_classification.strip().lower() in ("pii", "document_content", "confidential"):
            if not self.allow_pii_access:
                return SecurityDecision(
                    allowed=False,
                    message="Outbound transmission of sensitive payload is not permitted by security policy.",
                )

        # 4. Secrets authorization check
        if request.required_secrets:
            allowed_set = set(self.allowed_secrets)
            for sec in request.required_secrets:
                if sec not in allowed_set:
                    return SecurityDecision(
                        allowed=False,
                        message=f"Required secret '{sec}' is not permitted by security policy.",
                    )

        return SecurityDecision(allowed=True)
