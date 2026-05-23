#!/usr/bin/env sh
set -e

alembic upgrade head

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

exec python -m app.main
