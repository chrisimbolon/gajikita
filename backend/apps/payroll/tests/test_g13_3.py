"""
G13-3 (17 Nov 2026) — what the company pays for a person, and the tunjangan kehadiran.
  JHT 2% ditanggung perusahaan: Anthony's 2% is not taken from his pay; the company pays it (R1: -200.000 -> 0).
  Tunjangan kehadiran (DKCB Note sheet: "no late, no MC, no UL"): paid only for a perfect period, otherwise
  "hangus" with the reason on the slip. Made-up people.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.leave.models import LeaveRequest
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll import engine
from apps.payroll.models import PayrollSettings
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
RUNS = "/api/hr/payroll/runs/"
D = Decimal


class EngineTests(SimpleTestCase):
    def slip(self, terms=None, **period):
        return engine.calculate(terms or engine.EmployeeTerms(base_salary=D("10000000")),
                                engine.PeriodInput(**period), engine.PayrollRules(late_fine_per_minute=D("500")))

    def test_jht_by_company(self):
        own = self.slip()
        self.assertEqual(own.amount("jht_employee"), D("200000"))
        paid = self.slip(engine.EmployeeTerms(base_salary=D("10000000"), jht_by_company=True))
        self.assertEqual((paid.amount("jht_employee"), paid.net), (D("0"), D("10000000")))
        line = next(l for l in paid.employer if l.code == "jht_employee_company")
        self.assertEqual((line.amount, line.label), (D("200000"), "JHT 2% karyawan (ditanggung perusahaan)"))

    def test_attendance_bonus(self):
        terms = engine.EmployeeTerms(base_salary=D("3500000"), attendance_bonus=D("150000"))
        self.assertEqual(self.slip(terms).amount("attendance_bonus"), D("150000"))
        lost = self.slip(terms, late_minutes=D("6"), sick_days=D("1"), unpaid_days=D("0.5"))
        self.assertEqual(lost.amount("attendance_bonus"), D("0"))
        self.assertIn("Tunjangan kehadiran Rp 150.000 hangus: terlambat / pulang cepat 6 menit, sakit 1 hari, "
                      "tidak masuk tanpa upah ½ hari.", lost.warnings)
        self.assertEqual(engine.attendance_lost(0, 0, 0), [])
        self.assertEqual(engine.attendance_lost(0, 0, D("1.5")), ["tidak masuk tanpa upah 1½ hari"])


class PayRunTests(APITestCase):
    def setUp(self):
        p = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        p.start()
        self.addCleanup(p.stop)
        self.org = Organization.objects.create(name="PT Contoh Hadir")
        hr = CustomUser.objects.create_user(email="hr@hadir.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Kantor", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        PayrollSettings.objects.create(organization=self.org, late_fine_per_minute=D("500"), late_tolerance_minutes=5)
        mk = lambda no, name, **kw: Employee.objects.create(organization=self.org, employee_no=no, full_name=name,
                                                            join_date=date(2025, 1, 6), default_shift=self.shift,
                                                            **{"base_rate": D("3500000"), **kw})
        self.dila = mk("H-1", "Dila Contoh", attendance_bonus=D("150000"))
        self.tari = mk("H-2", "Tari Contoh", attendance_bonus=D("150000"))
        self.ani = mk("H-3", "Ani Contoh", attendance_bonus=D("150000"))
        self.boss = mk("H-4", "Bos Contoh", base_rate=D("10000000"), jht_by_company=True, pph21_by_company=True)
        start = date(2026, 9, 26)
        for k in range(30):
            d = start + timedelta(days=k)
            if d.isoweekday() == 7:
                continue
            for emp in (self.dila, self.tari, self.ani, self.boss):
                if emp is self.tari and d == date(2026, 10, 7):
                    continue                                              # sick, with a letter
                self.work(emp, d, (8, 20) if (emp is self.ani and d == date(2026, 10, 8)) else (7, 55))
        LeaveRequest.objects.create(organization=self.org, employee=self.tari, kind="sick", start_date=date(2026, 10, 7),
                                    end_date=date(2026, 10, 7), days=1, status="approved")

    def work(self, emp, d, inn):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift)
        for kind, (h, m) in (("in", inn), ("out", (17, 0))):
            t = datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                      occurred_at=t, received_at=t)

    def lines(self):
        run = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]
        rows = self.client.get(f"{RUNS}{run['id']}/").data["rows"]
        return {r["employee"]["full_name"]: self.client.get(f"{RUNS}{run['id']}/lines/{r['id']}/").data["line"]
                for r in rows}

    def test_bonus_and_company_jht_in_the_run(self):
        lines = self.lines()
        earned = lambda l, code: next((x["amount"] for x in l["result"]["earnings"] if x["code"] == code), None)
        self.assertEqual(earned(lines["Dila Contoh"], "attendance_bonus"), "150000")
        self.assertIsNone(earned(lines["Tari Contoh"], "attendance_bonus"))
        self.assertIn("Tunjangan kehadiran Rp 150.000 hangus: sakit 1 hari.", lines["Tari Contoh"]["result"]["warnings"])
        self.assertEqual(lines["Tari Contoh"]["auto"]["sick_days"], 1)
        self.assertIsNone(earned(lines["Ani Contoh"], "attendance_bonus"))
        self.assertIn("Tunjangan kehadiran Rp 150.000 hangus: terlambat / pulang cepat 15 menit.",
                      lines["Ani Contoh"]["result"]["warnings"])
        boss = lines["Bos Contoh"]
        self.assertEqual(boss["net"], "10000000.00")
        self.assertIn("jht_employee_company", [x["code"] for x in boss["result"]["employer"]])

    def test_employee_api_keeps_the_fields(self):
        r = self.client.patch(f"/api/hr/employees/{self.ani.pk}/", {"attendance_bonus": "-1"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f"/api/hr/employees/{self.ani.pk}/", {"attendance_bonus": "200000", "jht_by_company": True,
                                                                   "pph21_by_company": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.ani.refresh_from_db()
        self.assertEqual((self.ani.attendance_bonus, self.ani.jht_by_company, self.ani.pph21_by_company),
                         (D("200000"), True, True))
