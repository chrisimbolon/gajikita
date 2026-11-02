"""
G9b (2 Nov 2026) — "Hapus data import": remove fingerprint taps between two dates, keep phone taps,
locked days and (by default) days HR already decided; then the same file imports again.
And taps on an approved leave day all the way through the API and payroll.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.leave.models import LeaveRequest
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayRun
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
IMPORT = "/api/hr/attendance/fingerprint/import/"
DELETE = "/api/hr/attendance/fingerprint/delete/"
ATTLOG = (b"    32\t2026-09-26 07:14:21\t1\t0\t1\t0\n"
          b"    32\t2026-09-26 17:00:05\t1\t1\t1\t0\n"
          b"    32\t2026-10-03 07:12:00\t1\t0\t1\t0\n"
          b"    32\t2026-10-03 21:36:00\t1\t1\t1\t0\n"
          b"    10\t2026-09-26 07:50:00\t1\t0\t1\t0\n"
          b"    10\t2026-09-26 17:05:00\t1\t1\t1\t0\n")
RANGE = {"start": "2026-09-26", "end": "2026-10-03"}


class FingerprintDeleteTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        mk = lambda no, name, fp: Employee.objects.create(
            organization=self.org, employee_no=no, full_name=name, join_date=date(2025, 1, 6), fingerprint_id=fp,
            default_shift=self.shift, base_rate=Decimal("4000000"))
        self.sudar, self.iqbal = mk("DK-019", "Sudarmono", "32"), mk("DK-021", "Iqbal", "10")
        self.assertEqual(self.import_file().data["applied"], {"events": 6, "days": 3})

    def import_file(self):
        return self.client.post(IMPORT, {"file": SimpleUploadedFile("attlog.dat", ATTLOG), "commit": "1"}, format="multipart")

    def delete(self, **kw):
        return self.client.post(DELETE, {**RANGE, **kw}, format="json")

    def day(self, emp, d):
        return AttendanceDay.objects.filter(employee=emp, date=d).first()

    def test_preview_changes_nothing(self):
        d = self.delete().data
        self.assertEqual(d["totals"], {"taps": 6, "days": 3, "people": 2, "locked_days": 0, "decided_kept": 0,
                                       "decided_removed": 0})
        self.assertEqual([(p["employee"]["full_name"], p["taps"]) for p in d["people"]], [("Iqbal", 2), ("Sudarmono", 4)])
        self.assertEqual(ClockEvent.objects.count(), 6)

    def test_delete_keeps_phone_taps_and_hr_decisions_then_reimport_works(self):
        approved = self.day(self.sudar, date(2026, 10, 3))
        approved.decision, approved.overtime_approved_minutes = "approved", 276
        approved.save()
        iqbal_day = self.day(self.iqbal, date(2026, 9, 26))
        ClockEvent.objects.create(organization=self.org, day=iqbal_day, employee=self.iqbal, kind="in", source="app",
                                  occurred_at=datetime(2026, 9, 26, 13, 51, tzinfo=WIB),
                                  received_at=datetime(2026, 9, 26, 13, 51, tzinfo=WIB))
        self.assertEqual(self.delete(commit=True).status_code, 400)                    # a reason is required
        d = self.delete(commit=True, reason="File salah, import ulang").data
        self.assertEqual(d["totals"]["decided_kept"], 1)
        self.assertEqual(d["decided"][0]["what"], ["Disetujui HR", "Lembur disetujui 276 menit"])
        self.assertEqual(d["applied"], {"taps": 4, "days": 2, "days_removed": 1})
        self.assertIsNone(self.day(self.sudar, date(2026, 9, 26)))                      # empty day gone
        self.assertEqual(self.day(self.sudar, date(2026, 10, 3)).events.count(), 2)     # HR's day kept
        self.assertEqual(list(self.day(self.iqbal, date(2026, 9, 26)).events.values_list("source", flat=True)), ["app"])
        audit = AuditEntry.objects.get(action="attendance.fingerprint_delete")
        self.assertEqual(audit.data["note"], "File salah, import ulang")
        self.assertEqual(self.import_file().data["applied"]["events"], 4)

    def test_delete_decided_days_too_resets_hr_decision(self):
        approved = self.day(self.sudar, date(2026, 10, 3))
        approved.decision, approved.overtime_approved_minutes = "approved", 276
        approved.save()
        d = self.delete(commit=True, keep_decided=False, reason="Mulai dari nol").data
        self.assertEqual((d["totals"]["decided_removed"], d["applied"]), (1, {"taps": 6, "days": 3, "days_removed": 3}))
        self.assertFalse(AttendanceDay.objects.exists())

    def test_locked_days_and_payroll_warnings(self):
        AttendanceDay.objects.filter(employee=self.sudar, date=date(2026, 9, 26)).update(is_locked=True)
        PayRun.objects.create(organization=self.org, name="Payroll Oktober 2026", period_start=date(2026, 9, 26),
                              period_end=date(2026, 10, 25))
        d = self.delete().data
        self.assertEqual((d["totals"]["locked_days"], d["totals"]["taps"], d["draft_runs"]), (1, 4, ["Payroll Oktober 2026"]))
        self.delete(commit=True, reason="Salah file")
        self.assertEqual(self.day(self.sudar, date(2026, 9, 26)).events.count(), 2)


class LeaveWithTapsApiTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                     grace_minutes=5, working_days="123456")
        self.emp = Employee.objects.create(organization=self.org, employee_no="DK-019", full_name="Sudarmono",
                                           join_date=date(2025, 1, 6), default_shift=shift, base_rate=Decimal("4000000"))
        d = date(2026, 10, 20)
        self.day = AttendanceDay.objects.create(organization=self.org, employee=self.emp, date=d, shift=shift)
        for kind, h, m in (("in", 8, 24), ("out", 17, 1)):
            t = datetime(2026, 10, 20, h, m, tzinfo=WIB)
            ClockEvent.objects.create(organization=self.org, day=self.day, employee=self.emp, kind=kind,
                                      source="fingerprint", occurred_at=t, received_at=t)
        LeaveRequest.objects.create(organization=self.org, employee=self.emp, kind="annual", start_date=d, end_date=d,
                                    days=1, status="approved")

    def test_review_detail_and_payroll(self):
        review = self.client.get("/api/hr/attendance/review/", {"days": 7}).data
        self.assertEqual([r["review_reasons"] for r in review["rows"]], [["Masuk padahal cuti tahunan"]])
        detail = self.client.get(f"/api/hr/attendance/days/{self.day.id}/").data["day"]
        self.assertEqual((detail["status"], detail["leave"], detail["needs_review"]), ("on_time", "Cuti tahunan", True))
        run = self.client.post("/api/hr/payroll/runs/", {"month": "2026-10"}, format="json").data["run"]
        line = self.client.get(f"/api/hr/payroll/runs/{run['id']}/").data["rows"][0]
        auto = self.client.get(f"/api/hr/payroll/runs/{run['id']}/lines/{line['id']}/").data["line"]["auto"]
        self.assertEqual(auto["late_minutes"], 0)

    def test_rejecting_returns_the_day_to_leave(self):
        resp = self.client.post(f"/api/hr/attendance/days/{self.day.id}/decide/", {"action": "reject", "note": "Salah tap"},
                                format="json")
        self.assertEqual((resp.data["day"]["status"], resp.data["day"]["status_label"]), ("leave", "Cuti tahunan"))
        self.assertIn("kembali ke cuti tahunan", AuditEntry.objects.get(action="attendance.reject").summary)
