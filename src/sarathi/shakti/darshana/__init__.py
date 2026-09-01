"""Darshana — Intake Identification Plugin for Sarathi V2."""

from __future__ import annotations

from sarathi.shakti.darshana.capability import DarshanaCapability
from sarathi.shakti.darshana.facts import IdentificationFacts
from sarathi.shakti.darshana.identifier import (
    identify_bytes,
    identify_file,
    identify_input,
    identify_request,
)
from sarathi.shakti.darshana.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO

__all__ = [
    "CAPABILITY_DECLARATION",
    "DarshanaCapability",
    "IdentificationFacts",
    "PLUGIN_INFO",
    "identify_bytes",
    "identify_file",
    "identify_input",
    "identify_request",
]
