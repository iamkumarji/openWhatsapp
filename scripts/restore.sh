#!/usr/bin/env bash
# Restore PostgreSQL from an age-encrypted pg_dump.  Usage: restore.sh <pg-dump.age>
set -euo pipefail
DUMP="${1:?usage: restore.sh <pg-dump.age>}"
AGE_KEY="${AGE_KEY:?set AGE_KEY (path to age identity file)}"

echo "WARNING: this overwrites database '$POSTGRES_DB'. Ctrl-C to abort."; sleep 5

age -d -i "$AGE_KEY" "$DUMP" \
  | docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists

echo "restore complete. Run migrations if schema is newer: docker compose run --rm backend alembic upgrade head"
