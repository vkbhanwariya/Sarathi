"""L2 SQLite Persistent Cache and Unified Smriti Cache Service."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import threading
import time

from sarathi.sankalpa import Result
from sarathi.smriti.key import CacheKey, compute_cache_key
from sarathi.smriti.memory import MemoryCache
from sarathi.smriti.policy import CachePolicy
from sarathi.smriti.serialization import (
    deserialize_result,
    is_cacheable_result,
    serialize_result,
)


class SQLiteCacheStore:
    """Thread-safe SQLite persistent cache for Smriti."""

    def __init__(self, db_path: Path, policy: CachePolicy | None = None) -> None:
        self._db_path = db_path.resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._policy = policy or CachePolicy()
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS smriti_entries (
                    key_hash TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_smriti_cap ON smriti_entries(capability_id);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_smriti_accessed ON smriti_entries(accessed_at);
            """)

    def get(self, key: CacheKey) -> Result | None:
        """Retrieve serialized result from SQLite store if valid."""
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT data_json, created_at FROM smriti_entries WHERE key_hash = ?",
                (key.key_hash,),
            ).fetchone()

            if row is None:
                return None

            data_json, created_at = row
            now = time.time()
            if not self._policy.is_valid(created_at, now):
                conn.execute("DELETE FROM smriti_entries WHERE key_hash = ?", (key.key_hash,))
                return None

            # Update accessed timestamp
            conn.execute(
                "UPDATE smriti_entries SET accessed_at = ? WHERE key_hash = ?",
                (now, key.key_hash),
            )
            try:
                return deserialize_result(data_json)
            except Exception:
                # Corrupted or unparseable entry: prune safely
                conn.execute("DELETE FROM smriti_entries WHERE key_hash = ?", (key.key_hash,))
                return None

    def put(self, key: CacheKey, result: Result) -> None:
        """Store serialized result in SQLite store and enforce L2 capacity limits."""
        if not is_cacheable_result(result):
            return

        data_json = serialize_result(result)
        now = time.time()

        with self._lock, self._get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM smriti_entries").fetchone()[0]
            if count >= self._policy.max_entries_l2:
                conn.execute("""
                    DELETE FROM smriti_entries WHERE key_hash IN (
                        SELECT key_hash FROM smriti_entries ORDER BY accessed_at ASC LIMIT 50
                    )
                """)

            conn.execute("""
                INSERT OR REPLACE INTO smriti_entries
                (key_hash, capability_id, fingerprint, profile, data_json, created_at, accessed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (key.key_hash, key.capability_id, key.fingerprint, key.profile, data_json, now, now))

    def invalidate(self, key: CacheKey | None = None, capability_id: str | None = None) -> int:
        """Invalidate entries from persistent SQLite store."""
        with self._lock, self._get_connection() as conn:
            if key is not None:
                cur = conn.execute("DELETE FROM smriti_entries WHERE key_hash = ?", (key.key_hash,))
                return cur.rowcount
            if capability_id is not None:
                cur = conn.execute("DELETE FROM smriti_entries WHERE capability_id = ?", (capability_id,))
                return cur.rowcount
            cur = conn.execute("DELETE FROM smriti_entries")
            return cur.rowcount


class SmritiCache:
    """Canonical Two-Tier (L1 Memory + L2 SQLite) Cache Service for Sarathi V2."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        policy: CachePolicy | None = None,
    ) -> None:
        self._policy = policy or CachePolicy()
        self._l1 = MemoryCache(policy=self._policy)
        self._l2: SQLiteCacheStore | None = None
        if cache_dir is not None:
            self._l2 = SQLiteCacheStore(db_path=cache_dir / "smriti.db", policy=self._policy)

    def get_with_tier(self, key: CacheKey) -> tuple[Result | None, str | None]:
        """Two-tier lookup returning result and source tier ('l1' or 'l2')."""
        res = self._l1.get(key)
        if res is not None:
            return res, "l1"

        if self._l2 is not None:
            res_l2 = self._l2.get(key)
            if res_l2 is not None:
                self._l1.put(key, res_l2)
                return res_l2, "l2"

        return None, None

    def get(self, key: CacheKey) -> Result | None:
        """Two-tier lookup: L1 Memory -> L2 SQLite with promotion to L1."""
        res, _ = self.get_with_tier(key)
        return res

    def put(self, key: CacheKey, result: Result) -> None:
        """Write through both L1 Memory and L2 SQLite cache if cacheable."""
        if not is_cacheable_result(result):
            return
        self._l1.put(key, result)
        if self._l2 is not None:
            self._l2.put(key, result)

    def invalidate(self, key: CacheKey | None = None, capability_id: str | None = None) -> int:
        """Invalidate across both L1 Memory and L2 SQLite tiers."""
        l1_count = self._l1.invalidate(key=key, capability_id=capability_id)
        l2_count = self._l2.invalidate(key=key, capability_id=capability_id) if self._l2 else 0
        return max(l1_count, l2_count)
