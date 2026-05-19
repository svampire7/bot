from __future__ import annotations

import time


class SettingsCache:
    def __init__(self, ttl_seconds: int = 60) -> None:
        self.ttl_seconds = ttl_seconds
        self._values: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> str | None:
        item = self._values.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            self._values.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str) -> None:
        self._values[key] = (time.monotonic() + self.ttl_seconds, value)

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._values.clear()
        else:
            self._values.pop(key, None)


settings_cache = SettingsCache()
