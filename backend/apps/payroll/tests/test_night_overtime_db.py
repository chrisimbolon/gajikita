"""
G12e (7 Nov 2026) — the night-overtime rules through the database: settings API, the one-query
context, evaluate(), and the payroll numbers. A week modelled on DKCB's Ganda, 19-24 Oct 2026.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.day_status import Status
from apps.attendance.models import AttendanceDay, ClockEvent
from apps.attendance.review import evaluate, evaluate_missing, night_context
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings
from apps.payroll.payrun import collect_numbers
from apps.sites.models import Shift, Site

WIB = ZoneInfo("Asia/Jakarta")
URL = "/api/hr/payroll/settings/"
DKCB = [{"until": "01:59", "start": "10:00"}, {"until": "04:00", "start": "13:00"}, {"until": "", "start": ""}]


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class NightOvertimeDbTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        self.hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=self.hr, role="hr")
        self.client.force_authenticate(self.hr)
        self.site = Site.objects.create(organization=self.org, name="Batching Plant")
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        self.cfg = PayrollSettings.objects.create(
            organization=self.org, overtime_mode="flat", overtime_rounding="half_down", overtime_min_minutes=60,
            flat_overtime_hour=Decimal("12500"), meal_rule="late_out", meal_allowance=Decimal("15000"),
            meal_midnight_extra=True, late_fine_per_minute=Decimal("500"), late_tolerance_minutes=5,
            night_ot_rules=DKCB)
        self.ganda = Employee.objects.create(organization=self.org, employee_no="DK08", full_name="Ganda",
                                             join_date=date(2021, 6, 2), default_shift=self.shift,
                                             base_rate=Decimal("3250000"))
        D = date
        self.days = {
            D(2026, 10, 19): self.work(D(2026, 10, 19), (8, 15), at(D(2026, 10, 20), 0, 30)),
            D(2026, 10, 20): self.work(D(2026, 10, 20), (10, 19), at(D(2026, 10, 20), 17, 30)),
            D(2026, 10, 21): self.work(D(2026, 10, 21), (8, 21), at(D(2026, 10, 22), 0, 6)),
            D(2026, 10, 22): self.work(D(2026, 10, 22), (8, 27), at(D(2026, 10, 22), 20, 30)),
            D(2026, 10, 23): self.work(D(2026, 10, 23), (8, 15), at(D(2026, 10, 24), 4, 30)),
        }                                                          # 24 Oct: no taps (home at 04:30)

    def work(self, d, inn, out):
        day = AttendanceDay.objects.create(organization=self.org, employee=self.ganda, date=d, shift=self.shift)
        for kind, when in (("in", at(d, *inn)), ("out", out)):
            ClockEvent.objects.create(organization=self.org, day=day, employee=self.ganda, kind=kind, site=self.site,
                                      occurred_at=when, received_at=when)
        return day

    def test_one_context_for_the_week(self):
        ctx = night_context(self.org.id, None, date(2026, 10, 19), date(2026, 10, 24))
        self.assertEqual(ctx.overtime_min, 60)
        self.assertIsNone(ctx.night_for(self.ganda.id, date(2026, 10, 19)))
        self.assertEqual(ctx.night_for(self.ganda.id, date(2026, 10, 20)).start, time(10))
        self.assertTrue(ctx.night_for(self.ganda.id, date(2026, 10, 24)).day_off)

    def test_each_day(self):
        r20 = evaluate(self.days[date(2026, 10, 20)])
        self.assertEqual((r20.late_minutes, r20.note), (19, "Lembur malam sampai 00:30: masuk jam 10:00"))
        self.assertNotIn(Status.LATE, evaluate(self.days[date(2026, 10, 22)]).tags)       # allowed in at 10:00
        r24 = evaluate_missing(self.ganda, date(2026, 10, 24))
        self.assertEqual(r24.status, Status.DAY_OFF)                                      # not absent
        self.assertEqual(evaluate(self.days[date(2026, 10, 22)]).overtime_proposed_minutes, 210)

    def test_payroll_numbers(self):
        nums = collect_numbers(self.ganda, date(2026, 10, 19), date(2026, 10, 24), self.cfg, self.days, {},
                               datetime(2026, 10, 26, 10, tzinfo=WIB))
        self.assertEqual((nums["present_days"], nums["absent_days"]), (5, 0))
        self.assertEqual(nums["late_minutes"], 10 + 14 + 16 + 10)                 # 19, 20, 21, 23 Oct
        self.assertEqual(nums["meal_days"], 2 + 0 + 2 + 1 + 2)                     # a second meal past 00:00

    def test_rules_off_means_no_change(self):
        self.cfg.night_ot_rules = []
        self.cfg.save()
        self.assertEqual(evaluate(self.days[date(2026, 10, 20)]).late_minutes, 139)
        self.assertEqual(evaluate_missing(self.ganda, date(2026, 10, 24)).status, Status.ABSENT)

    def test_settings_api_checks_the_rows(self):
        resp = self.client.patch(URL, {"night_ot_rules": [{"until": "04:00", "start": "13:00"},
                                                          {"until": "02:00", "start": "10:00"}]}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.patch(URL, {"night_ot_rules": [], "overtime_min_minutes": 30, "breakfast_allowance": "12000",
                                       "breakfast_before": "07:00"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["settings"]["night_ot_rules"], [])
        self.assertEqual(self.client.patch(URL, {"overtime_min_minutes": 500}, format="json").status_code, 400)
