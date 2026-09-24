"""L1 In-Memory LRU Cache for Smriti."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from types import MappingProxyType
from typing import Any

from sarathi.sankalpa import Result
from sarathi.smriti.key import CacheKey
from sarathi.smriti.policy import CachePolicy
from sarathi.smriti.serialization import is_cacheable_result

_IMMUTABLE_TYPES = (int, float, str, bytes, bool, type(None))


def _defensive_copy(value: Any) -> Any:
    """Copy canonical cache values without process-global deepcopy hooks."""
    if isinstance(value, _IMMUTABLE_TYPES):
        return value
    if isinstance(value, list):
        return [_defensive_copy(item) for item in value]
    if isinstance(value, dict):
        return {_defensive_copy(key): _defensive_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        if not value:
            return value
        copied_items = [_defensive_copy(item) for item in value]
        if any(c is not orig for c, orig in zip(copied_items, value)):
            return tuple(copied_items)
        return value
    if isinstance(value, MappingProxyType):
        if not value:
            return value
        copied_mapping = {_defensive_copy(key): _defensive_copy(item) for key, item in value.items()}
        if any(copied_mapping[key] is not item for key, item in value.items()):
            return MappingProxyType(copied_mapping)
        return value
    if isinstance(value, Mapping):
        return {_defensive_copy(key): _defensive_copy(item) for key, item in value.items()}
    if isinstance(value, frozenset):
        if not value:
            return value
        copied_set = [_defensive_copy(item) for item in value]
        if any(c is not orig for c, orig in zip(copied_set, value)):
            return frozenset(copied_set)
        return value
    if isinstance(value, set):
        return {_defensive_copy(item) for item in value}
    if is_dataclass(value) and not isinstance(value, type):
        is_frozen = getattr(getattr(value, "__dataclass_params__", None), "frozen", False)
        updates: dict[str, Any] = {}
        has_changes = False
        for field in fields(value):
            if not field.init:
                continue
            orig = getattr(value, field.name)
            copied = _defensive_copy(orig)
            if copied is not orig:
                has_changes = True
                updates[field.name] = copied
            else:
                updates[field.name] = orig
        if is_frozen and not has_changes:
            return value
        return replace(value, **updates)
    return value


def _estimate_data_bytes(val: Any, depth: int = 0) -> int:
    """Recursively estimate in-memory byte size of cached data payloads."""
    if depth > 4 or val is None:
        return 0
    if isinstance(val, (bytes, bytearray)):
        return len(val)
    if isinstance(val, str):
        return len(val.encode("utf-8", errors="ignore"))
    if hasattr(val, "text") and isinstance(val.text, str):
        size = len(val.text.encode("utf-8", errors="ignore"))
        if hasattr(val, "tables") and isinstance(val.tables, (list, tuple)):
            for t in val.tables:
                if hasattr(t, "rows") and isinstance(t.rows, (list, tuple)):
                    for r in t.rows:
                        if isinstance(r, (list, tuple)):
                            size += sum(len(str(c).encode("utf-8", errors="ignore")) for c in r)
        return size
    if hasattr(val, "pages") and isinstance(val.pages, (list, tuple)):
        size = 0
        for p in val.pages:
            if hasattr(p, "text") and isinstance(p.text, str):
                size += len(p.text.encode("utf-8", errors="ignore"))
        return size
    if isinstance(val, (list, tuple, set, frozenset)):
        return sum(_estimate_data_bytes(item, depth + 1) for item in val)
    if isinstance(val, (dict, Mapping, MappingProxyType)):
        return sum(_estimate_data_bytes(k, depth + 1) + _estimate_data_bytes(v, depth + 1) for k, v in val.items())
    if hasattr(val, "content") and isinstance(val.content, (bytes, str)):
        return len(val.content) if isinstance(val.content, bytes) else len(val.content.encode("utf-8", errors="ignore"))
    return 64


def _estimate_result_bytes(res: Result) -> int:
    """Estimate in-memory byte size of a Result object."""
    total = 256
    if res.artifact_payloads:
        for p in res.artifact_payloads:
            if hasattr(p, "content") and p.content:
                total += len(p.content) if isinstance(p.content, (bytes, bytearray)) else len(str(p.content).encode("utf-8", errors="ignore"))
    if res.data is not None:
        total += _estimate_data_bytes(res.data)
    return max(512, total)



@dataclass(slots=True)
class MemoryCacheEntry:
    key: CacheKey
    result: Result
    created_at: float
    size_bytes: int = 0


class MemoryCache:
    """Thread-safe in-memory LRU cache bounded by count and byte budget."""

    def __init__(self, policy: CachePolicy | None = None) -> None:
        self._policy = policy or CachePolicy()
        self._lock = threading.RLock()
        self._cache: OrderedDict[str, MemoryCacheEntry] = OrderedDict()
        self._current_bytes: int = 0

    @property
    def current_bytes(self) -> int:
        with self._lock:
            return self._current_bytes

    def get(self, key: CacheKey) -> Result | None:
        """Retrieve result from memory if present and unexpired."""
        with self._lock:
            entry = self._cache.get(key.key_hash)
            if entry is None:
                return None

            now = time.time()
            if not self._policy.is_valid(entry.created_at, now):
                self._current_bytes = max(0, self._current_bytes - entry.size_bytes)
                del self._cache[key.key_hash]
                return None

            self._cache.move_to_end(key.key_hash)
            return _defensive_copy(entry.result)

    def put(
        self,
        key: CacheKey,
        result: Result,
        created_at: float | None = None,
        validate: bool = True,
    ) -> bool:
        """Store result in memory, evicting LRU items if at count or byte capacity."""
        if validate and not is_cacheable_result(result):
            return False

        with self._lock:
            now = time.time()
            entry_created_at = created_at if created_at is not None else now
            result_copy = _defensive_copy(result)
            est_size = _estimate_result_bytes(result_copy)

            if key.key_hash in self._cache:
                old_entry = self._cache[key.key_hash]
                self._current_bytes = max(0, self._current_bytes - old_entry.size_bytes)
                self._cache.move_to_end(key.key_hash)
                self._cache[key.key_hash] = MemoryCacheEntry(
                    key=key,
                    result=result_copy,
                    created_at=entry_created_at,
                    size_bytes=est_size,
                )
                self._current_bytes += est_size
                return True

            # Evict LRU items if at count capacity or byte capacity
            while self._cache and (
                len(self._cache) >= self._policy.max_entries_l1
                or (self._current_bytes + est_size > self._policy.max_bytes_l1 and self._current_bytes > 0)
            ):
                _, evicted = self._cache.popitem(last=False)
                self._current_bytes = max(0, self._current_bytes - evicted.size_bytes)

            self._cache[key.key_hash] = MemoryCacheEntry(
                key=key,
                result=result_copy,
                created_at=entry_created_at,
                size_bytes=est_size,
            )
            self._current_bytes += est_size
            return True

    def invalidate(self, key: CacheKey | None = None, capability_id: str | None = None) -> int:
        """Invalidate specific key, entire capability, or all entries."""
        with self._lock:
            if key is not None:
                if key.key_hash in self._cache:
                    entry = self._cache.pop(key.key_hash)
                    self._current_bytes = max(0, self._current_bytes - entry.size_bytes)
                    return 1
                return 0

            if capability_id is not None:
                to_del = [k for k, e in self._cache.items() if e.key.capability_id == capability_id]
                for k in to_del:
                    entry = self._cache.pop(k)
                    self._current_bytes = max(0, self._current_bytes - entry.size_bytes)
                return len(to_del)

            count = len(self._cache)
            self._cache.clear()
            self._current_bytes = 0
            return count

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
