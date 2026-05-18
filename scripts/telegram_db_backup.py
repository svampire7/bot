from __future__ import annotations

import asyncio
import gzip
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import aiohttp


BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/backups"))
BACKUP_TIME = os.getenv("BACKUP_TIME", "03:30")
BACKUP_TIMEZONE = os.getenv("BACKUP_TIMEZONE", "Asia/Tehran")
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "7"))


def admin_ids() -> list[int]:
    raw = os.getenv("ADMIN_TELEGRAM_IDS", "")
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def parse_database_url() -> dict[str, str]:
    url = os.getenv("DATABASE_URL", "")
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if not parsed.hostname or not parsed.path:
        raise RuntimeError("DATABASE_URL is invalid")
    return {
        "host": parsed.hostname,
        "port": str(parsed.port or 5432),
        "user": parsed.username or "",
        "password": parsed.password or "",
        "db": parsed.path.lstrip("/"),
    }


def next_run_at() -> datetime:
    hour, minute = [int(part) for part in BACKUP_TIME.split(":", 1)]
    tz = ZoneInfo(BACKUP_TIMEZONE)
    now = datetime.now(tz)
    run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if run_at <= now:
        run_at += timedelta(days=1)
    return run_at


def create_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    db = parse_database_url()
    timestamp = datetime.now(ZoneInfo(BACKUP_TIMEZONE)).strftime("%Y%m%d_%H%M%S")
    sql_path = BACKUP_DIR / f"vpnbot_{timestamp}.sql"
    gz_path = BACKUP_DIR / f"{sql_path.name}.gz"
    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"]
    command = [
        "pg_dump",
        "-h",
        db["host"],
        "-p",
        db["port"],
        "-U",
        db["user"],
        "-d",
        db["db"],
        "--no-owner",
        "--no-privileges",
        "-f",
        str(sql_path),
    ]
    subprocess.run(command, check=True, env=env)
    with sql_path.open("rb") as source, gzip.open(gz_path, "wb") as target:
        shutil.copyfileobj(source, target)
    sql_path.unlink(missing_ok=True)
    return gz_path


async def send_backup(path: Path) -> None:
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing")
    caption = f"VPN bot database backup\n{path.name}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        for admin_id in admin_ids():
            data = aiohttp.FormData()
            data.add_field("chat_id", str(admin_id))
            data.add_field("caption", caption)
            data.add_field(
                "document",
                path.open("rb"),
                filename=path.name,
                content_type="application/gzip",
            )
            async with session.post(f"https://api.telegram.org/bot{token}/sendDocument", data=data) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(f"Telegram sendDocument failed for {admin_id}: {response.status} {text[:300]}")


def prune_old_backups() -> None:
    cutoff = datetime.now().timestamp() - BACKUP_RETENTION_DAYS * 86400
    for path in BACKUP_DIR.glob("vpnbot_*.sql.gz"):
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


async def run_once() -> None:
    backup = create_backup()
    await send_backup(backup)
    prune_old_backups()
    print(f"Backup sent: {backup}", flush=True)


async def main() -> None:
    if os.getenv("BACKUP_RUN_ONCE", "false").lower() == "true":
        await run_once()
        return
    while True:
        run_at = next_run_at()
        sleep_seconds = max((run_at - datetime.now(ZoneInfo(BACKUP_TIMEZONE))).total_seconds(), 1)
        print(f"Next backup at {run_at.isoformat()}", flush=True)
        await asyncio.sleep(sleep_seconds)
        try:
            await run_once()
        except Exception as exc:
            print(f"Backup failed: {exc}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
