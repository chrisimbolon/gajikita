"""
G10 (1 Nov 2026) — Rekap Absensi: everyone x every day of the pay period, its summary,
the Excel export, and agreement with payroll.
"""
import io
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.leave.models import LeaveRequest
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
URL = "/api/hr/attendance/rekap/"


def at(d, h, m):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class RekapTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        mk = lambda no, name: Employee.objects.create(organization=self.org, employee_no=no, full_name=name,
                                                      join_date=date(2025, 1, 6), default_shift=self.shift,
                                                      base_rate=Decimal("4000000"))
        self.andi, self.budi = mk("B-1", "Andi"), mk("B-2", "Budi")
        self.work(self.andi, date(2026, 9, 28), (7, 55), (17, 0))
        self.work(self.andi, date(2026, 9, 29), (8, 24), (17, 1))                       # late 24
        self.work(self.andi, date(2026, 9, 30), (7, 52), (20, 34))                      # overtime waiting (214)
        self.work(self.andi, date(2026, 10, 1), (7, 50), (20, 0), decision="approved", overtime_approved_minutes=180)
        LeaveRequest.objects.create(organization=self.org, employee=self.budi, kind="sick", start_date=date(2026, 9, 28),
                                    end_date=date(2026, 9, 29), days=2, status="approved")

    def work(self, emp, d, inn, out, **kw):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift, **kw)
        for kind, (h, m) in (("in", inn), ("out", out)):
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, occurred_at=at(d, h, m),
                                      received_at=at(d, h, m), source="fingerprint")

    def test_the_grid_and_its_summary(self):
        d = self.client.get(URL, {"month": "2026-10"}).data
        self.assertEqual((d["start"], d["end"], len(d["days"]), d["total"], d["prev"], d["next"]),
                         ("2026-09-26", "2026-10-25", 30, 2, "2026-09", "2026-11"))
        self.assertEqual((d["days"][1]["dow"], d["days"][1]["sunday"]), ("Min", True))
        rows = {r["employee"]["full_name"]: r for r in d["rows"]}
        andi = {c["d"]: c for c in rows["Andi"]["cells"]}
        self.assertEqual([andi[x]["c"] for x in ("2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29", "2026-10-02")],
                         ["A", "L", "H", "T", "A"])
        self.assertEqual((andi["2026-09-29"]["fi"], andi["2026-09-29"]["lo"], andi["2026-09-29"]["rv"]), ("08:24", "17:01", True))
        self.assertEqual((andi["2026-09-30"]["otp"], andi["2026-10-01"]["ot"]), (214, 180))
        s = rows["Andi"]["summary"]
        self.assertEqual((s["present"], s["late_times"], s["late_minutes"], s["overtime_minutes"],
                          s["overtime_pending_minutes"], s["problem"]), (4, 1, 24, 180, 214, True))
        budi = {c["d"]: c for c in rows["Budi"]["cells"]}
        self.assertEqual((budi["2026-09-28"]["c"], budi["2026-09-28"]["l"]), ("S", "Sakit"))
        self.assertEqual(rows["Budi"]["summary"]["leave"], {"Sakit": 2})

    def test_rekap_agrees_with_payroll(self):
        rekap = {r["employee"]["full_name"]: r["summary"] for r in self.client.get(URL, {"month": "2026-10"}).data["rows"]}
        run = self.client.post("/api/hr/payroll/runs/", {"month": "2026-10"}, format="json").data["run"]
        lines = {r["employee"]["full_name"]: r["id"] for r in self.client.get(f"/api/hr/payroll/runs/{run['id']}/").data["rows"]}
        for name in ("Andi", "Budi"):
            auto = self.client.get(f"/api/hr/payroll/runs/{run['id']}/lines/{lines[name]}/").data["line"]["auto"]
            self.assertEqual((auto["present_days"], auto["absent_days"], auto["meal_days"]),
                             (rekap[name]["present"], rekap[name]["absent"], rekap[name]["meal_days"]), name)

    def test_filters_and_default_period(self):
        self.assertEqual([r["employee"]["full_name"] for r in self.client.get(URL, {"month": "2026-10", "q": "bud"}).data["rows"]],
                         ["Budi"])
        d = self.client.get(URL).data                   # today is 26 Okt: the period 26 Okt - 25 Nov
        self.assertEqual((d["month"], d["start"]), ("2026-11", "2026-10-26"))

    def test_excel_export(self):
        from openpyxl import load_workbook
        resp = self.client.get(f"{URL}export/", {"month": "2026-10"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Rekap_Absensi_Oktober_2026.xlsx", resp["Content-Disposition"])
        wb = load_workbook(io.BytesIO(resp.content))
        self.assertEqual(wb.sheetnames, ["Rekap", "Jam", "Keterangan"])
        ws = wb["Rekap"]
        self.assertEqual((ws["A5"].value, ws["B5"].value, ws["G5"].value), ("B-1", "Andi", "T*"))   # G = 29 Sep
        self.assertEqual(wb["Jam"]["G5"].value, "08:24\n17:01")

    def test_workers_cannot_open_it(self):
        self.client.force_authenticate(CustomUser.objects.create_user(email="w@b.id", password="pass12345!",
                                                                      full_name="W", role="employee"))
        self.assertEqual(self.client.get(URL).status_code, 403)
