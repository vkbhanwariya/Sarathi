"""Pravaha - Dynamic Pipeline Engine for Nabhi Kernel in Sarathi V2.

Defines:
- Pravaha: Executes resolved capability plans across injected executable capabilities,
  owns failure lifecycle decisions, bounded retry, quarantine, and release.
"""

from __future__ import annotations

from sarathi.nabhi.pravaha.common import (
    _SAFE_ID_PATTERN,
    authorize_capability,
    compute_input_hash,
    quarantine_transition_scope,
    record_pramana_if_available,
)
from sarathi.nabhi.pravaha.engine import Pravaha
from sarathi.nabhi.pravaha.lifecycle import (
    apply_lifecycle_action,
    execute_retry_attempt,
)
from sarathi.nabhi.pravaha.pipeline import execute_pipeline

__all__ = [
    "Pravaha",
    "_SAFE_ID_PATTERN",
    "apply_lifecycle_action",
    "authorize_capability",
    "compute_input_hash",
    "execute_pipeline",
    "execute_retry_attempt",
    "quarantine_transition_scope",
    "record_pramana_if_available",
]
