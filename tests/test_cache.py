"""Cache tests: SQLite round-trip, TTL expiry, URL normalization, factory."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from app.config import Settings
from app.services.cache import (
    NullCache,
    RedisAuditCache,
    SqliteAuditCache,
    build_cache,
    normalize_url,
)


def test_normalize_url_collapses_trailing_slash_and_case() -> None:
    assert normalize_url("https://X.com/") == normalize_url("https://x.com")


async def test_sqlite_cache_round_trip(tmp_path: Path) -> None:
    path = str(tmp_path / "c.sqlite3")
    cache = SqliteAuditCache(path, ttl_seconds=100)

    assert await cache.get("https://example.com") is None
    await cache.set("https://example.com", {"score": 72})
    # Trailing-slash variant hits the same normalized key.
    assert await cache.get("https://example.com/") == {"score": 72}


async def test_sqlite_cache_expiry(tmp_path: Path) -> None:
    path = str(tmp_path / "c.sqlite3")
    cache = SqliteAuditCache(path, ttl_seconds=100)
    await cache.set("https://example.com", {"score": 72})

    # Backdate the row beyond the TTL.
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE audit_cache SET created_at = ?", (time.time() - 200,))

    assert await cache.get("https://example.com") is None


async def test_null_cache_is_noop() -> None:
    cache = NullCache()
    await cache.set("https://example.com", {"x": 1})
    assert await cache.get("https://example.com") is None


def test_build_cache_backends(tmp_path: Path) -> None:
    sqlite_settings = Settings(
        cache_backend="sqlite", cache_path=str(tmp_path / "c.sqlite3")
    )
    assert isinstance(build_cache(sqlite_settings), SqliteAuditCache)

    assert isinstance(build_cache(Settings(cache_backend="none")), NullCache)

    redis_settings = Settings(cache_backend="redis")
    assert isinstance(build_cache(redis_settings), RedisAuditCache)
