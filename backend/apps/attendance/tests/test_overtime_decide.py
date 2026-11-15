"""
G17-6 (15 Nov 2026) — overtime decided in one place: Bayar lembur (hours per row), Hadir tanpa lembur,
Sudah diputuskan (change in place, Kembalikan ke belum) and Urungkan. Made-up people; the days copy the
15 Nov mix-up (Prayuda / Arief, October 2026).
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, AttendanceExemption, ClockEvent
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
PERIOD = "/api/hr/attendance/review/period/"
BULK = "/api/hr/attendance/review/bulk/"
UNDO = "/api/hr/attendance/review/undo/"


class OvertimeDecideTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 11, 15, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Contoh Lembur")
        hr = CustomUser.objects.create_user(email="hr@lembur.id", password="pass12345!", full_name="HR Lembur")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        mk = lambda no, name, **kw: Employee.objects.create(organization=self.org, employee_no=no, full_name=name,
                                                            join_date=date(2025, 1, 6), default_shift=self.shift,
                                                            base_rate=Decimal("3000000"), **kw)
        self.yuda, self.arif = mk("L-1", "Yuda Contoh"), mk("L-2", "Arif Contoh")
        self.sec = mk("L-3", "Satpam Contoh", overtime_eligible=False)
        self.y15 = self.work(self.yuda, date(2026, 10, 15), (7, 55), (21, 0))         # 240 min proposed
        self.y17 = self.work(self.yuda, date(2026, 10, 17), (7, 50), (23, 59))        # long day
        self.a26 = self.work(self.arif, date(2026, 9, 26), (7, 55), (20, 30))         # 210 min
        self.s01 = self.work(self.sec, date(2026, 10, 1), (7, 55), (20, 0))
        self.locked = self.work(self.arif, date(2026, 10, 2), (7, 55), (21, 0), is_locked=True)

    def work(self, emp, d, inn, out, **kw):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift, **kw)
        for kind, (h, m) in (("in", inn), ("out", out)):
            t = datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                      occurred_at=t, received_at=t)
        return day

    def post(self, **body):
        resp = self.client.post(BULK, {"note": "", "waive_late": False, **body}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data

    def state(self, day):
        day.refresh_from_db()
        return day.decision, day.overtime_approved_minutes

    def test_pay_what_the_boxes_say_and_the_rest_as_proposed(self):
        r = self.post(action="pay_overtime", ids=[str(self.y15.pk), str(self.a26.pk)], overtime={str(self.y15.pk): 120})
        self.assertEqual((r["decided"], r["overtime_minutes"]), (2, 120 + 210))
        self.assertEqual(self.state(self.y15), ("approved", 120))
        self.assertEqual(self.state(self.a26), ("approved", 210))
        self.assertRegex(r["batch"], r"^[0-9a-f]{32}$")
        self.assertEqual(AuditEntry.objects.filter(action="attendance.overtime_pay", data__batch=r["batch"]).count(), 2)

    def test_present_without_overtime_and_who_cannot_get_overtime(self):
        r = self.post(action="no_overtime", ids=[str(self.y15.pk), str(self.y17.pk), str(self.locked.pk)])
        self.assertEqual((r["decided"], r["overtime_minutes"], r["skipped"]), (2, 0, 1))
        self.assertEqual(self.state(self.y17), ("approved", None))
        r = self.post(action="pay_overtime", ids=[str(self.s01.pk)], overtime={str(self.s01.pk): 60})   # typed by hand
        self.assertEqual((r["decided"], r["skipped"]), (0, 1))
        self.assertIn("tidak berhak upah lembur", r["skipped_list"][0]["message"])
        self.assertEqual(self.post(action="no_overtime", ids=[str(self.s01.pk)])["decided"], 1)    # present is fine

    def test_decided_days_are_listed_and_changed_in_place(self):
        self.post(action="pay_overtime", ids=[str(self.y15.pk), str(self.y17.pk)])           # the mix-up: full pay
        d = self.client.get(PERIOD, {"month": "2026-10", "state": "decided", "kind": "overtime"}).data
        self.assertEqual(([x["date"] for x in d["rows"]], d["decided_all"]), (["2026-10-15", "2026-10-17"], 2))
        self.assertEqual(d["rows"][0]["overtime_proposed_minutes"], 240)                     # still shown
        self.assertEqual(self.client.get(PERIOD, {"month": "2026-10"}).data["decided_all"], 2)
        self.post(action="no_overtime", state="decided", month="2026-10", kind="overtime")
        self.assertEqual((self.state(self.y15), self.state(self.y17)), (("approved", None), ("approved", None)))

    def test_changing_overtime_keeps_the_late_decision(self):
        AttendanceDay.objects.filter(pk=self.y15.pk).update(decision="approved", waive_late=True,
                                                             overtime_approved_minutes=240)
        self.post(action="pay_overtime", ids=[str(self.y15.pk)], overtime={str(self.y15.pk): 60})
        self.y15.refresh_from_db()
        self.assertEqual((self.y15.waive_late, self.y15.overtime_approved_minutes), (True, 60))

    def test_back_to_open_and_rejected_days_are_not_paid(self):
        self.post(action="pay_overtime", ids=[str(self.a26.pk)])
        r = self.post(action="reset", ids=[str(self.a26.pk), str(self.y15.pk)])
        self.assertEqual((r["decided"], r["skipped"]), (1, 1))                                # y15 was never decided
        self.assertEqual(self.state(self.a26), ("", None))
        AttendanceDay.objects.filter(pk=self.y15.pk).update(decision="rejected")
        r = self.post(action="pay_overtime", ids=[str(self.y15.pk)])
        self.assertEqual((r["decided"], r["skipped"]), (0, 1))
        self.assertEqual(self.state(self.y15), ("rejected", None))

    def test_undo_puts_a_batch_back_once(self):
        r = self.post(action="pay_overtime", ids=[str(self.y15.pk), str(self.a26.pk)])
        resp = self.client.post(UNDO, {"batch": r["batch"]}, format="json")
        self.assertEqual((resp.status_code, resp.data["undone"]), (200, 2))
        self.assertEqual((self.state(self.y15), self.state(self.a26)), (("", None), ("", None)))
        self.assertEqual(self.client.post(UNDO, {"batch": r["batch"]}, format="json").status_code, 400)
        self.assertEqual(self.client.post(UNDO, {"batch": "nope"}, format="json").status_code, 400)

    def test_undo_leaves_days_changed_since(self):
        r = self.post(action="pay_overtime", ids=[str(self.y15.pk), str(self.a26.pk)])
        self.post(action="no_overtime", ids=[str(self.a26.pk)])                             # changed again
        resp = self.client.post(UNDO, {"batch": r["batch"]}, format="json")
        self.assertEqual((resp.data["undone"], resp.data["skipped"]), (1, 1))
        self.assertEqual(self.state(self.a26), ("approved", None))

    def test_undo_works_for_bulk_approve_and_tugas_luar(self):
        r = self.post(action="approve", ids=[str(self.y15.pk)], overtime_max_minutes=None)
        self.assertEqual(self.client.post(UNDO, {"batch": r["batch"]}, format="json").data["undone"], 1)
        self.assertEqual(self.state(self.y15), ("", None))
        r = self.post(action="away", ids=[str(self.y17.pk)], note="Belanja alat")
        self.assertTrue(AttendanceExemption.objects.filter(employee=self.yuda).exists())
        self.assertEqual(self.client.post(UNDO, {"batch": r["batch"]}, format="json").data["undone"], 1)
        self.assertFalse(AttendanceExemption.objects.filter(employee=self.yuda).exists())
