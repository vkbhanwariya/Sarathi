"""Agni — Sarathi application composition root."""

from sarathi.agni.bootstrap import Agni
from sarathi.nabhi.prana import Prana


def _legacy_prana_view(self: Agni) -> Prana:
    """Return the deprecated Prana compatibility view for older callers."""
    return Prana(self)


# Compatibility only: lifecycle state and behavior live in Agni itself.
Agni.prana = property(_legacy_prana_view)  # type: ignore[attr-defined]
Agni._prana = property(_legacy_prana_view)  # type: ignore[attr-defined]

__all__ = ["Agni"]
