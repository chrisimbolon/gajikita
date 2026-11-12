#!/bin/bash
# =============================================================================
# deploy/remote-health.sh — runs ON the droplet, last step of every deploy.
#   bash /home/apps/seegaji/deploy/remote-health.sh <git sha>
# Fails the run (exit 1) unless the backend answers 200 on /api/health/ AND the
# static site is in place. Every failure path ends in an explicit exit 1, so
# a missing container can never end green (first deploy, 12 Nov 2026).
# =============================================================================
set -uo pipefail
SHA="${1:-unknown}"
APP_DIR=/home/apps/seegaji

fail() {
  echo "❌ $1"
  docker ps -a --filter name=seegaji --format 'table {{.Names}}\t{{.Status}}' || true
  docker logs seegaji_backend --tail 60 2>&1 || true
  exit 1
}

[ -f "$APP_DIR/frontend/out/index.html" ] || fail "static site missing: $APP_DIR/frontend/out/index.html"
echo "✅ static site in place ($(find "$APP_DIR/frontend/out" -name '*.html' | wc -l) pages)"

docker ps --format '{{.Names}}' | grep -q '^seegaji_backend$' || fail "seegaji_backend is not running"

OK=no
for i in $(seq 1 30); do
  CODE=$(docker exec seegaji_backend curl -s -o /dev/null -w "%{http_code}" \
    -H "X-Forwarded-Proto: https" -H "Host: seegaji.com" \
    http://localhost:8000/api/health/ </dev/null 2>/dev/null || echo 000)
  echo "Backend /api/health/: $CODE ($i/30)"
  if [ "$CODE" = "200" ]; then OK=yes; break; fi
  sleep 3
done
[ "$OK" = "yes" ] || fail "backend not healthy after 90 s"
echo "✅ Backend healthy"

CADDY=$(docker ps -qf "name=caddy-container")
if [ -n "$CADDY" ] && docker exec "$CADDY" caddy reload --config /etc/caddy/Caddyfile </dev/null >/dev/null 2>&1; then
  echo "✅ Caddy reloaded"
else
  echo "⚠️  Caddy reload skipped"
fi

echo "$(date -u '+%F %T') UTC | ${SHA:0:7} | OK" >> "$APP_DIR/deploy.log"
docker ps --filter name=seegaji --format 'table {{.Names}}\t{{.Status}}'
free -h
