from __future__ import annotations


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

