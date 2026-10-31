# =============================================================================
# === backend/apps/attendance/dashboard.py ===
# =============================================================================
"""
GET /api/hr/summary/ — everything the Ringkasan dashboard shows in one call (G6, 28 Oct 2026):
today's counters, who needs attention, today's list (problems first), and this
month's approved overtime per site. Built from the same functions as the
Absensi, Perlu Tinjau and Lembur pages, so the numbers always agree.
"""
from decimal import Decimal

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR
from apps.payroll.views import overtime_month
from apps.sites.models import Site
from apps.leave.models import LeaveRequest

from .hr_views import daily_counters, daily_rows, review_rows, review_summary

TODAY_LIMIT = 8
# Problems first, then people still expected, then the fine ones.
_ORDER = {"no_clock_out": 0, "absent": 1, "late": 2, "early_out": 3, "rejected": 4, "day_off_work": 5,
          "not_yet": 6, "working": 7, "on_time": 8, "present": 8, "leave": 9, "day_off": 9}


class SummaryView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        org = request.hr_org
        now = timezone.now()
        today = timezone.localtime(now).date()

        rows = daily_rows(org, today, now)
        counts = {c["key"]: c["count"] for c in daily_counters(rows)}
        present = sum(1 for r in rows if r["first_in"])
        queue = review_rows(org, 7, now)
        rows.sort(key=lambda r: (not r["needs_review"], _ORDER.get(r["status"], 10), r["employee"]["full_name"]))

        ot = overtime_month(org, today.replace(day=1))
        top = sorted(ot["sites"], key=lambda s: Decimal(s["amount"]), reverse=True)[:4]
        biggest = Decimal(top[0]["amount"]) if top else Decimal("0")
        for s in top:
            s["share"] = int(Decimal(s["amount"]) * 100 / biggest) if biggest else 0

        return Response({
            "success": True,
            "user_name": request.user.full_name,
            "date": today.isoformat(),
            "employees_active": Employee.objects.filter(organization=org, status=Employee.Status.ACTIVE).count(),
            "sites_active": Site.objects.filter(organization=org, is_active=True).count(),
            "present": present,
            "counters": counts,
            "review": {"count": len(queue), "summary": review_summary(queue)},
            "today": rows[:TODAY_LIMIT],
            "today_total": len(rows),
            "overtime": {"month": ot["month"], **ot["totals"], "sites": top},
            "leave": {"pending": LeaveRequest.objects.filter(organization=org, status=LeaveRequest.Status.PENDING).count(),
                      "today": counts.get("leave", 0)},
        })
