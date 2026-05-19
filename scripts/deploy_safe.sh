#!/usr/bin/env sh
set -eu

echo "Creating pre-deploy database backup..."
docker compose -p "${COMPOSE_PROJECT_NAME:-vpnbot}" run --rm \
  -e BACKUP_RUN_ONCE=true \
  db-backup

echo "Updating bot container..."
git pull --ff-only
docker compose -p "${COMPOSE_PROJECT_NAME:-vpnbot}" up --build -d bot db-backup
docker compose -p "${COMPOSE_PROJECT_NAME:-vpnbot}" ps
docker compose -p "${COMPOSE_PROJECT_NAME:-vpnbot}" logs --tail=80 bot
