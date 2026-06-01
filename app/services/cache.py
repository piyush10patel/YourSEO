"""Audit result cache with a 24h TTL.

Two interchangeable backends behind a tiny async interface:

  * ``SqliteAuditCache`` — zero-config local file (default). Great for single
    -node/dev; no server to run.
  * ``RedisAuditCache``  — shared, fast, ideal for the Docker stack / multiple
    workers.

Both degrade gracefully: any backend error is logged and treated as a cache
miss (for ``get``) or a no-op (for ``set``), so a flaky cache never breaks an
audit. ``NullCache`` disables caching entirely.

Keys are normalised URLs so ``example.com`` and ``example.com/`` share an entry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from typing import Protocol
from urllib.parse import urlparse

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "audit:v2:"


def normalize_url(url: str) -> str:
    """Canonicalise a URL for cache keying (scheme+host lowercased, no trailing /)."""
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    canon = f"{scheme}://{netloc}{path}"
    if parsed.query:
        canon += f"?{parsed.query}"
    return canon


class AuditCache(Protocol):
    async def get(self, url: str) -> dict | None: ...
    async def set(self, url: str, value: dict) -> None: ...


class NullCache:
    """No-op cache (caching disabled)."""

    async def get(self, url: str) -> dict | None:
        return None

    async def set(self, url: str, value: dict) -> None:
        return None


class SqliteAuditCache:
    """SQLite-backed cache. All DB work runs in a thread to stay non-blocking."""

    def __init__(self, path: str, ttl_seconds: int) -> None:
        self.path = path
        self.ttl = ttl_seconds
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def _init_db(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS audit_cache ("
                    "  key TEXT PRIMARY KEY,"
                    "  value TEXT NOT NULL,"
                    "  created_at REAL NOT NULL"
                    ")"
                )
        except sqlite3.Error:
            logger.exception("Failed to initialise SQLite cache at %s", self.path)

    def _get_sync(self, key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, created_at FROM audit_cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value_json, created_at = row
        if time.time() - created_at > self.ttl:
            return None  # expired (lazily ignored; cleaned on next set)
        return json.loads(value_json)

    def _set_sync(self, key: str, value: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO audit_cache (key, value, created_at) "
                "VALUES (?, ?, ?)",
                (key, json.dumps(value), time.time()),
            )

    async def get(self, url: str) -> dict | None:
        key = _KEY_PREFIX + normalize_url(url)
        try:
            return await asyncio.to_thread(self._get_sync, key)
        except Exception:
            logger.exception("SQLite cache get failed; treating as miss")
            return None

    async def set(self, url: str, value: dict) -> None:
        key = _KEY_PREFIX + normalize_url(url)
        try:
            await asyncio.to_thread(self._set_sync, key, value)
        except Exception:
            logger.exception("SQLite cache set failed; skipping")


class RedisAuditCache:
    """Redis-backed cache using redis.asyncio. TTL is enforced by Redis itself."""

    def __init__(self, redis_url: str, ttl_seconds: int) -> None:
        from redis import asyncio as aioredis  # lazy import (optional dep)

        self.ttl = ttl_seconds
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def get(self, url: str) -> dict | None:
        key = _KEY_PREFIX + normalize_url(url)
        try:
            raw = await self._redis.get(key)
        except Exception:
            logger.exception("Redis cache get failed; treating as miss")
            return None
        return json.loads(raw) if raw else None

    async def set(self, url: str, value: dict) -> None:
        key = _KEY_PREFIX + normalize_url(url)
        try:
            await self._redis.set(key, json.dumps(value), ex=self.ttl)
        except Exception:
            logger.exception("Redis cache set failed; skipping")


def build_cache(settings: Settings | None = None) -> AuditCache:
    """Construct the configured cache backend (falls back to SQLite on error)."""
    settings = settings or get_settings()
    backend = settings.cache_backend.lower()

    if backend == "none":
        return NullCache()

    if backend == "redis":
        try:
            return RedisAuditCache(settings.redis_url, settings.cache_ttl_seconds)
        except Exception:
            logger.exception("Redis cache unavailable; falling back to SQLite cache.")

    return SqliteAuditCache(settings.cache_path, settings.cache_ttl_seconds)
