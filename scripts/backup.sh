#!/usr/bin/env bash
# Encrypted PostgreSQL + WhatsApp-session backup with offsite upload.
# Run via cron, e.g.:  0 * * * * /opt/waint/scripts/backup.sh >> /var/log/waint-backup.log 2>&1
set -euo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/waint}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
AGE_RECIPIENT="${AGE_RECIPIENT:?set AGE_RECIPIENT (age public key) for encryption}"
mkdir -p "$BACKUP_DIR"

echo "[$(date -u)] starting backup $STAMP"

# 1) Postgres logical dump (custom format), streamed straight into encryption
docker compose exec -T postgres pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | age -r "$AGE_RECIPIENT" -o "$BACKUP_DIR/pg-$STAMP.dump.age"

# 2) WhatsApp session volume (so re-pairing isn't always needed)
docker run --rm -v waint_wadata:/data -v "$BACKUP_DIR":/out alpine \
  tar czf "/out/wa-session-$STAMP.tgz" -C /data .

# 3) offsite (S3-compatible / rsync). Pick one:
if [ -n "${S3_BUCKET:-}" ]; then
  aws s3 cp "$BACKUP_DIR/pg-$STAMP.dump.age"      "s3://$S3_BUCKET/pg/"
  aws s3 cp "$BACKUP_DIR/wa-session-$STAMP.tgz"   "s3://$S3_BUCKET/wa/"
fi

# 4) prune local
find "$BACKUP_DIR" -type f -mtime +"$RETENTION_DAYS" -delete

echo "[$(date -u)] backup complete $STAMP"
