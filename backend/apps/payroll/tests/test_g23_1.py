"""
G23-1 (28 Nov 2026) — uang makan 'pulang malam' only when that day's overtime is approved (Anthony, 27 Nov visit,
A3: "lembur harus disetujui"). A company switch, off by default. People not paid overtime (a TM driver, paid per
kubikasi) keep earning it from the clock-out (A5). Made-up company and people.
"""
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.meals import LATE_OUT, OVERTIME_DAY, PRESENT_DAY, meal_count, waits_for_overtime
from apps.payroll.models import PayrollSettings
from apps.payroll.payrun import collect_numbers
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
DAY = date(2026, 10, 15)
NEXT = date(2026, 10, 16)
NOW = datetime(2026, 10, 26, 10, tzinfo=WIB)


def at(h, m, d=DAY):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


def meals(rule, out, ot=0, needs=True):
    return meal_count(rule, DAY, at(8, 5), out, False, ot, time(19), WIB, midnight_extra=True, needs_overtime=needs)


class PureTests(SimpleTestCase):
    def test_pulang_malam_needs_the_overtime_approved(self):
        self.assertEqual(meals(LATE_OUT, at(20, 30), needs=False), 1)                 # switch off: as before
        self.assertEqual(meals(LATE_OUT, at(20, 30)), 0)                              # no approved overtime
        self.assertEqual(meals(LATE_OUT, at(20, 30), ot=210), 1)
        self.assertEqual(meals(LATE_OUT, at(0, 0, NEXT), ot=420), 2)                 # 00:00 still 2x
        self.assertEqual(meals(LATE_OUT, at(0, 0, NEXT)), 0)
        self.assertEqual(meals(LATE_OUT, at(18, 30), ot=60), 0)                      # approved, but home before 19:00

    def test_other_rules_unchanged(self):
        self.assertEqual(meals(PRESENT_DAY, at(17, 5)), 1)
        self.assertEqual(meals(OVERTIME_DAY, at(21, 0), ot=240), 1)

    def test_waiting(self):
        wait = lambda out, ot=0, needs=True: waits_for_overtime(LATE_OUT, DAY, at(8, 5), out, False, ot, time(19), WIB, needs)
        self.assertTrue(wait(at(20, 30)))
        self.assertFalse(wait(at(20, 30), ot=210))                                   # paid
        self.assertFalse(wait(at(17, 10)))                                           # not a late day anyway
        self.assertFalse(wait(at(20, 30), needs=False))


class WhyTests(SimpleTestCase):
    def day(self, overtime_open):
        from apps.attendance import ringkasan as R
        from apps.attendance.attendance_log import Rates
        t = {"date": DAY, "day_id": "x", "working": True, "status": "on_time", "event": "", "late_raw": 0,
             "early_raw": 0, "first_in": at(8, 0), "last_out": at(20, 30), "inside_grace": 0, "night_excused": 0,
             "night_note": "", "night_rule": "", "locked": False, "late_tag": False, "early_tag": False, "late": 0,
             "early": 0, "late_half": False, "early_half": False, "one_tap": False, "permit": False, "half_leave": "",
             "forgiven": False, "hr_fixed": False, "decision": "", "rejected": False, "leave_kind": "",
             "leave_label": "", "absent": False, "unpaid_leave": False, "exempt": False, "meal": 0, "breakfast": False,
             "overtime": 0, "meal_rule": "late_out", "meal_wait": True, "overtime_open": overtime_open,
             "present": True, "holiday": False, "disrupted": False, "worked_minutes": 630, "spl": ""}
        cell = {"d": DAY.isoformat(), "c": "H", "s": "on_time", "l": "Tepat waktu", "day": "x", "rv": False, "ot": 0,
                "otp": 210 if overtime_open else 0, "late": 0, "early": 0, "n": None}
        emp = NS(id="E1", pay_type="monthly", default_shift=NS(start_time=time(8), end_time=time(17), saturday_end_time=None))
        cfg = NS(meal_late_after=time(19), breakfast_before=None)
        rates = Rates(fine=500, tolerance=5, per_day=100000, half_day=50000, meal=15000)
        return R.build_days(emp, [t], [cell], rates, cfg, {}, lambda t: None)[0]

    def test_waiting_for_hr(self):
        day = self.day(overtime_open=True)
        self.assertIn("Makan menunggu lembur", [c["label"] for c in day["chips"]])
        self.assertTrue(any(w.startswith("Uang makan menunggu lembur disetujui: pulang 20:30") for w in day["why"]), day["why"])
        self.assertFalse(any("aturan: pulang jam 19:00" in w for w in day["why"]))     # not the old reason too

    def test_no_overtime_approved(self):
        day = self.day(overtime_open=False)
        self.assertTrue(any("tidak ada lembur yang disetujui hari itu" in w for w in day["why"]), day["why"])


class PayrollTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Contoh")
        hr = CustomUser.objects.create_user(email="hr@contoh.id", password="pass12345!", full_name="Rina HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        self.helper = self.person("C01", "Budi Helper", eligible=True)
        self.driver = self.person("C02", "Tono Sopir", eligible=False)
        self.cfg = PayrollSettings.for_org(self.org)
        self.cfg.meal_rule, self.cfg.meal_allowance, self.cfg.meal_late_after = "late_out", Decimal("15000"), time(19)
        self.cfg.meal_midnight_extra = True
        self.cfg.save()

    def person(self, no, name, eligible):
        return Employee.objects.create(organization=self.org, employee_no=no, full_name=name, join_date=date(2022, 1, 3),
                                       default_shift=self.shift, base_rate=Decimal("3000000"), overtime_eligible=eligible)

    def taps(self, emp, out):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=DAY, shift=self.shift)
        for kind, when in (("in", at(8, 0)), ("out", out)):
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                      occurred_at=when, received_at=when)
        return day

    def nums(self, emp):
        days = {d.date: d for d in AttendanceDay.objects.filter(employee=emp)}
        trace = []
        n = collect_numbers(emp, DAY, DAY, PayrollSettings.for_org(self.org), days, {}, NOW, trace=trace)
        return n, trace[0]

    def switch(self, on):
        r = self.client.patch("/api/hr/payroll/settings/", {"meal_needs_overtime": on}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["success"], r.data)
        self.assertEqual(PayrollSettings.for_org(self.org).meal_needs_overtime, on)          # saved

    def test_off_by_default(self):
        self.assertFalse(PayrollSettings.for_org(self.org).meal_needs_overtime)
        self.taps(self.helper, at(20, 30))
        self.assertEqual(self.nums(self.helper)[0]["meal_days"], 1)                   # as before G23-1

    def test_meal_waits_for_the_overtime_decision(self):
        self.switch(True)
        day = self.taps(self.helper, at(20, 30))
        n, t = self.nums(self.helper)
        self.assertEqual((n["meal_days"], n.get("meal_wait_days"), t["meal_wait"], t["overtime_open"]), (0, 1, True, True))
        r = self.client.post(f"/api/hr/attendance/days/{day.id}/decide/", {"action": "approve", "overtime_minutes": 210},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        n, t = self.nums(self.helper)
        self.assertEqual((n["meal_days"], n.get("meal_wait_days"), t["meal_wait"]), (1, None, False))

    def test_a_driver_without_overtime_keeps_the_clock_out_rule(self):
        self.switch(True)
        self.taps(self.driver, at(0, 10, NEXT))
        n, t = self.nums(self.driver)
        self.assertEqual((n["meal_days"], t["meal_wait"]), (2, False))
