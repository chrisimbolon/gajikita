"""
G13-4 (18 Nov 2026) — DKCB rules from Anthony's answers: late / early by more than 2 hours = ½ day instead of the
per-minute fine; breakfast only with an SPL (paid overtime that day). Made-up people.
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
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll import engine
from apps.payroll.models import PayrollSettings
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
RUNS, CHECK = "/api/hr/payroll/runs/", "/api/hr/attendance/checklist/"
D = Decimal


class RuleTests(SimpleTestCase):
    def test_long_late_split(self):
        f = engine.long_late_split
        self.assertEqual(f(150, 0, 120), (0, 0, 1))              # long late: ½ day, no minutes
        self.assertEqual(f(0, 150, 120), (0, 0, 1))              # long early leave
        self.assertEqual(f(135, 180, 120), (0, 0, 2))            # both: 1 day
        self.assertEqual(f(120, 30, 120), (120, 30, 0))          # exactly 2 h is not "more than"
        self.assertEqual(f(150, 0, None), (150, 0, 0))           # rule off
        self.assertEqual(f(150, 150, 120, room=1), (0, 150, 1))  # a ½ day already taken: never more than 1 day
        self.assertEqual(f(150, 0, 120, room=0), (150, 0, 0))
        self.assertEqual((engine.halves_text(1), engine.halves_text(2), engine.halves_text(3)), ("½", "1", "1½"))
        self.assertEqual((engine.minutes_text(120), engine.minutes_text(90)), ("2 jam", "90 menit"))


class PayrollTests(APITestCase):
    def setUp(self):
        p = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        p.start()
        self.addCleanup(p.stop)
        self.org = Organization.objects.create(name="PT Contoh Telat Lama")
        hr = CustomUser.objects.create_user(email="hr@telatlama.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        self.cfg = PayrollSettings.objects.create(organization=self.org, late_fine_per_minute=D("500"),
                                                  late_tolerance_minutes=5, meal_rule="late_out",
                                                  meal_allowance=D("15000"), breakfast_allowance=D("12000"))
        mk = lambda no, name: Employee.objects.create(organization=self.org, employee_no=no, full_name=name,
                                                      join_date=date(2025, 1, 6), default_shift=self.shift,
                                                      base_rate=D("3000000"), attendance_bonus=D("150000"))
        self.lama, self.pagi = mk("L-1", "Lama Contoh"), mk("L-2", "Pagi Contoh")
        special = {
            (self.lama, date(2026, 10, 1)): ((10, 30), (17, 0)),       # 150 min late -> ½ day
            (self.lama, date(2026, 10, 2)): ((8, 0), (14, 30)),        # 150 min early -> ½ day
            (self.lama, date(2026, 10, 3)): ((10, 15), (14, 0)),       # both long -> 1 day
            (self.lama, date(2026, 10, 5)): ((9, 0), (17, 0)),         # 60 min late -> fined 55 min
            (self.lama, date(2026, 10, 6)): ((11, 0), (17, 0)),        # long late, forgiven below
            (self.pagi, date(2026, 10, 7)): ((6, 40), (17, 0)),        # early, no overtime
            (self.pagi, date(2026, 10, 8)): ((6, 40), (17, 0)),        # early, overtime paid (SPL)
        }
        d = date(2026, 9, 26)
        while d <= date(2026, 10, 25):
            if d.isoweekday() != 7:
                for emp in (self.lama, self.pagi):
                    inn, out = special.get((emp, d), ((7, 55), (17, 0)))
                    day = self.work(emp, d, inn, out)
                    if (emp, d) == (self.lama, date(2026, 10, 6)):
                        day.waive_late, day.decision = True, "approved"
                        day.save(update_fields=["waive_late", "decision"])
                    if (emp, d) == (self.pagi, date(2026, 10, 8)):
                        day.decision, day.overtime_approved_minutes = "approved", 60
                        day.save(update_fields=["decision", "overtime_approved_minutes"])
            d += timedelta(days=1)

    def work(self, emp, d, inn, out):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift)
        for kind, (h, m) in (("in", inn), ("out", out)):
            t = datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                      occurred_at=t, received_at=t)
        return day

    def lines(self):
        run = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]
        rows = self.client.get(f"{RUNS}{run['id']}/").data["rows"]
        return {r["employee"]["full_name"]: self.client.get(f"{RUNS}{run['id']}/lines/{r['id']}/").data["line"]
                for r in rows}

    def test_off_by_default_nothing_changes(self):
        lines = self.lines()
        lama, pagi = lines["Lama Contoh"]["auto"], lines["Pagi Contoh"]["auto"]
        self.assertEqual((lama["long_halves"], lama["unpaid_days"]), (0, 0))
        self.assertEqual(lama["late_minutes"], (150 - 5) + 150 + (135 - 5) + 180 + (60 - 5))
        self.assertEqual(pagi["breakfast_days"], 2)

    def test_long_late_is_half_a_day_instead_of_the_fine(self):
        self.cfg.long_late_half_day_minutes = 120
        self.cfg.save()
        lama = self.lines()["Lama Contoh"]
        a = lama["auto"]
        self.assertEqual((a["long_halves"], a["long_days"], a["unpaid_days"], a["late_minutes"]), (4, 3, 2, 55))
        self.assertIn("Terlambat / pulang cepat lebih dari 2 jam (3 hari): dipotong 2 hari (aturan perusahaan), "
                      "tanpa denda per menit untuk keterlambatan itu. Maafkan di Siap gajian bila ada alasannya.",
                      lama["result"]["warnings"])
        self.assertNotIn("attendance_bonus", [x["code"] for x in lama["result"]["earnings"]])

    def test_siap_gajian_shows_the_same_rule(self):
        self.cfg.long_late_half_day_minutes = 120
        self.cfg.save()
        c = self.client.get(CHECK, {"month": "2026-10"}).data
        p = next(x for x in c["late"]["people"] if x["employee"]["full_name"] == "Lama Contoh")
        by_date = {x["date"]: x for x in p["days"]}
        self.assertEqual((by_date["2026-10-01"]["half"], by_date["2026-10-01"]["charged"], by_date["2026-10-01"]["rupiah"]),
                         (1, 0, 50000))                                     # 3.000.000 / 30 / 2
        self.assertEqual((by_date["2026-10-03"]["half"], by_date["2026-10-03"]["rupiah"]), (2, 100000))
        self.assertEqual((by_date["2026-10-05"]["half"], by_date["2026-10-05"]["rupiah"]), (0, 27500))
        self.assertTrue(by_date["2026-10-06"]["forgiven"])
        self.assertEqual((p["half_days"], p["minutes"], c["late"]["half_days"], c["rules"]["long_late_half_day_minutes"]),
                         (4, 55, 4, 120))

    def test_breakfast_only_with_an_spl(self):
        self.cfg.breakfast_needs_overtime = True
        self.cfg.save()
        self.assertEqual(self.lines()["Pagi Contoh"]["auto"]["breakfast_days"], 1)

    def test_the_setting_is_checked(self):
        r = self.client.patch("/api/hr/payroll/settings/", {"long_late_half_day_minutes": 10}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch("/api/hr/payroll/settings/", {"long_late_half_day_minutes": 120,
                                                            "breakfast_needs_overtime": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.cfg.refresh_from_db()
        self.assertEqual((self.cfg.long_late_half_day_minutes, self.cfg.breakfast_needs_overtime), (120, True))
        r = self.client.patch("/api/hr/payroll/settings/", {"long_late_half_day_minutes": None}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
