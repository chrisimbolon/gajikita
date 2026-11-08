"""
G12g (8 Nov 2026) — no silent overtime cap in Tinjau massal. Overtime is approved as the taps propose;
a cap only when HR asks (or the company set one in Pengaturan payroll); every cut is reported; days
over PP 35's 4 hours are a warning. Plus fix_capped_overtime, which gives back what the old 240-minute
default cut.
"""
from datetime import date, datetime, time
from decimal import Decimal
from io import StringIO
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import call_command
from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.attendance.review_bulk import capped_bulk_days
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
PERIOD = "/api/hr/attendance/review/period/"
BULK = "/api/hr/attendance/review/bulk/"
SETTINGS = "/api/hr/payroll/settings/"
NOW = datetime(2026, 11, 4, 10, tzinfo=WIB)


class OvertimeCapTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
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
                                                      base_rate=Decimal("3250000"))
        self.ganda, self.budi = mk("DK08", "Ganda"), mk("B-2", "Budi")
        self.long = self.work(self.ganda, date(2026, 10, 15), (8, 0), (2026, 10, 16, 2, 0))   # 17:00 -> 02:00 = 540
        self.short = self.work(self.ganda, date(2026, 10, 14), (8, 0), (2026, 10, 14, 20, 0))  # 180
        self.budi_long = self.work(self.budi, date(2026, 10, 15), (8, 0), (2026, 10, 15, 23, 30))  # 390
        self.cfg = PayrollSettings.for_org(self.org)

    def work(self, emp, d, inn, out):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift)
        for kind, t in (("in", datetime(d.year, d.month, d.day, *inn, tzinfo=WIB)), ("out", datetime(*out, tzinfo=WIB))):
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                      occurred_at=t, received_at=t)
        return day

    def approve(self, **kw):
        return self.client.post(BULK, {"action": "approve", "month": "2026-10", "kind": "overtime", **kw}, format="json")

    def minutes(self, day):
        day.refresh_from_db()
        return day.overtime_approved_minutes

    def test_no_cap_unless_asked(self):
        resp = self.approve()
        self.assertEqual((resp.data["decided"], resp.data["cap_minutes"], resp.data["trimmed_count"]), (3, None, 0))
        self.assertEqual((self.minutes(self.long), self.minutes(self.short), self.minutes(self.budi_long)), (540, 180, 390))
        self.assertEqual(resp.data["over_legal_days"], 2)                    # a warning, not a cut

    def test_the_company_cap_is_the_default_and_every_cut_is_reported(self):
        self.cfg.overtime_daily_cap_minutes = 300
        self.cfg.save()
        resp = self.approve()
        self.assertEqual((self.minutes(self.long), self.minutes(self.short), self.minutes(self.budi_long)), (300, 180, 300))
        self.assertEqual(resp.data["cap_minutes"], 300)
        self.assertEqual(resp.data["trimmed"], [
            {"name": "Budi", "date": "2026-10-15", "proposed": 390, "approved": 300},
            {"name": "Ganda", "date": "2026-10-15", "proposed": 540, "approved": 300}])
        audit = AuditEntry.objects.get(action="attendance.approve", target_id=str(self.long.id))
        self.assertIn("usulan 540, dibatasi 300 menit/hari", audit.summary)
        self.assertEqual((audit.data["proposed"], audit.data["cap"]), (540, 300))

    def test_null_means_no_cap_even_when_the_company_has_one(self):
        self.cfg.overtime_daily_cap_minutes = 240
        self.cfg.save()
        self.approve(overtime_max_minutes=None)
        self.assertEqual(self.minutes(self.long), 540)

    def test_the_queue_flags_days_over_four_hours_and_tells_the_cap(self):
        d = self.client.get(PERIOD, {"month": "2026-10", "kind": "overtime"}).data
        self.assertEqual((d["over_legal"], d["legal_day_minutes"], d["cap_minutes"]), (2, 240, None))
        self.assertEqual({r["date"] + r["employee"]["full_name"]: r["over_legal"] for r in d["rows"]},
                         {"2026-10-14Ganda": False, "2026-10-15Budi": True, "2026-10-15Ganda": True})

    def test_the_setting_is_checked(self):
        self.assertEqual(self.client.patch(SETTINGS, {"overtime_daily_cap_minutes": 20}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(SETTINGS, {"overtime_daily_cap_minutes": 600}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(SETTINGS, {"overtime_daily_cap_minutes": None}, format="json").status_code, 200)
        self.cfg.refresh_from_db()
        self.assertIsNone(self.cfg.overtime_daily_cap_minutes)

    def test_fix_capped_overtime_gives_back_only_what_a_bulk_approval_cut(self):
        self.approve(overtime_max_minutes=240)                               # the old behaviour: 3 days, 2 cut
        self.client.post(f"/api/hr/attendance/days/{self.budi_long.id}/decide/", {"action": "reset"}, format="json")
        self.client.post(f"/api/hr/attendance/days/{self.budi_long.id}/decide/",
                         {"action": "approve", "overtime_minutes": 120}, format="json")   # HR typed 120 by hand
        out = StringIO()
        call_command("fix_capped_overtime", month="2026-10", org=str(self.org.id), stdout=out)
        self.assertIn("240 ->  540 menit", out.getvalue())
        self.assertNotIn("Budi", out.getvalue())                           # a hand decision is never touched
        self.assertEqual(self.minutes(self.long), 240)                       # a dry run changes nothing

        call_command("fix_capped_overtime", month="2026-10", org="beton", employee="DK08", apply=True, stdout=out)
        self.assertEqual((self.minutes(self.long), self.minutes(self.budi_long), self.minutes(self.short)), (540, 120, 180))
        fix = AuditEntry.objects.get(action="attendance.overtime_uncap")
        self.assertIsNone(fix.actor)
        self.assertEqual(fix.data["after"]["overtime_approved_minutes"], 540)
        self.assertEqual(capped_bulk_days(self.org, date(2026, 9, 26), date(2026, 10, 25), NOW), [])   # safe to repeat

    def test_locked_days_are_listed_but_never_changed(self):
        self.approve(overtime_max_minutes=240)
        AttendanceDay.objects.filter(pk=self.long.pk).update(is_locked=True)
        out = StringIO()
        call_command("fix_capped_overtime", month="2026-10", org=str(self.org.id), apply=True, stdout=out)
        self.assertIn("TERKUNCI", out.getvalue())
        self.assertEqual((self.minutes(self.long), self.minutes(self.budi_long)), (240, 390))
