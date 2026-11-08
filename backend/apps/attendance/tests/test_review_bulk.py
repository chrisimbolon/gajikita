"""
G11 (4 Nov 2026) — Tinjau massal per periode: the days waiting for HR in a pay period, counted
by kind, and decided many at once (overtime capped), each with its own audit line.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
PERIOD = "/api/hr/attendance/review/period/"
BULK = "/api/hr/attendance/review/bulk/"


class BulkReviewTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 11, 4, 10, tzinfo=WIB))
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
        self.ot180 = self.work(self.andi, date(2026, 9, 28), (7, 55), (20, 0))
        self.late = self.work(self.andi, date(2026, 9, 29), (8, 20), (17, 0))
        self.ot390 = self.work(self.andi, date(2026, 9, 30), (7, 50), (23, 30))
        self.ot120 = self.work(self.budi, date(2026, 9, 28), (7, 55), (19, 0))
        self.tp = self.work(self.budi, date(2026, 9, 29), (7, 55), None)
        self.locked = self.work(self.budi, date(2026, 10, 1), (7, 55), (21, 0), is_locked=True)
        self.done = self.work(self.andi, date(2026, 10, 2), (7, 55), (21, 0), decision="approved",
                              overtime_approved_minutes=240)

    def work(self, emp, d, inn, out, **kw):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift, **kw)
        for kind, hm in (("in", inn), ("out", out)):
            if hm:
                t = datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=WIB)
                ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                          occurred_at=t, received_at=t)
        return day

    def test_the_period_queue_counts_every_kind(self):
        d = self.client.get(PERIOD, {"month": "2026-10"}).data
        self.assertEqual((d["start"], d["end"], d["all"], d["total"]), ("2026-09-26", "2026-10-25", 5, 5))
        self.assertEqual({k["key"]: k["count"] for k in d["kinds"]}, {"overtime": 3, "late": 1, "no_clock_out": 1})
        ot = self.client.get(PERIOD, {"month": "2026-10", "kind": "overtime"}).data
        self.assertEqual([(r["employee"]["full_name"], r["date"]) for r in ot["rows"]],
                         [("Andi", "2026-09-28"), ("Budi", "2026-09-28"), ("Andi", "2026-09-30")])
        self.assertEqual(ot["rows"][0]["kinds"], ["overtime"])

    def test_approve_all_overtime_of_the_period_with_a_cap(self):
        resp = self.client.post(BULK, {"action": "approve", "month": "2026-10", "kind": "overtime",
                                       "overtime_max_minutes": 240, "note": "Sesuai SPL"}, format="json")
        self.assertEqual({k: resp.data[k] for k in ("success", "decided", "skipped", "overtime_minutes")},
                         {"success": True, "decided": 3, "skipped": 0, "overtime_minutes": 540})
        self.assertEqual((resp.data["cap_minutes"], resp.data["trimmed_count"]), (240, 1))     # G12g: the cut is told
        self.assertEqual(resp.data["trimmed"], [{"name": "Andi", "date": "2026-09-30", "proposed": 390, "approved": 240}])
        for day, minutes in ((self.ot180, 180), (self.ot390, 240), (self.ot120, 120)):
            day.refresh_from_db()
            self.assertEqual((day.decision, day.overtime_approved_minutes), ("approved", minutes))
        self.late.refresh_from_db()
        self.assertEqual(self.late.decision, "")                         # not an overtime day: untouched
        audit = AuditEntry.objects.filter(action="attendance.approve")
        self.assertEqual(audit.count(), 3)
        self.assertTrue(all(a.data["bulk"] for a in audit))
        left = self.client.get(PERIOD, {"month": "2026-10"}).data
        self.assertEqual(left["all"], 2)

    def test_ticked_rows_reject_needs_a_note_and_skips_locked_days(self):
        ids = [str(self.tp.id), str(self.locked.id)]
        self.assertEqual(self.client.post(BULK, {"action": "reject", "ids": ids}, format="json").status_code, 400)
        resp = self.client.post(BULK, {"action": "reject", "ids": ids, "note": "Tidak masuk, titip absen"}, format="json")
        self.assertEqual((resp.data["decided"], resp.data["skipped"]), (1, 1))
        self.tp.refresh_from_db()
        self.locked.refresh_from_db()
        self.assertEqual((self.tp.decision, self.locked.decision), ("rejected", ""))

    def test_the_cap_does_not_cut_rest_day_work(self):
        sunday = self.work(self.budi, date(2026, 10, 4), (8, 0), (14, 30))          # 390 minutes on a Sunday
        self.client.post(BULK, {"action": "approve", "ids": [str(sunday.id)], "overtime_max_minutes": 240},
                         format="json")
        sunday.refresh_from_db()
        self.assertEqual(sunday.overtime_approved_minutes, 390)

    def test_workers_cannot_use_it(self):
        self.client.force_authenticate(CustomUser.objects.create_user(email="w@b.id", password="pass12345!",
                                                                      full_name="W", role="employee"))
        self.assertEqual(self.client.get(PERIOD).status_code, 403)
        self.assertEqual(self.client.post(BULK, {"action": "approve", "month": "2026-10"}, format="json").status_code, 403)
