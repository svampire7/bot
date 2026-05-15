# Marzban Telegram VPN Bot

A Dockerized bilingual Persian/English Telegram bot for selling V2Ray VPN traffic packages through Marzban. Users pay manually by card-to-card transfer, upload a receipt, and an admin approves the order inside Telegram. On approval, the bot creates or renews the Marzban user without expiry and sends the subscription link.

## Features

- Python 3.11, aiogram 3, PostgreSQL, Redis, SQLAlchemy 2, Alembic
- Persian default, English optional, all user-facing text in `app/bot/i18n/fa.json` and `app/bot/i18n/en.json`
- Manual card-to-card payment workflow with receipt upload
- Admin Telegram panel with pending orders, approvals, rejection, search, stats, broadcast, service actions
- Marzban API client with login, token refresh, retry, create/update/delete/disable, usage, subscription URL
- One active VPN service per Telegram user by default
- Renewal adds traffic to the same Marzban user and keeps the same subscription link
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

MARZBAN_BASE_URL=https://your-marzban.example.com
MARZBAN_USERNAME=admin
MARZBAN_PASSWORD=secret
MARZBAN_INBOUND_ID_OR_PROFILE=3

CARD_NUMBER=6037...
CARD_HOLDER_NAME=Your Name
BANK_NAME=Your Bank
SUPPORT_USERNAME=@support
```

The default price is `220000` Toman per GB. Custom package limits are controlled by `MIN_CUSTOM_GB` and `MAX_CUSTOM_GB`.

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

1. User selects a package and uploads a receipt image.
2. The bot stores only Telegram `file_id`, not the actual receipt file.
3. Order status becomes `pending_admin`.
4. Admins from `ADMIN_TELEGRAM_IDS` receive the order and receipt.
5. Admin can approve, reject, ask for a new receipt, or view the user.
6. Approval locks/checks order status first. If it is not `pending_admin`, duplicate approval is rejected.
7. If Marzban succeeds, order becomes `completed` and the user receives service data.
8. If Marzban fails, order becomes `failed`, the error is saved in `admin_note`, and admin is notified.

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
3. `خرید VPN`
4. انتخاب `20GB`
5. کارت به کارت مبلغ
6. ارسال تصویر رسید
7. دریافت لینک اشتراک پس از تایید ادمین

English:

1. `/start`
2. Choose `English`
3. `Buy VPN`
4. Choose `20GB`
5. Transfer the amount manually
6. Upload receipt image
7. Receive subscription link after admin approval

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

## Recommended Client Apps

The bot sends these after successful activation:

- Android: v2rayNG
- iOS: Streisand / FoXray / V2Box
- Windows: v2rayN
- macOS: V2Box / Clash Verge

## Troubleshooting

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
