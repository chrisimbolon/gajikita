#!/bin/sh
# =============================================================================
# deploy/backup.sh — SeeGaji database + uploads backup (runs ON the droplet)
#   nightly by /etc/cron.d/seegaji-backup, and before every migrating deploy.
# Keeps 14 days of nightly copies and the last 10 pre-deploy copies.
# Restore (database):  docker exec -i seegaji_db pg_restore -U seegaji -d seegaji --clean --if-exists < FILE.dump
# =============================================================================
set -eu
LABEL="${1:-nightly}"
DIR=/home/apps/seegaji-backups
STAMP=$(date -u +%Y-%m-%d_%H%M)
mkdir -p "$DIR"
chmod 700 "$DIR"

DB_FILE="$DIR/db_${LABEL}_${STAMP}.dump"
docker exec seegaji_db pg_dump -U seegaji -d seegaji -Fc > "$DB_FILE"
# a real dump is never this small; fail loudly rather than keep an empty file
[ "$(wc -c < "$DB_FILE")" -gt 2048 ] || { echo "$(date -u) ❌ dump too small: $DB_FILE"; rm -f "$DB_FILE"; exit 1; }

MEDIA=/var/lib/docker/volumes/seegaji_media/_data
if [ -d "$MEDIA" ]; then
  tar czf "$DIR/media_${LABEL}_${STAMP}.tar.gz" -C "$MEDIA" .
fi
chmod 600 "$DIR"/*_"${LABEL}"_"${STAMP}"* 2>/dev/null || true

# retention
find "$DIR" -name 'db_nightly_*'      -mtime +14 -delete
find "$DIR" -name 'media_nightly_*'   -mtime +14 -delete
ls -1t "$DIR"/db_pre-deploy_*    2>/dev/null | tail -n +11 | xargs -r rm -f
ls -1t "$DIR"/media_pre-deploy_* 2>/dev/null | tail -n +11 | xargs -r rm -f

echo "$(date -u '+%F %T') UTC ✅ $LABEL backup: $(du -h "$DB_FILE" | cut -f1) db"
