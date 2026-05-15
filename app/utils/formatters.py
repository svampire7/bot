from __future__ import annotations

from html import escape


GB = 1024**3


def gb_to_bytes(gb: int) -> int:
    return int(gb * GB)


def bytes_to_gb(value: int | float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / GB, 2)


def toman(value: int) -> str:
    return f"{value:,}"


def optional_gb(value: float | int | None) -> str:
    return "-" if value is None else f"{float(value):.2f} GB"


def html_escape(value: object | None) -> str:
    return escape("" if value is None else str(value), quote=False)


def html_code(value: object | None) -> str:
    return f"<code>{html_escape(value)}</code>"


def html_code_lines(values: list[str] | tuple[str, ...]) -> str:
    return "\n".join(html_code(value) for value in values)
