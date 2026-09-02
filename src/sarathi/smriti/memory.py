"""L1 In-Memory LRU Cache for Smriti."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading
import time

from sarathi.sankalpa import Result
from sarathi.smriti.key import CacheKey
from sarathi.smriti.policy import CachePolicy
from sarathi.smriti.serialization import is_cacheable_result


@dataclass(slots=True)
class MemoryCacheEntry:
    key: CacheKey
    result: Result
    created_at: float
    accessed_at: float


class MemoryCache:
    """Thread-safe in-memory LRU cache."""

    def __init__(self, policy: CachePolicy | None = None) -> None:
        self._policy = policy or CachePolicy()
        self._lock = threading.RLock()
        self._cache: OrderedDict[str, MemoryCacheEntry] = OrderedDict()

    def get(self, key: CacheKey) -> Result | None:
        """Retrieve result from memory if present and unexpired."""
        with self._lock:
            entry = self._cache.get(key.key_hash)
            if entry is None:
                return None

            now = time.time()
            if not self._policy.is_valid(entry.created_at, now):
                del self._cache[key.key_hash]
                return None

            # Move to end for LRU
            entry.accessed_at = now
            self._cache.move_to_end(key.key_hash)
            return entry.result

    def put(self, key: CacheKey, result: Result) -> None:
        """Store result in memory, evicting LRU items if at capacity."""
        if not is_cacheable_result(result):
            return

        with self._lock:
            now = time.time()
            if key.key_hash in self._cache:
                self._cache.move_to_end(key.key_hash)
                self._cache[key.key_hash] = MemoryCacheEntry(
                    key=key,
                    result=result,
                    created_at=now,
                    accessed_at=now,
                )
                return

            if len(self._cache) >= self._policy.max_entries_l1:
                # Evict least recently used
                self._cache.popitem(last=False)

            self._cache[key.key_hash] = MemoryCacheEntry(
                key=key,
                result=result,
                created_at=now,
                accessed_at=now,
            )

    def invalidate(self, key: CacheKey | None = None, capability_id: str | None = None) -> int:
        """Invalidate specific key, entire capability, or all entries."""
        with self._lock:
            if key is not None:
                if key.key_hash in self._cache:
                    del self._cache[key.key_hash]
                    return 1
                return 0

            if capability_id is not None:
                to_del = [k for k, e in self._cache.items() if e.key.capability_id == capability_id]
                for k in to_del:
                    del self._cache[k]
                return len(to_del)

            count = len(self._cache)
            self._cache.clear()
            return count

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
