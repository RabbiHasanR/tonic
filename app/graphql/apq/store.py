"""Redis-backed store for Automatic Persisted Queries.

Maps `sha256(query) -> query string`. Shared across all uvicorn workers so the
first-time POST register cost is paid once globally, not once per worker.
"""

import logging
from typing import Optional

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)


class APQStore:
    PREFIX = "apq:"
    DEFAULT_TTL = 60 * 60 * 24 * 30

    def __init__(self, url: Optional[str] = None) -> None:
        self._url = url or settings.REDIS_URL
        self._client: Optional[redis.Redis] = None

    def _conn(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    async def get(self, hash_: str) -> Optional[str]:
        try:
            return await self._conn().get(f"{self.PREFIX}{hash_}")
        except RedisError as exc:
            logger.warning("APQ store get failed: %s", exc)
            return None

    async def set(self, hash_: str, query: str, ttl: int = DEFAULT_TTL) -> None:
        try:
            await self._conn().set(f"{self.PREFIX}{hash_}", query, ex=ttl)
        except RedisError as exc:
            logger.warning("APQ store set failed: %s", exc)


apq_store = APQStore()
