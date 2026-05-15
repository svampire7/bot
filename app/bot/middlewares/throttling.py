from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from redis.asyncio import Redis


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, redis: Redis, default_limit_seconds: int = 1) -> None:
        self.redis = redis
        self.default_limit_seconds = default_limit_seconds

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)
        key = f"throttle:{user.id}:{getattr(event, 'event_type', event.__class__.__name__)}"
        now = time.time()
        added = await self.redis.set(key, str(now), nx=True, ex=self.default_limit_seconds)
        if not added:
            return None
        return await handler(event, data)

