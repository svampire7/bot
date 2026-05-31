# Marzban Telegram VPN Bot

A Dockerized bilingual Persian/English Telegram bot for selling V2Ray VPN traffic packages and unlimited time packages through Marzban. Users charge their wallet, buy a package, and the bot creates or renews the Marzban user and sends the subscription link.

## Features

- Python 3.11, aiogram 3, PostgreSQL, Redis, SQLAlchemy 2, Alembic
- Persian default, English optional, all user-facing text in `app/bot/i18n/fa.json` and `app/bot/i18n/en.json`
- Manual card-to-card payment workflow with receipt upload
- Admin Telegram panel with pending orders, approvals, rejection, search, stats, broadcast, service actions
- Marzban API client with login, token refresh, retry, create/update/delete/disable, usage, subscription URL
- One active VPN service per Telegram user by default
- Traffic renewal adds GB to the same Marzban user and keeps the same subscription link
- Unlimited time packages use the same Marzban user with no traffic limit and an expiry date
- Docker Compose with bot, PostgreSQL, Redis, healthchecks, and automatic migrations

## Create Telegram Bot

1. Open Telegram and message `@BotFather`.
2. Run `/newbot`.
3. Choose a display name and username.
4. Copy the bot token.
5. Put it in `.env` as `BOT_TOKEN=...`.

## Configure `.env`

Copy the example file:

```bash
cp .env.example .env
```

Edit these required values:

```env
BOT_TOKEN=
ADMIN_TELEGRAM_IDS=123456789,987654321
TELEGRAM_PROXY_URL=

MARZBAN_BASE_URL=https://your-marzban.example.com
MARZBAN_USERNAME=admin
MARZBAN_PASSWORD=secret
MARZBAN_INBOUND_ID_OR_PROFILE=3

CARD_NUMBER=6037...
CARD_REFERENCE_REQUIRED=false
CARD_HOLDER_NAME=Your Name
BANK_NAME=Your Bank
SUPPORT_USERNAME=@support
CRYPTO_LTC_WALLET=
CRYPTO_LTC_QR_FILE_ID=
LTC_PRICE_API_URL=https://api.wallex.ir/v1/markets
LTC_TOMAN_RATE=7000000
CRYPTO_LTC_BONUS_PERCENT=0
CRYPTO_LTC_BONUS_PERCENT=0
PACKAGE_PRICES_TOMAN=1:220000,3:600000,5:900000,10:1600000
UNLIMITED_TIME_PACKAGES_TOMAN=30:900000,90:2400000,180:4500000,365:8000000
```

The default price is `220000` Toman per GB. Custom package limits are controlled by `MIN_CUSTOM_GB` and `MAX_CUSTOM_GB`.

`UNLIMITED_TIME_PACKAGES_TOMAN` uses `days:price` items. For example, `30:900000` means unlimited traffic for 30 days at 900,000 Toman. Admins can edit this later from bot settings or the web admin settings page.

`CARD_REFERENCE_REQUIRED=false` keeps card transfer visible to everyone. When enabled from `.env` or Admin Settings, new users must enter a valid reference code from an already-known user before the bot shows card details. LTC wallet top-up stays visible without a reference code.

If your server cannot reach `https://api.telegram.org`, set `TELEGRAM_PROXY_URL` to an HTTP/SOCKS proxy URL supported by aiohttp, or deploy on a server/network with Telegram API access. `TELEGRAM_REQUEST_TIMEOUT` controls how long a single Telegram API send/edit call may wait before failing; lower values make the bot recover faster from bad Telegram routes.

## Run With Docker Compose

```bash
docker compose up --build -d
```

The bot waits for PostgreSQL and Redis healthchecks, runs:

```bash
alembic upgrade head
```

and then starts polling Telegram.

View logs:

```bash
docker compose logs -f bot
```

Stop:

```bash
docker compose down
```

## Production Hardening

The bot includes a few safeguards for larger usage:

- User language is cached in Redis to avoid a database lookup on every Telegram update.
- Editable bot settings are cached briefly in-process and invalidated after admin changes.
- Marzban login tokens and inbound/template data are cached to reduce panel API calls.
- Broadcasts are sent in controlled batches. Configure with:

```env
BROADCAST_BATCH_SIZE=25
BROADCAST_BATCH_DELAY_SECONDS=1
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
```

Admins can check runtime health from:

`/admin` → `System Status`

This checks database and Redis connectivity and shows broadcast batch settings.

Run tests and lint checks:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check app tests
```

For safer server updates, use:

```bash
scripts/deploy_safe.sh
```

It creates a Telegram database backup before pulling code and rebuilding the bot container.

## Run Migrations Manually

Inside the bot container:

```bash
docker compose run --rm bot alembic upgrade head
```

Create a new migration after model changes:

```bash
docker compose run --rm bot alembic revision --autogenerate -m "change message"
```

## Admin Approval Flow

1. User selects a traffic package or an unlimited time package.
2. User chooses whether the service is for themselves or another person.
3. For another person, the buyer can choose either:
   - receive a redeem code/link so the real customer activates the service in their own Telegram account
   - create a standalone config immediately and forward the subscription/config data themselves
4. With redeem codes, the real customer starts the bot and enters the redeem code from `Redeem Gift Code`, or opens the direct redeem link.
5. With direct config delivery, the bot creates a standalone Marzban account and stores it as a bulk account, without touching the buyer's own active service.
6. If a manual receipt flow is enabled later, the bot stores only Telegram `file_id`, not the actual receipt file.
7. Approval locks/checks order status first. If it is not `pending_admin`, duplicate approval is rejected.
8. If Marzban succeeds, order becomes `completed` and the recipient receives service data.
9. If Marzban fails, order becomes `failed`, the error is saved in `admin_note`, and admin is notified.

## Card Reference Gate

Admins can enable or disable the card-number gate from:

`/admin` → `Settings` → `Card Gate`

Accepted values are `1`/`0` or `on`/`off`.

When enabled:

- New users can still see and use Litecoin wallet charging.
- Card transfer asks for a reference code before showing the card number.
- Every user has a personal reference code in `Invite Friends`.
- A reference code is accepted only if it belongs to an already-known user, meaning a user with a completed order, active service, completed wallet top-up, or previously unlocked card access.
- After a valid code is entered once, card access stays unlocked for that Telegram user.

## Live LTC Wallet Top-up Pricing

When a user charges their wallet with Litecoin, the bot fetches the live LTC/Toman price from `LTC_PRICE_API_URL` and locks that rate into a 30-minute quote. The transaction hash is verified against the exact LTC amount from that quote, so the user’s wallet is credited in Toman/Rial terms even though they paid with LTC.

`LTC_TOMAN_RATE` is a manual fallback rate if the live price API is temporarily unavailable.

Admins can adjust the crypto wallet bonus from:

`/admin` → `Settings` → `LTC Bonus`

For example, with `10`, if the user pays for `900,000` Toman, their wallet receives `990,000` Toman after the LTC payment is verified.

## Marzban Integration

The client lives in `app/marzban/client.py`.

Supported operations:

- `authenticate`
- `create_user`
- `get_user`
- `update_user`
- `add_traffic_to_user`
- `disable_user`
- `delete_user`
- `get_subscription_url`
- `get_user_usage`

`MARZBAN_INBOUND_ID_OR_PROFILE` can be either:

- a Marzban user template ID, for example `3`
- explicit inbound tags, for example `vless:VLESS gRPC TLS,VLESS gRPC REALITY,VLESS TCP REALITY`
- a JSON mapping, for example `{"vless":["VLESS TCP REALITY"]}`

VPN users are created with:

- no expiry: `expire=None`
- traffic-only limit
- reset strategy: `no_reset`
- inbound/profile/group value from `MARZBAN_INBOUND_ID_OR_PROFILE`, default `3`

If your Marzban deployment expects a different inbound payload shape, adjust `_user_payload()` in `app/marzban/client.py`.

## Renewal / Add Traffic

Each purchase creates a separate `Order`.

For an existing active service:

- the bot fetches the current Marzban user
- adds the purchased GB to the current data limit
- updates the same Marzban user
- keeps the stored subscription URL

A new Marzban user is created only if the user has no active service or the old Marzban user no longer exists.

## Example User Flow

Persian:

1. `/start`
2. انتخاب `فارسی`
3. `خرید نامحدود` یا `خرید حجمی`
4. انتخاب `20GB`
5. انتخاب `برای خودم` یا `برای شخص دیگر`
6. پرداخت از کیف پول
7. برای خرید خودتان: دریافت لینک اشتراک و کانفیگ‌ها
8. برای شخص دیگر: دریافت کد فعال‌سازی یا دریافت کانفیگ آماده و ارسال آن به مشتری

English:

1. `/start`
2. Choose `English`
3. `Monthly Unlimited` or `Buy by Traffic`
4. Choose `20GB`
5. Choose `For me` or `For someone else`
6. Pay from wallet
7. For your own purchase: receive subscription link and configs
8. For someone else: receive a redeem code, or receive ready configs and send them to the customer

## Admin Panel

Run:

```text
/admin
```

Available actions:

- Pending Orders
- Search User
- Order History
- Active Services
- Add Traffic Manually
- Disable User
- Enable User
- Delete VPN User
- Broadcast Message
- Bot Settings
- Stats

Every admin action is stored in `admin_action_logs`.

## Reseller Panel

Admins can add approved resellers from `/admin` -> `Manage Resellers`.
Send the reseller Telegram ID and optional name:

```text
123456789 Reza Shop
```

Set the reseller price from `/admin` -> `Bot Settings` -> `Reseller Price`.
Reseller bulk orders must be at least 50GB total by default. Admins can change this from
`/admin` -> `Bot Settings` -> `Reseller Min GB`.

Approved resellers use `Reseller Panel` from the main menu. Bulk order input:

```text
10x3
3 x 5
```

This means 10 accounts with 3GB and 3 accounts with 5GB. The bot shows a summary,
calculates `total_gb * price_per_gb_reseller`, asks for payment proof, then sends
the order to admins. Admins approve from `/admin` -> `Bulk Orders`.

Generated TXT example:

```text
Order ID: BULK-000123
Reseller Telegram ID: 123456789
Total Accounts: 13
Total Traffic: 45GB

--------------------------------
Username: reseller123456789-3gb-001
Quota: 3GB
Config: vless://...
Subscription: https://...
--------------------------------
```

## Web Admin Panel

The project includes an optional browser admin panel beside the Telegram admin panel.
It uses the same PostgreSQL database, service layer, Marzban API client, and
`admin_action_logs`.

Configure these values in `.env`:

```env
WEB_ADMIN_ENABLED=true
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD=change-this-strong-password
WEB_ADMIN_SECRET_KEY=change-this-long-random-secret
WEB_ADMIN_HOST=0.0.0.0
WEB_ADMIN_PORT=8080
WEB_ADMIN_BIND_ADDRESS=0.0.0.0
WEB_ADMIN_PUBLIC_PORT=8080
WEB_ADMIN_ACTION_TELEGRAM_ID=
WEB_ADMIN_ALLOWED_IPS=
```

`WEB_ADMIN_ACTION_TELEGRAM_ID` is used in logs for web actions. If empty, the first
ID in `ADMIN_TELEGRAM_IDS` is used.

`WEB_ADMIN_ALLOWED_IPS` is optional. When set, only these comma-separated source IPs
can access the web admin panel, for example `WEB_ADMIN_ALLOWED_IPS=81.91.146.90`.
The Dockerized Nginx proxy also uses this value and publishes the panel on
`WEB_ADMIN_PUBLIC_PORT`.

Run it with Docker Compose:

```bash
docker compose up -d --build web
```

Compose publishes the panel through the `web-admin-nginx` service. If you keep
`WEB_ADMIN_BIND_ADDRESS=127.0.0.1`, the safest access method is an SSH tunnel:

```bash
ssh -L 8080:127.0.0.1:8080 user@your-server
```

Then open `http://127.0.0.1:8080`. If you set `WEB_ADMIN_BIND_ADDRESS=0.0.0.0`,
open `http://SERVER_IP:WEB_ADMIN_PUBLIC_PORT`; Nginx and the app will both enforce
`WEB_ADMIN_ALLOWED_IPS`.

The web panel supports dashboard stats, pending order approval/rejection, wallet top-up
approval/rejection and correction, user search/details, wallet ledger, order history,
referral overview, manual wallet adjustment, VPN service actions, bot settings,
reseller management, reseller bulk order approval/resend, support replies, and
broadcasts by segment.

Keep the panel behind SSH tunnel, VPN, or a trusted HTTPS reverse proxy. Do not expose
it directly to the public internet with a weak password.

## Recommended Client Apps

The bot sends these after successful activation:

- Android: v2rayNG
- iOS: Streisand / FoXray / V2Box
- Windows: v2rayN
- macOS: V2Box / Clash Verge

## Troubleshooting

## Daily Telegram Database Backup

Docker Compose includes a `db-backup` service. It runs `pg_dump`, compresses the SQL
backup, and sends it to every Telegram ID in `ADMIN_TELEGRAM_IDS`.

Configure in `.env`:

```env
BACKUP_TIME=03:30
BACKUP_TIMEZONE=Asia/Tehran
BACKUP_RETENTION_DAYS=7
```

Start or update it with:

```bash
docker compose up -d db-backup
```

Test one backup manually:

```bash
docker compose run --rm -e BACKUP_RUN_ONCE=true db-backup
```

Backups are also kept in the Docker volume `db_backups` for the configured retention period.

`bot exits immediately`

- Check `BOT_TOKEN`.
- Run `docker compose logs -f bot`.

`database connection failed`

- Make sure `DATABASE_URL` points to `postgres` when running in Docker.
- Check PostgreSQL health: `docker compose ps`.

`Redis connection failed`

- Make sure `REDIS_URL=redis://redis:6379/0`.

`Marzban approval fails`

- Check `MARZBAN_BASE_URL`, admin username/password, and API availability.
- Review the failed order `admin_note` in PostgreSQL.
- Confirm your Marzban API accepts the inbound/profile payload used by `_user_payload()`.

`Admins do not receive orders`

- Ensure `ADMIN_TELEGRAM_IDS` contains numeric Telegram IDs, not usernames.
- The admin must have started the bot at least once.

`Duplicate approval`

- The approval flow checks the order status under a database lock. If an order is already processed, the second approval is rejected.
