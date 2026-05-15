from __future__ import annotations

import logging
import json as jsonlib
from typing import Any

import aiohttp
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings
from app.marzban.schemas import MarzbanUsage, MarzbanUser
from app.utils.formatters import bytes_to_gb, gb_to_bytes

logger = logging.getLogger(__name__)


class MarzbanAPIError(RuntimeError):
    pass


class MarzbanClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.marzban_base_url.rstrip("/")
        self.token = settings.marzban_token
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "MarzbanClient":
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        if not self.token:
            await self.authenticate()
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.session:
            await self.session.close()

    async def authenticate(self) -> None:
        data = {
            "username": self.settings.marzban_username,
            "password": self.settings.marzban_password,
        }
        payload = await self._raw_request("POST", "/api/admin/token", data=data, auth=False)
        self.token = payload.get("access_token") or payload.get("token")
        if not self.token:
            raise MarzbanAPIError("Marzban login did not return a token")

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        if not self.session:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        headers = {}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        async with self.session.request(
            method, f"{self.base_url}{path}", json=json, data=data, headers=headers
        ) as response:
            if response.status == 401 and auth:
                self.token = None
                await self.authenticate()
                return await self._raw_request(method, path, json=json, data=data, auth=True)
            text = await response.text()
            if response.status >= 400:
                raise MarzbanAPIError(f"Marzban API {response.status}: {text[:500]}")
            if not text:
                return {}
            return await response.json()

    @retry(
        retry=retry_if_exception_type((aiohttp.ClientError, TimeoutError, MarzbanAPIError)),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return await self._raw_request(method, path, **kwargs)

    async def _resolve_inbounds(self) -> dict[str, list[str]]:
        value = self.settings.marzban_inbound_id_or_profile.strip()
        if not value:
            return {}
        if value.isdigit():
            template = await self.request("GET", f"/api/user_template/{value}")
            inbounds = template.get("inbounds") or {}
            if not isinstance(inbounds, dict):
                raise MarzbanAPIError(f"Template {value} has invalid inbounds")
            return {str(protocol): list(tags) for protocol, tags in inbounds.items()}
        if value.startswith("{"):
            parsed = jsonlib.loads(value)
            return {str(protocol): list(tags) for protocol, tags in parsed.items()}
        inbounds: dict[str, list[str]] = {}
        for item in value.split(";"):
            if not item.strip() or ":" not in item:
                continue
            protocol, tags = item.split(":", 1)
            inbounds[protocol.strip()] = [tag.strip() for tag in tags.split(",") if tag.strip()]
        return inbounds

    async def _user_payload(self, username: str, data_limit_gb: int) -> dict[str, Any]:
        inbounds = await self._resolve_inbounds()
        proxies = {protocol: {} for protocol in inbounds}
        return {
            "username": username,
            "proxies": proxies,
            "inbounds": inbounds,
            "data_limit": gb_to_bytes(data_limit_gb),
            "data_limit_reset_strategy": "no_reset",
            "expire": 0,
            "status": "active",
        }

    async def create_user(self, username: str, data_limit_gb: int) -> MarzbanUser:
        payload = await self._user_payload(username, data_limit_gb)
        data = await self.request("POST", "/api/user", json=payload)
        return MarzbanUser.model_validate(data)

    async def get_user(self, username: str) -> MarzbanUser | None:
        try:
            data = await self.request("GET", f"/api/user/{username}")
        except MarzbanAPIError as exc:
            if "404" in str(exc):
                return None
            raise
        return MarzbanUser.model_validate(data)

    async def update_user(self, username: str, data: dict[str, Any]) -> MarzbanUser:
        payload = await self.request("PUT", f"/api/user/{username}", json=data)
        return MarzbanUser.model_validate(payload)

    async def add_traffic_to_user(self, username: str, gb_amount: int) -> MarzbanUser:
        current = await self.get_user(username)
        if not current:
            raise MarzbanAPIError(f"Marzban user {username} not found")
        current_limit_gb = int(bytes_to_gb(current.data_limit or 0) or 0)
        new_limit_gb = current_limit_gb + gb_amount
        return await self.update_user(
            username,
            {
                "data_limit": gb_to_bytes(new_limit_gb),
                "data_limit_reset_strategy": "no_reset",
                "expire": 0,
                "status": "active",
            },
        )

    async def disable_user(self, username: str) -> None:
        try:
            await self.update_user(username, {"status": "disabled"})
        except MarzbanAPIError as exc:
            if "404" in str(exc):
                return
            raise

    async def enable_user(self, username: str) -> None:
        await self.update_user(username, {"status": "active", "expire": 0})

    async def delete_user(self, username: str) -> bool:
        try:
            await self.request("DELETE", f"/api/user/{username}")
        except MarzbanAPIError as exc:
            if "404" in str(exc):
                return False
            raise
        return True

    def get_subscription_url(self, username: str, user: MarzbanUser | None = None) -> str:
        if user and user.subscription_url:
            return user.subscription_url
        if self.settings.marzban_subscription_base_url:
            return f"{self.settings.marzban_subscription_base_url.rstrip('/')}/{username}"
        return f"{self.base_url}/sub/{username}"

    async def get_user_usage(self, username: str) -> MarzbanUsage:
        user = await self.get_user(username)
        if not user:
            raise MarzbanAPIError(f"Marzban user {username} not found")
        remaining = None
        if user.data_limit is not None and user.used_traffic is not None:
            remaining = max(user.data_limit - user.used_traffic, 0)
        return MarzbanUsage(
            data_limit=user.data_limit,
            used_traffic=user.used_traffic,
            remaining_traffic=remaining,
        )
