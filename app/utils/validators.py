from __future__ import annotations

import re


USERNAME_RE = re.compile(r"[^a-zA-Z0-9_]")


def sanitize_username(value: str) -> str:
    return USERNAME_RE.sub("_", value)[:64]


def parse_positive_int(text: str) -> int | None:
    try:
        value = int(text.strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None

