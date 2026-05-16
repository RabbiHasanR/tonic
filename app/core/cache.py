"""Sync Redis cache-aside helpers for the service layer.

Used by `{Post,User,Comment}Service` to cache single-entity reads
(`get_post` / `get_user` / `get_comment`). Values are JSON-encoded dicts;
each service owns its own serializer/deserializer so the cached shape stays
explicit and decoupled from SQLModel internals.

Fails open: any `RedisError` is swallowed and the call returns as if the
cache missed (for reads) or no-op (for writes/deletes). The service then
falls through to Postgres — Redis being down must never break the API.

Kept separate from the async `redis.asyncio` client used by `app.graphql.apq`
because services are synchronous (SQLModel `Session` is sync).
"""

import json
from typing import Optional

import redis
from redis.exceptions import RedisError

from app.core.config import settings

_client: Optional[redis.Redis] = None


def _conn() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def cache_get(key: str) -> Optional[dict]:
    try:
        raw = _conn().get(key)
    except RedisError:
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def cache_set(key: str, value: dict, ttl: int) -> None:
    try:
        _conn().set(key, json.dumps(value), ex=ttl)
    except RedisError:
        pass


def cache_delete(*keys: str) -> None:
    if not keys:
        return
    try:
        _conn().delete(*keys)
    except RedisError:
        pass
