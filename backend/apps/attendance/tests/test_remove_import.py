"""attendance_remove_import (14 Nov 2026): one import day's machine taps leave a date range. Made-up data."""
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.employees.models import Employee
from apps.organizations.models import Organization

WIB = ZoneInfo("Asia/Jakarta")
ARGS = {"org": "Hapus", "imported": "2026-11-06", "start": "2026-09-26", "end": "2026-10-25"}


class RemoveImportTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Contoh Hapus")
        self.emp = Employee.objects.create(organization=self.org, employee_no="H-1", full_name="Eko Contoh",
                                           join_date=date(2025, 1, 6), base_rate=Decimal("3000000"))
        self.old = self.tap(date(2026, 10, 6), 7, 38, "fingerprint", imported=(2026, 11, 6))     # the wrong import
        self.real = self.tap(date(2026, 10, 8), 8, 2, "fingerprint", imported=(2026, 11, 12))    # the real import
        self.app = self.tap(date(2026, 10, 9), 8, 0, "app", imported=(2026, 11, 6))              # not a machine tap
        self.before = self.tap(date(2026, 9, 20), 8, 0, "fingerprint", imported=(2026, 11, 6))   # outside the range

    def tap(self, d, h, m, source, imported):
        day, _ = AttendanceDay.objects.get_or_create(organization=self.org, employee=self.emp, date=d)
        t = datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)
        e = ClockEvent.objects.create(organization=self.org, day=day, employee=self.emp, kind="in", source=source,
                                      occurred_at=t, received_at=t)
        ClockEvent.objects.filter(pk=e.pk).update(created_at=datetime(*imported, 17, 39, tzinfo=WIB))
        return e

    def left(self):
        return set(ClockEvent.objects.values_list("pk", flat=True))

    def test_preview_changes_nothing(self):
        out = StringIO()
        call_command("attendance_remove_import", stdout=out, **ARGS)
        self.assertIn("TOTAL 1 tap di 1 hari-orang, 1 karyawan.", out.getvalue())
        self.assertIn("hanya pratinjau", out.getvalue())
        self.assertEqual(len(self.left()), 4)

    def test_yes_removes_only_that_import_in_the_range(self):
        call_command("attendance_remove_import", yes=True, stdout=StringIO(), **ARGS)
        self.assertEqual(self.left(), {self.real.pk, self.app.pk, self.before.pk})
        self.assertTrue(AttendanceDay.objects.filter(employee=self.emp, date=date(2026, 10, 6)).exists())   # the day stays

    def test_a_locked_day_stops_it(self):
        AttendanceDay.objects.filter(date=date(2026, 10, 6)).update(is_locked=True)
        with self.assertRaisesMessage(CommandError, "sudah dikunci"):
            call_command("attendance_remove_import", yes=True, stdout=StringIO(), **ARGS)
        self.assertEqual(len(self.left()), 4)
