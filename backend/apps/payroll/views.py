# =============================================================================
# === backend/apps/payroll/views.py ===
# =============================================================================
"""
GET /api/hr/overtime/?month=YYYY-MM  (G4a, 28 Oct 2026)

Approved overtime for the month in rupiah: per employee (with every day's
working), per site, and the totals, plus PP 35 warnings (over 4 hours a day,
over 18 hours a week). Only HR-approved minutes count; proposed-but-not-yet-
approved overtime waits in the Perlu Tinjau queue.

overtime_month() is shared with the dashboard (G6).
"""
from calendar import monthrange
from datetime import date as Date
from decimal import Decimal

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attendance.models import AttendanceDay
from apps.organizations.permissions import IsCompanyHR

from .overtime import overtime_pay, week_warnings
from .services import NOT_PAID_REASONS, is_rest_day, pay_payload, shift_of, wage_basis


def _month(value):
    try:
        y, m = (int(x) for x in (value or "").split("-"))
        return Date(y, m, 1)
    except (ValueError, TypeError):
        today = timezone.localdate()
        return today.replace(day=1)


def overtime_month(org, first):
    last = first.replace(day=monthrange(first.year, first.month)[1])
    days = (AttendanceDay.objects
            .filter(organization=org, date__gte=first, date__lte=last,
                    decision="approved", overtime_approved_minutes__gt=0)
            .select_related("employee", "employee__default_shift", "shift")
            .prefetch_related("events__site").order_by("employee__full_name", "date"))

    people, sites = {}, {}
    for day in days:
        emp = day.employee
        p = people.setdefault(emp.id, {
            "employee": {"id": str(emp.id), "employee_no": emp.employee_no, "full_name": emp.full_name},
            "days": [], "minutes": 0, "amount": Decimal("0"), "warnings": [], "_entries": [], "not_paid": None,
        })
        minutes = day.overtime_approved_minutes
        rest = is_rest_day(day)
        p["_entries"].append((day.date, minutes, rest))
        p["minutes"] += minutes
        last_site = next((e.site.name for e in reversed(list(day.events.all())) if e.site), "Tanpa lokasi")
        basis, hourly, pattern, reason = wage_basis(emp, shift_of(day))
        entry = {"date": day.date.isoformat(), "day_id": str(day.id), "site": last_site, "minutes": minutes,
                 "rest_day": rest}
        if reason:
            p["not_paid"] = NOT_PAID_REASONS[reason]
            entry.update({"amount": "0", "lines": [], "warnings": []})
        else:
            pay = overtime_pay(minutes, rest, pattern, hourly)
            entry.update(pay_payload(pay))
            p["amount"] += pay.amount
            p["hourly_rate"] = entry["hourly_rate"]
            p["warnings"].extend(f"{day.date:%d/%m}: {w}" for w in pay.warnings)
            s = sites.setdefault(last_site, {"site": last_site, "minutes": 0, "amount": Decimal("0")})
            s["minutes"] += minutes
            s["amount"] += pay.amount
        p["days"].append(entry)

    rows = []
    for p in people.values():
        p["warnings"].extend(week_warnings(p.pop("_entries")))
        p["amount"] = str(p["amount"])
        rows.append(p)
    site_rows = sorted(({**s, "amount": str(s["amount"])} for s in sites.values()), key=lambda s: s["site"])
    total = sum((Decimal(r["amount"]) for r in rows), Decimal("0"))
    return {
        "month": first.strftime("%Y-%m"),
        "totals": {"people": len(rows), "minutes": sum(r["minutes"] for r in rows), "amount": str(total)},
        "employees": rows, "sites": site_rows,
    }


class OvertimeMonthView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        first = _month(request.query_params.get("month"))
        return Response({"success": True, **overtime_month(request.hr_org, first)})
