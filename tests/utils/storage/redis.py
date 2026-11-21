from utils.storage.redis import _NoopRedis


async def test_noop_redis_get_like_calls_return_none():
  noop = _NoopRedis()
  assert await noop.get('any-key') is None


async def test_noop_redis_set_like_calls_are_safe_no_ops():
  noop = _NoopRedis()
  # must not raise, regardless of args/kwargs shape, for any attribute name.
  assert await noop.set('key', 'value', ex=60) is None
  assert await noop.expire('key', 60) is None
  assert await noop.aclose() is None


async def test_noop_redis_accepts_any_arbitrary_attribute_name():
  noop = _NoopRedis()
  assert await noop.ping() is None
  assert await noop.whatever_future_method_doesnt_exist_yet(1, 2, three=3) is None
