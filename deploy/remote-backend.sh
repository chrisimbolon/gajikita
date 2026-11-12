#!/bin/bash
# =============================================================================
# deploy/remote-backend.sh — runs ON the droplet, called by .github/workflows/deploy.yml
#   bash /home/apps/seegaji/deploy/remote-backend.sh <backend_changed: true|false>
# A real file, not a heredoc piped over ssh: piped scripts get eaten by any command
# that reads stdin (first deploy, 12 Nov 2026: `docker compose run` swallowed every
# line after the migrations, so the container was never created and the job still
# went green). Every docker call below also gets -T / </dev/null for the same reason.
# =============================================================================
set -euo pipefail
BACKEND_CHANGED="${1:-true}"
APP_DIR=/home/apps/seegaji
cd "$APP_DIR"
COMPOSE="docker compose -p seegaji -f docker-compose.yml -f docker-compose.prod.yml"

if [ "$BACKEND_CHANGED" != "true" ] && docker ps --format '{{.Names}}' | grep -q '^seegaji_backend$'; then
  echo "⏭️  Backend unchanged and running — skipping rebuild"
  exit 0
fi

echo "=== Building backend image (pip layer cached unless requirements change) ==="
$COMPOSE build --pull seegaji_backend </dev/null

echo "=== Starting DB ==="
$COMPOSE up -d seegaji_db </dev/null
for i in $(seq 1 30); do
  STATUS=$(docker inspect seegaji_db --format='{{.State.Health.Status}}' 2>/dev/null || echo starting)
  echo "DB: $STATUS ($i/30)"
  [ "$STATUS" = "healthy" ] && break
  if [ "$i" -eq 30 ]; then echo "❌ DB timeout"; exit 1; fi
  sleep 3
done

echo "=== Backup before migrating (skipped while the database is still empty) ==="
if docker exec seegaji_db psql -U seegaji -d seegaji -tAc "select 1 from django_migrations limit 1" </dev/null 2>/dev/null | grep -q 1; then
  sh deploy/backup.sh pre-deploy </dev/null
else
  echo "Fresh database — nothing to back up yet"
fi

echo "=== Migrations ==="
$COMPOSE run --rm -T seegaji_backend python manage.py migrate --noinput </dev/null
PENDING=$($COMPOSE run --rm -T seegaji_backend python manage.py showmigrations --plan </dev/null | grep -c "\[ \]" || true)
if [ "$PENDING" != "0" ]; then echo "❌ $PENDING migration(s) still unapplied"; exit 1; fi
echo "✅ All migrations applied"
# collectstatic happens inside the image build (backend/Dockerfile).

echo "=== Force-recreating backend ==="
$COMPOSE up -d --no-deps --force-recreate seegaji_backend </dev/null
sleep 3

if ! docker ps -a --format '{{.Names}}' | grep -q '^seegaji_backend$'; then
  echo "❌ seegaji_backend does not exist after 'up -d'"; exit 1
fi
CREATED=$(docker inspect seegaji_backend --format '{{.Created}}')
AGE=$(( $(date -u +%s) - $(date -u -d "$CREATED" +%s) ))
if [ "$AGE" -gt 120 ]; then echo "❌ container is ${AGE}s old — stale, not recreated"; exit 1; fi
echo "✅ recreated ${AGE}s ago"
if ! docker inspect seegaji_backend --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' | grep -q caddy-net; then
  echo "❌ not on caddy-net — Caddy cannot reach it"; exit 1
fi
echo "✅ on caddy-net"

docker image prune -f >/dev/null
echo "=== Backend deployed ==="
