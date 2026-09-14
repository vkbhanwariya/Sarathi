"""Statutory and Legal Document Intelligence Shakti Capability Package."""

from __future__ import annotations

from sarathi.shakti.statutory.checksums import (
    verify_cin,
    verify_cnr,
    verify_din,
    verify_gstin,
    verify_pan,
    verify_tan,
)
from sarathi.shakti.statutory.detector import is_statutory_document
from sarathi.shakti.statutory.extractor import extract_statutory_entities
from sarathi.shakti.statutory.models import (
    ECourtsMetadata,
    GSTMetadata,
    IncomeTaxMetadata,
    MCAMetadata,
    StatutoryDocumentType,
    StatutoryEntities,
)
from sarathi.shakti.statutory.provider import StatutoryProvider

__all__ = [
    "ECourtsMetadata",
    "GSTMetadata",
    "IncomeTaxMetadata",
    "MCAMetadata",
    "StatutoryDocumentType",
    "StatutoryEntities",
    "StatutoryProvider",
    "extract_statutory_entities",
    "is_statutory_document",
    "verify_cin",
    "verify_cnr",
    "verify_din",
    "verify_gstin",
    "verify_pan",
    "verify_tan",
]
