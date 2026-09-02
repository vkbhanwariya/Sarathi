"""Contract 3 & 4: Validity, Invalidation, and Retention Policies."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """Configurable validity and capacity policy for Smriti cache."""

    ttl_seconds: int | None = 86400  # Default 24 hours
    max_entries_l1: int = 200  # Max items in L1 memory
    max_entries_l2: int = 2000  # Max items in L2 SQLite

    def is_valid(self, created_at: float, current_time: float | None = None) -> bool:
        """Check whether a cached item remains valid under TTL policy."""
        if self.ttl_seconds is None:
            return True
        now = current_time if current_time is not None else time.time()
        return (now - created_at) < self.ttl_seconds
