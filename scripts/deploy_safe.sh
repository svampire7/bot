#!/usr/bin/env sh
set -eu

echo "Creating pre-deploy database backup..."
docker compose -p "${COMPOSE_PROJECT_NAME:-vpnbot}" run --rm \
  -e BACKUP_RUN_ONCE=true \
  db-backup

echo "Updating bot and web containers..."
git pull --ff-only
docker compose -p "${COMPOSE_PROJECT_NAME:-vpnbot}" up --build -d bot web web-admin-nginx db-backup
docker compose -p "${COMPOSE_PROJECT_NAME:-vpnbot}" ps
docker compose -p "${COMPOSE_PROJECT_NAME:-vpnbot}" logs --tail=80 bot
docker compose -p "${COMPOSE_PROJECT_NAME:-vpnbot}" logs --tail=40 web
docker compose -p "${COMPOSE_PROJECT_NAME:-vpnbot}" logs --tail=40 web-admin-nginx
