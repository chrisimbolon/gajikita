# =============================================================================
# === backend/Dockerfile ===  SeeGaji backend (Django + gunicorn)
# Same shape as Arthasee's. requirements copied and installed BEFORE the code,
# so a code-only change rebuilds in seconds (pip layer stays cached).
# libcairo2-dev + pkg-config: xhtml2pdf (slips) pulls in pycairo, which has no
# ready-made Linux wheel and must compile against cairo.
# =============================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jakarta

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev libcairo2-dev pkg-config curl tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/base.txt requirements/base.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements/base.txt

COPY . .

# Static files (admin CSS/JS) are baked into the image, so every container started from it
# has them. The values below exist only so the settings module can load during the build;
# collectstatic never touches the database and none of them end up in the running app.
RUN SECRET_KEY=build-only DB_NAME=build DB_USER=build DB_PASSWORD=build \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    python manage.py collectstatic --noinput

EXPOSE 8000

# 2 workers: the droplet has 1 vCPU / 2 GB shared with other apps; plenty for
# DKCB (~30 people). timeout 120: machine-file imports and payroll runs can take
# a while. max-requests recycles workers so memory can't creep up over weeks.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "2", "--timeout", "120", \
     "--max-requests", "1000", "--max-requests-jitter", "100", \
     "--access-logfile", "-"]
