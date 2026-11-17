"""
G17-8.1 (17 Nov 2026) — "Ubah" on an applied HR note: the one decision is undone and the row waits again
(Vinsensius 30 Sep "Cuti 1/2 hari": paid by mistake, changed to unpaid without a trip through the Rekap).
Made-up people.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, AttendanceExemption, ClockEvent, DayNote
from apps.attendance.note_decisions import AWAY, FORGIVE, HALF_CUTI, UL
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.leave.models import LeaveRequest
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
URL = "/api/hr/attendance/note-decisions/"


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class NoteUndoTests(APITestCase):
    def setUp(self):
        p = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        p.start()
        self.addCleanup(p.stop)
        self.org = Organization.objects.create(name="PT Contoh Ubah")
        hr = CustomUser.objects.create_user(email="hr@ubah.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        self.emp = Employee.objects.create(organization=self.org, employee_no="U-1", full_name="Vinsen Contoh",
                                           join_date=date(2020, 1, 6), default_shift=self.shift,
                                           base_rate=Decimal("2800000"), bpjs_tk_enrolled=False)
        self.d_half, self.d_ul, self.d_away, self.d_power = (date(2026, 9, 30), date(2026, 10, 6),
                                                             date(2026, 10, 9), date(2026, 10, 13))
        for d, text, code in ((self.d_half, "Cuti 1/2 hari berobat", ""), (self.d_ul, "UL", "UL"),
                              (self.d_away, "Belanja alat", ""), (self.d_power, "Mati lampu", "")):
            DayNote.objects.create(organization=self.org, employee=self.emp, date=d, text=text, code=code)
        self.taps(self.d_half, (12, 28), (17, 6))
        self.taps(self.d_power, (8, 20), (17, 0))

    def taps(self, d, *times):
        day = AttendanceDay.objects.create(organization=self.org, employee=self.emp, date=d, shift=self.shift)
        for kind, (h, m) in zip(("in", "out"), times):
            ClockEvent.objects.create(organization=self.org, day=day, employee=self.emp, kind=kind, source="fingerprint",
                                      occurred_at=at(d, h, m), received_at=at(d, h, m))
        return day

    def apply(self, group, d, choice=""):
        r = self.client.post(f"{URL}apply/", {"month": "2026-10", "group": group, "items": [
            {"employee": str(self.emp.pk), "date": d.isoformat(), "choice": choice}]}, format="json")
        self.assertEqual(r.data["applied"], 1, r.data)

    def undo(self, group, d):
        return self.client.post(f"{URL}undo/", {"month": "2026-10", "group": group, "employee": str(self.emp.pk),
                                                "date": d.isoformat()}, format="json")

    def state(self, body, group):
        return next(g for g in body["groups"] if g["key"] == group)["rows"][0]["state"]

    def test_half_day_paid_by_mistake_becomes_unpaid(self):
        self.apply(HALF_CUTI, self.d_half, "paid")
        r = self.undo(HALF_CUTI, self.d_half)
        self.assertEqual((r.status_code, self.state(r.data, HALF_CUTI)), (200, "todo"))
        day = AttendanceDay.objects.get(employee=self.emp, date=self.d_half)
        self.assertEqual((day.decision, day.half_day_leave, day.waive_late), ("", "", False))
        self.apply(HALF_CUTI, self.d_half, "unpaid")
        day.refresh_from_db()
        self.assertEqual(day.half_day_leave, "unpaid")

    def test_unpaid_leave_is_cancelled(self):
        self.apply(UL, self.d_ul)
        r = self.undo(UL, self.d_ul)
        self.assertEqual((r.status_code, self.state(r.data, UL)), (200, "todo"))
        self.assertEqual(LeaveRequest.objects.get(employee=self.emp).status, "cancelled")

    def test_tugas_luar_is_removed(self):
        self.apply(AWAY, self.d_away)
        self.assertEqual(self.undo(AWAY, self.d_away).status_code, 200)
        self.assertFalse(AttendanceExemption.objects.filter(employee=self.emp).exists())

    def test_overtime_decided_that_day_stays(self):
        self.apply(FORGIVE, self.d_power)
        AttendanceDay.objects.filter(employee=self.emp, date=self.d_power).update(overtime_approved_minutes=60)
        self.assertEqual(self.undo(FORGIVE, self.d_power).status_code, 200)
        day = AttendanceDay.objects.get(employee=self.emp, date=self.d_power)
        self.assertEqual((day.decision, day.waive_late, day.overtime_approved_minutes), ("approved", False, 60))

    def test_locked_and_not_decided_are_refused(self):
        r = self.undo(HALF_CUTI, self.d_half)
        self.assertEqual((r.status_code, r.data["message"]), (400, "Tidak ada keputusan untuk diubah di hari ini."))
        self.apply(HALF_CUTI, self.d_half, "paid")
        AttendanceDay.objects.filter(employee=self.emp, date=self.d_half).update(is_locked=True)
        self.assertEqual(self.undo(HALF_CUTI, self.d_half).status_code, 400)
