from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.config import Settings


class AdminFilter(BaseFilter):
    def __init__(self, settings: Settings) -> None:
        self.admin_ids = set(settings.admin_telegram_ids)

    async def __call__(self, message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in self.admin_ids)

