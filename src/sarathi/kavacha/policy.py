"""Security Policy Definitions for Kavacha in Sarathi V2.

Defines:
- SecurityPolicy: Immutable, explicitly constructed policy for authorization decisions.

Contains configuration contracts only: no filesystem I/O, environment reads,
or global singletons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
    """Explicit immutable security policy governing plugin and capability execution."""

    allow_pii_access: bool
    allow_network_access: bool
    allow_external_processing: bool
    allowed_secrets: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.allow_pii_access, bool):
            raise TypeError(
                f"allow_pii_access must be a bool, got {type(self.allow_pii_access).__name__}."
            )
        if not isinstance(self.allow_network_access, bool):
            raise TypeError(
                f"allow_network_access must be a bool, got {type(self.allow_network_access).__name__}."
            )
        if not isinstance(self.allow_external_processing, bool):
            raise TypeError(
                f"allow_external_processing must be a bool, got {type(self.allow_external_processing).__name__}."
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
