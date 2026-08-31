"""Dosh — Error System for Sarathi V2.

This package defines the small common failure vocabulary:
- FailureCode: Canonical failure classifications.
- DoshError: Single typed exception for classified operational failures.
"""

from __future__ import annotations

from sarathi.dosh.errors import DoshError, FailureCode

__all__ = [
    "DoshError",
    "FailureCode",
]
