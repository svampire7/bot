from __future__ import annotations

from pydantic import BaseModel, Field


class MarzbanUser(BaseModel):
    username: str
    subscription_url: str | None = None
    links: list[str] = Field(default_factory=list)
    data_limit: int | None = None
    used_traffic: int | None = Field(default=None, alias="used_traffic")
    status: str | None = None


class MarzbanUsage(BaseModel):
    data_limit: int | None = None
    used_traffic: int | None = None
    remaining_traffic: int | None = None
