"""Redis-backed token bucket rate limiter.

Each client key (`rl:u:{user_id}` for authed, `rl:ip:{client_ip}` for anon)
has a bucket holding up to `RATE_LIMIT_CAPACITY` tokens, refilling at
`RATE_LIMIT_REFILL_PER_SECOND` per second. Each request consumes `cost`
tokens (the computed query complexity). Insufficient tokens → reject with
a retry-after hint.

Atomicity is non-negotiable: with multiple uvicorn workers (and multiple
containers) all racing on the same key, a naive Python read-modify-write
would let bursts slip past the limit. We push the whole check into a Lua
script — Redis runs it atomically.

Fail-open: any `RedisError` lets the request through (logging is left to
the caller's discretion). Availability beats strictness during an outage.
"""

import time
from typing import Optional

import redis
from redis.exceptions import RedisError

from app.core.config import settings

# KEYS[1] = bucket hash key
# ARGV[1] = now (float seconds)
# ARGV[2] = cost (number, must be > 0)
# ARGV[3] = capacity (number)
# ARGV[4] = refill_rate (tokens per second)
# Returns: {allowed (0/1), retry_after_seconds (string)}
_LUA = """
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])
local refill = tonumber(ARGV[4])

local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity end
if ts == nil then ts = now end

local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * refill)

if tokens < cost then
  local need = cost - tokens
  local retry = need / refill
  redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
  redis.call('EXPIRE', KEYS[1], math.ceil(capacity / refill) + 60)
  return {0, tostring(retry)}
end

tokens = tokens - cost
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / refill) + 60)
return {1, '0'}
"""


class TokenBucket:
    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None
        self._script_sha: Optional[str] = None

    def _conn(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._client

    def _script(self):
        conn = self._conn()
        if self._script_sha is None:
            self._script_sha = conn.script_load(_LUA)
        return self._script_sha

    def check(self, key: str, cost: int) -> tuple[bool, float]:
        """Atomically refill + try to consume `cost` tokens.

        Returns `(allowed, retry_after_seconds)`. On Redis error, fails open
        (returns `(True, 0.0)`).
        """
        if cost <= 0:
            return True, 0.0
        try:
            conn = self._conn()
            sha = self._script()
            res = conn.evalsha(
                sha,
                1,
                key,
                str(time.time()),
                str(cost),
                str(settings.RATE_LIMIT_CAPACITY),
                str(settings.RATE_LIMIT_REFILL_PER_SECOND),
            )
        except redis.exceptions.NoScriptError:
            # Redis restarted and forgot the cached script; reload + retry once.
            self._script_sha = None
            try:
                res = self._conn().eval(
                    _LUA,
                    1,
                    key,
                    str(time.time()),
                    str(cost),
                    str(settings.RATE_LIMIT_CAPACITY),
                    str(settings.RATE_LIMIT_REFILL_PER_SECOND),
                )
            except RedisError:
                return True, 0.0
        except RedisError:
            return True, 0.0

        allowed = int(res[0]) == 1
        retry = float(res[1]) if not allowed else 0.0
        return allowed, retry


bucket = TokenBucket()
