"""
shared/storage/redis.py — Shared async Redis pool.

Initialized once at module load, closed on app shutdown.
Never call Redis.from_url() elsewhere — import from here instead.

`redis` is always a usable object, never None — when REDIS_URL is unset it's a
no-op stand-in instead of a real client, so callers don't need to check for
None before every call:

  from shared.storage import redis
  await redis.set("key", "value")   # no-op when disabled
  await redis.get("key")            # None when disabled — same as a cache miss

Usage in FastAPI route handlers (via Depends):
  from shared.storage import RedisClient
  @router.get("/example")
  async def example(r: RedisClient):
    await r.set("key", "value")

Use REDIS_ENABLED where "disabled" needs to be distinguished from a real
cache miss or error — e.g. health checks.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from config import settings

REDIS_ENABLED: bool = bool(settings.REDIS_URL)


class _NoopRedis:
  """Stand-in for Redis when REDIS_URL is unset.

  Every call is a safe no-op: get-like calls return None (indistinguishable
  from a cache miss), everything else (set, expire, aclose, ...) does nothing.
  """

  async def _noop(self, *_args, **_kwargs) -> None:
    return None

  def __getattr__(self, _name: str):
    return self._noop


redis: Redis | _NoopRedis = Redis.from_url(settings.REDIS_URL, decode_responses=True) if REDIS_ENABLED else _NoopRedis()


async def get_redis() -> AsyncGenerator[Redis | _NoopRedis, None]:
  yield redis


RedisClient = Annotated[Redis | _NoopRedis, Depends(get_redis)]
