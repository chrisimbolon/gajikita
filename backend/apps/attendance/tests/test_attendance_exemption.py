"""
G12i (11 Nov 2026) — "Tidak wajib absen" through the API, the screens and payroll.

Marganda's October as in Anthony's book: no taps, every day "Kerja di Lobam", paid his full base with no meals,
overtime or UL; Kamarol (sales) the same. Without an exemption SeeGaji showed 25 x "Tidak hadir".
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceExemption
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.leave.models import LeaveRequest
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings, PayRun
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
RUNS = "/api/hr/payroll/runs/"


class ExemptionTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        self.hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=self.hr, role="hr")
        self.client.force_authenticate(self.hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        PayrollSettings.objects.create(organization=self.org, meal_rule="late_out", meal_allowance=Decimal("15000"),
                                       late_fine_per_minute=Decimal("500"))
        self.marganda = Employee.objects.create(
            organization=self.org, employee_no="DK17", full_name="Marganda Hutasoit", join_date=date(2024, 7, 26),
            default_shift=self.shift, base_rate=Decimal("4250000"), fingerprint_id="30", overtime_eligible=False)
        self.url = f"/api/hr/employees/{self.marganda.pk}/attendance-exemptions/"

    def exempt(self, **body):
        return self.client.post(self.url, {"start": "2026-09-01", "reason": "Kerja di Lobam", **body}, format="json")

    def test_create_list_and_the_employee_badge(self):
        resp = self.exempt()
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["current"]["reason"], "Kerja di Lobam")
        self.assertEqual(resp.data["exemptions"][0]["end"], None)
        emp = next(e for e in self.client.get("/api/hr/employees/").data["employees"] if e["id"] == str(self.marganda.pk))
        self.assertEqual(emp["attendance_exempt"]["start"], "2026-09-01")
        self.assertTrue(AuditEntry.objects.filter(action="attendance.exemption_create").exists())

    def test_bad_input_is_refused_plainly(self):
        self.exempt(end="2026-09-30")
        self.assertEqual(self.exempt(start="2026-09-15", end="2026-10-15").status_code, 400)       # overlaps
        self.assertIn("Bertabrakan", self.exempt(start="2026-09-15").data["message"])
        self.assertEqual(self.exempt(start="2026-10-10", end="2026-10-01").status_code, 400)       # end before start
        self.assertEqual(self.exempt(start="2026-10-01", reason="x").status_code, 400)             # no real reason
        self.assertEqual(self.exempt(start="2026-10-01").status_code, 201)                         # after it: fine

    def test_screens_show_DL_and_payroll_pays_like_anthony(self):
        self.exempt()
        LeaveRequest.objects.create(organization=self.org, employee=self.marganda, kind="annual",
                                    start_date=date(2026, 10, 5), end_date=date(2026, 10, 5), days=1, status="approved")
        daily = self.client.get("/api/hr/attendance/daily/", {"date": "2026-10-12"}).data
        row = next(r for r in daily["rows"] if r["employee"]["full_name"] == "Marganda Hutasoit")
        self.assertEqual((row["status"], row["needs_review"]), ("exempt", False))
        rekap = self.client.get("/api/hr/attendance/rekap/", {"month": "2026-10"}).data
        cells = {c["d"]: c["c"] for c in next(r for r in rekap["rows"] if r["employee"]["full_name"] == "Marganda Hutasoit")["cells"]}
        self.assertEqual((cells["2026-10-12"], cells["2026-10-11"], cells["2026-10-05"]), ("DL", "L", "C"))
        run = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]
        rows = self.client.get(f"{RUNS}{run['id']}/").data["rows"]
        m = next(r for r in rows if r["employee"]["full_name"] == "Marganda Hutasoit")
        self.assertEqual((m["present_days"], m["absent_days"], m["exempt_days"], m["exempt_reason"]),
                         (24, 0, 24, "Kerja di Lobam"))                       # 25 working days, 1 cuti
        line = PayRun.objects.get(pk=run["id"]).lines.get(employee=self.marganda)
        self.assertEqual((line.auto["unpaid_days"], line.auto["meal_days"], line.auto["late_minutes"]), (0, 0, 0))
        self.assertIn("Tidak wajib absen (Kerja di Lobam): 24 hari", line.result["warnings"][0])

    def test_without_the_period_he_is_absent(self):
        run = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]
        m = next(r for r in self.client.get(f"{RUNS}{run['id']}/").data["rows"]
                 if r["employee"]["full_name"] == "Marganda Hutasoit")
        self.assertEqual((m["absent_days"], m["exempt_days"]), (25, 0))

    def test_ending_the_period_only_changes_the_days_after(self):
        x = self.exempt().data["exemptions"][0]
        resp = self.client.patch(f"/api/hr/attendance-exemptions/{x['id']}/", {"end": "2026-10-10"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        rekap = self.client.get("/api/hr/attendance/rekap/", {"month": "2026-10"}).data
        cells = {c["d"]: c["c"] for c in next(r for r in rekap["rows"] if r["employee"]["full_name"] == "Marganda Hutasoit")["cells"]}
        self.assertEqual((cells["2026-10-10"], cells["2026-10-12"]), ("DL", "A"))
        self.assertTrue(AuditEntry.objects.filter(action="attendance.exemption_update").exists())

    def test_a_locked_payroll_cannot_be_rewritten(self):
        x = self.exempt().data["exemptions"][0]
        run = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]
        self.assertEqual(self.client.post(f"{RUNS}{run['id']}/lock/", {"action": "lock", "note": "Oktober final"}, format="json").status_code, 200)
        url = f"/api/hr/attendance-exemptions/{x['id']}/"
        refused = self.client.delete(url)
        self.assertEqual(refused.status_code, 400)
        self.assertIn("sudah dikunci", refused.data["message"])
        self.assertEqual(self.client.patch(url, {"end": "2026-10-10"}, format="json").status_code, 400)
        ok = self.client.patch(url, {"end": "2026-11-30"}, format="json")       # ending it after the locked month
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(AttendanceExemption.objects.get(pk=x["id"]).end, date(2026, 11, 30))
