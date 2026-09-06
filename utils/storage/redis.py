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
