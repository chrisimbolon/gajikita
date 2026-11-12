# SeeGaji — deploying to production (seegaji.com)

Everything goes through git: you commit and push, GitHub Actions tests and deploys.
The droplet is never edited by hand, except for the one-time steps marked **(once)**.

## How it fits on chris-apps-server

| Piece | Where | Notes |
|---|---|---|
| `seegaji_backend` | Docker, networks `seegaji-internal` + `caddy-net` | gunicorn, 2 workers, port 8000 (internal only) |
| `seegaji_db` | Docker, `seegaji-internal` only | Postgres 16, **no published port**, small memory settings |
| Static site | `/home/apps/seegaji/frontend/out` | built on GitHub, rsynced up, served by Caddy |
| Uploads | volume `seegaji_media` | selfies + surat dokter, served only through logged-in HR views |
| Backups | `/home/apps/seegaji-backups` | nightly 02:00 WIB (14 days) + before every migrating deploy (last 10) |
| Deploy log | `/home/apps/seegaji/deploy.log` | one line per successful deploy |

## Every deploy (normal life)

```bash
git push origin main
```
GitHub → Actions → "Deploy SeeGaji to Production":
1. **test**: makemigrations check + all backend tests (must be green, or nothing ships)
2. **deploy**: frontend build (if `frontend/` changed) → code + `.env` rsynced →
   backend rebuilt, backup, migrate, collectstatic, recreated (if `backend/` or compose changed) →
   backup schedule installed → `/api/health/` must answer 200 → Caddy reload

Emergency full redeploy: Actions → Deploy SeeGaji → **Run workflow**.

## First launch (once)

### 1. GitHub secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DB_PASSWORD` | `python3 -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `SSH_PRIVATE_KEY` | same value as Arthasee's secret |
| `SSH_HOST` | `104.248.251.227` |
| `SSH_USER` | same as Arthasee's (root) |

Keep `DB_PASSWORD` in your password manager too. Postgres stores it the first time the
database is created; changing the secret later does NOT change the database password.

### 2. Try the image on your Mac first (optional, recommended)
```bash
cp .env.example .env            # then put any long random SECRET_KEY / DB_PASSWORD in it
docker compose up -d --build
docker exec seegaji_backend python manage.py migrate --noinput
docker exec seegaji_backend curl -s -H "X-Forwarded-Proto: https" -H "Host: seegaji.com" localhost:8000/api/health/
#   → {"status":"ok"}
docker compose down             # add -v to also drop the local test database
```

### 3. Push
```bash
git push origin main
```
Watch the run in GitHub → Actions. The first backend build takes a few minutes (1 vCPU).

### 4. Caddy (in the Caddy repo, ~/Projects/caddy)
- Apply the Caddy patch there: seegaji.com block + read-only mount of `/home/apps/seegaji/frontend/out`
  (KLA retired in the same patch).
- Push; the Caddy container must be **recreated** for a new mount (~5 s pause for all sites).

### 5. DNS
`seegaji.com` A → 104.248.251.227 (done). Add `www` → same IP (A record or CNAME to seegaji.com).
Caddy fetches both HTTPS certificates by itself on the first visit.

### 6. Smoke test
- https://seegaji.com → landing page; https://www.seegaji.com → redirects
- Masuk → log in; Ringkasan, Absensi, Rekap, Payroll open
- import one machine file, open Rekap, run a test payroll, print one slip
- `curl -sI https://seegaji.com/api/health/` → `200`

## Restoring a backup
```bash
ls -lt /home/apps/seegaji-backups | head
docker exec -i seegaji_db pg_restore -U seegaji -d seegaji --clean --if-exists < /home/apps/seegaji-backups/db_nightly_YYYY-MM-DD_HHMM.dump
```
Copy backups off the droplet now and then (they live on the same disk as the database):
```bash
scp 'root@104.248.251.227:/home/apps/seegaji-backups/db_nightly_*' ~/Backups/seegaji/
```

## Later (not needed for launch)
- Droplet to 4 GB RAM before a second customer.
- Off-site backups (DigitalOcean Spaces) instead of copying by hand.
- Selfies/attachments to a private Spaces bucket (settings change only).
