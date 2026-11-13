"""
G17-1 (13 Nov 2026) — one tap in a day. Made-up people; the times copy R1 (DKCB, October):
a lone 17:12 after the power cut is a clock-out, not 552 minutes late; Anthony's Note sheet cuts ½ day.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day
from apps.attendance.models import AttendanceDay, ClockEvent
from apps.attendance.review_kinds import kinds_of
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
WED = date(2026, 10, 14)                        # a Wednesday
PAGI = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
NIGHT = ShiftInfo(start=time(19), end=time(7), grace_minutes=5, working_days="1234567")
LATER = datetime(2026, 10, 20, 12, tzinfo=WIB)


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


def ev(*taps, shift=PAGI, day=WED, **kw):
    return evaluate_day(day, shift, list(taps), LATER, WIB, **kw)


class LoneTapTests(SimpleTestCase):
    def test_afternoon_tap_is_the_clock_out(self):
        r = ev(Tap("in", at(WED, 17, 12)))                 # how the machine import stores it today
        self.assertEqual((r.status, r.first_in, r.last_out), (Status.NO_CLOCK_IN, None, at(WED, 17, 12)))
        self.assertEqual((r.late_minutes, r.early_minutes, r.worked_minutes), (0, 0, 0))
        self.assertTrue(r.half_day and r.needs_review)
        self.assertIn("Tidak absen masuk (hanya tap pulang)", r.review_reasons)
        self.assertEqual(kinds_of(r.review_reasons), ["no_clock_in"])

    def test_morning_tap_is_still_the_clock_in(self):
        r = ev(Tap("in", at(WED, 7, 55)))
        self.assertEqual((r.status, r.first_in, r.last_out, r.half_day), (Status.NO_CLOCK_OUT, at(WED, 7, 55), None, True))

    def test_the_middle_of_the_shift_decides(self):
        self.assertEqual(ev(Tap("in", at(WED, 12, 29))).status, Status.NO_CLOCK_OUT)   # 08-17: middle 12:30
        self.assertEqual(ev(Tap("in", at(WED, 12, 30))).status, Status.NO_CLOCK_IN)

    def test_a_late_lone_clock_out_still_proposes_overtime(self):
        r = ev(Tap("out", at(WED, 22, 16)))                # Arief 14 Okt: "Mati lampu tidak finger in"
        self.assertEqual((r.status, r.overtime_proposed_minutes), (Status.NO_CLOCK_IN, 316))

    def test_hr_times_win(self):
        r = ev(Tap("in", at(WED, 17, 12)), hr_in=at(WED, 8), hr_out=at(WED, 17, 12))
        self.assertEqual((r.status, r.late_minutes, r.half_day), (Status.ON_TIME, 0, False))

    def test_two_taps_are_untouched(self):
        r = ev(Tap("in", at(WED, 13)), Tap("out", at(WED, 17)))
        self.assertEqual((r.status, r.late_minutes, r.half_day), (Status.LATE, 300, False))

    def test_night_shift_morning_tap_is_the_clock_out(self):
        r = ev(Tap("in", at(WED + timedelta(days=1), 6, 58)), shift=NIGHT)        # 19-07: middle 01:00
        self.assertEqual((r.status, r.late_minutes), (Status.NO_CLOCK_IN, 0))

    def test_day_off_and_leave_are_untouched(self):
        sunday = date(2026, 10, 18)
        r = ev(Tap("in", at(sunday, 17)), day=sunday)
        self.assertIn(Status.DAY_OFF_WORK, r.tags)                                   # as before
        self.assertFalse(r.half_day)                                                 # never a cut on a day off
        r = ev(Tap("in", at(WED, 17, 12)), leave="Sakit")
        self.assertFalse(r.half_day)


class HalfDayPayrollTests(APITestCase):
    RUNS = "/api/hr/payroll/runs/"

    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Contoh Tap")
        hr = CustomUser.objects.create_user(email="hr@tap.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        self.cfg = PayrollSettings.objects.create(organization=self.org, late_fine_per_minute=Decimal("500"),
                                                  late_tolerance_minutes=5, single_tap_half_day=True)
        self.emp = Employee.objects.create(organization=self.org, employee_no="T-1", full_name="Hadi Contoh",
                                           join_date=date(2025, 1, 6), default_shift=self.shift,
                                           base_rate=Decimal("3000000"), bpjs_tk_enrolled=False)
        start = date(2026, 9, 26)
        for i in range(30):
            d = start + timedelta(days=i)
            if d.isoweekday() == 7:
                continue
            taps = [("in", 17, 12)] if d == WED else [("in", 7, 55), ("out", 17, 0)]
            day = AttendanceDay.objects.create(organization=self.org, employee=self.emp, date=d, shift=self.shift)
            for kind, h, m in taps:
                ClockEvent.objects.create(organization=self.org, day=day, employee=self.emp, kind=kind,
                                          source="fingerprint", occurred_at=at(d, h, m), received_at=at(d, h, m))
        self.day = AttendanceDay.objects.get(employee=self.emp, date=WED)

    def line(self):
        run = self.client.post(self.RUNS, {"month": "2026-10"}, format="json").data["run"]
        rows = self.client.get(f"{self.RUNS}{run['id']}/").data["rows"]
        return self.client.get(f"{self.RUNS}{run['id']}/lines/{rows[0]['id']}/").data["line"]

    def amounts(self, line):
        return {x["code"]: Decimal(x["amount"]) for x in line["result"]["deductions"]}

    def test_one_tap_costs_half_a_day_and_no_late_fine(self):
        line = self.line()
        self.assertEqual((line["auto"]["half_days"], line["auto"]["unpaid_days"]), (1, 0.5))
        self.assertEqual(line["auto"]["present_days"], 25)                          # the lone clock-out came
        d = self.amounts(line)
        self.assertEqual(d["unpaid_leave"], Decimal("50000.00"))                     # 3.000.000 / 30 / 2
        self.assertNotIn("late", d)                                                  # not 552 minutes late
        self.assertTrue(line["result"]["warnings"][0].startswith("Tap sekali 1 hari: dipotong ½ hari"))

    def test_forgiven_or_corrected_days_are_not_cut(self):
        self.day.decision, self.day.waive_late = "approved", True
        self.day.save()
        self.assertEqual(self.line()["auto"]["half_days"], 0)

    def test_the_rule_is_off_by_default(self):
        self.cfg.single_tap_half_day = False
        self.cfg.save()
        line = self.line()
        self.assertEqual((line["auto"]["half_days"], line["auto"]["unpaid_days"]), (0, 0))
        self.assertNotIn("unpaid_leave", {k for k, v in self.amounts(line).items() if v})
