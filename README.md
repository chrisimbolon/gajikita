# GajiKita

SaaS HR & Payroll for Indonesian companies: attendance, leave, salary, BPJS, PPh 21.
Chris & Pak Holan (co-founders). Built on Arthasee's core (event bus, tenant
scoping, auth), licensed from Langit. Domain logic is ported from the earlier
FastAPI prototype (hr-app) after review and fixes.

## Run locally

Ports are chosen so it runs next to Arthasee (8000/3000) and TourTravel (8001/3001):
backend **8002**, frontend **3002**.

    # backend
    cd backend
    source .venv/bin/activate
    python manage.py runserver 8002

    # frontend (second terminal)
    cd frontend
    npm run dev          # http://localhost:3002

    # tests
    cd backend && python manage.py test

## What's here (v0 scaffold)

- `apps/core` — TenantScopedModel, TenantScopedAPIView, Outbox + event bus (from Arthasee)
- `apps/authentication` — CustomUser (owner / super_admin), JWT login (from Arthasee)
- `apps/organizations` — Organization = one company (slimmed)
- `/api/health/` — health check

Not yet: employees, attendance, leave, payroll, payslips, and the accounting engine.
