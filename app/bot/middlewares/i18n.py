from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db.repositories import get_user_by_telegram_id


class I18n:
    def __init__(self, base_path: Path, default_language: str) -> None:
        self.default_language = default_language
        self.messages = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in base_path.glob("*.json")
        }

    def t(self, key: str, lang: str | None = None, **kwargs: object) -> str:
        language = lang or self.default_language
        template = self.messages.get(language, {}).get(
            key, self.messages[self.default_language].get(key, key)
        )
        return template.format(**kwargs)


class I18nMiddleware(BaseMiddleware):
    def __init__(self, sessionmaker: async_sessionmaker, settings: Settings, i18n: I18n) -> None:
        self.sessionmaker = sessionmaker
        self.settings = settings
        self.i18n = i18n

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        language = self.settings.default_language
        user = data.get("event_from_user")
        if user:
            async with self.sessionmaker() as session:
                db_user = await get_user_by_telegram_id(session, user.id)
                if db_user:
                    language = db_user.language
        data["i18n"] = self.i18n
        data["lang"] = language
        data["_"] = lambda key, **kwargs: self.i18n.t(key, language, **kwargs)
        return await handler(event, data)

