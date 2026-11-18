# =============================================================================
# === backend/apps/payroll/views.py ===
# =============================================================================
"""
GET /api/hr/overtime/?month=YYYY-MM&basis=period|calendar  (G4a, 28 Oct 2026; G17-10, 18 Nov 2026)

basis=period (the Lembur page and Ringkasan since G17-10): the pay period that ends in that month, the dates the
payroll pays (start day 26: "2026-10" = 26 Sep - 25 Okt); without month = the current pay period. The answer
also carries `payroll`: that month's pay run and the overtime its slips pay, so the page can say whether both agree.
basis missing or calendar: the calendar month, as before G17-10.

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

from .engine import period_for                                                        # G17-10
from .overtime import overtime_pay, week_warnings
from .models import PayrollSettings, PayRun
from .services import NOT_PAID_REASONS, is_rest_day, pay_payload, price_overtime, shift_of, wage_basis


PERIOD, CALENDAR = "period", "calendar"                                                # G17-10
OVERTIME_CODES = ("overtime", "overtime_rest_day")


def _month(value, default=None):
    try:
        y, m = (int(x) for x in (value or "").split("-"))
        return Date(y, m, 1)
    except (ValueError, TypeError):
        return default or timezone.localdate().replace(day=1)


def current_pay_month(today, start_day):
    """G17-10: the pay month whose period holds `today` (start day 26: 18 Nov -> November, 28 Okt -> November)."""
    if start_day and start_day > 1 and today.day >= start_day:
        return Date(today.year + 1, 1, 1) if today.month == 12 else Date(today.year, today.month + 1, 1)
    return today.replace(day=1)


def bounds(cfg, first, basis):
    """(start, end) of what the page counts."""
    if basis == PERIOD:
        return period_for(first.year, first.month, cfg.period_start_day)
    return first, first.replace(day=monthrange(first.year, first.month)[1])


def payroll_overtime(org, first):
    """G17-10: that month's pay run and the overtime its slips pay (as last calculated)."""
    run = PayRun.objects.filter(organization=org, period_end__year=first.year, period_end__month=first.month).first()
    if run is None:
        return None
    total = Decimal("0")
    for result in run.lines.values_list("result", flat=True):
        for e in (result or {}).get("earnings", []):
            if e.get("code") in OVERTIME_CODES:
                total += Decimal(str(e.get("amount") or 0))
    return {"run": str(run.id), "name": run.name, "locked": run.is_locked, "amount": str(total),
            "calculated_at": run.calculated_at.isoformat() if getattr(run, "calculated_at", None) else None}


def overtime_month(org, first, basis=CALENDAR):
    cfg = PayrollSettings.for_org(org)
    start, last = bounds(cfg, first, basis)
    days = (AttendanceDay.objects
            .filter(organization=org, date__gte=start, date__lte=last,
                    decision="approved", overtime_approved_minutes__gt=0)
            .select_related("employee", "employee__default_shift", "shift")
            .prefetch_related("events__site").order_by("employee__full_name", "date"))

    people, sites = {}, {}                      # G11c: priced the way payroll pays it (cfg above)
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
        entry = {"date": day.date.isoformat(), "day_id": str(day.id), "site": last_site, "minutes": minutes,
                 "rest_day": rest}
        price = price_overtime(emp, shift_of(day), minutes, rest, cfg)
        if "not_paid" in price:
            p["not_paid"] = price["not_paid"]
            entry.update({"amount": "0", "lines": [], "warnings": []})
        else:
            amount = Decimal(price["amount"])
            entry.update(price)
            p["amount"] += amount
            p["hourly_rate"] = entry.get("hourly_rate")
            p["warnings"].extend(f"{day.date:%d/%m}: {w}" for w in price["warnings"])
            s = sites.setdefault(last_site, {"site": last_site, "minutes": 0, "amount": Decimal("0")})
            s["minutes"] += minutes
            s["amount"] += amount
        p["days"].append(entry)

    rows = []
    for p in people.values():
        p["warnings"].extend(week_warnings(p.pop("_entries")))
        p["amount"] = str(p["amount"])
        rows.append(p)
    site_rows = sorted(({**s, "amount": str(s["amount"])} for s in sites.values()), key=lambda s: s["site"])
    total = sum((Decimal(r["amount"]) for r in rows), Decimal("0"))
    payroll = payroll_overtime(org, first) if basis == PERIOD else None              # G17-10
    if payroll is not None:
        diff = Decimal(payroll["amount"]) - total
        payroll.update({"same": diff == 0, "difference": str(diff)})
    return {
        "month": first.strftime("%Y-%m"),
        "basis": basis, "start": start.isoformat(), "end": last.isoformat(), "payroll": payroll,   # G17-10
        "totals": {"people": len(rows), "minutes": sum(r["minutes"] for r in rows), "amount": str(total)},
        "employees": rows, "sites": site_rows,
    }


class OvertimeMonthView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        basis = PERIOD if request.query_params.get("basis") == PERIOD else CALENDAR
        default = (current_pay_month(timezone.localdate(), PayrollSettings.for_org(request.hr_org).period_start_day)
                   if basis == PERIOD else None)
        first = _month(request.query_params.get("month"), default)
        return Response({"success": True, **overtime_month(request.hr_org, first, basis)})
