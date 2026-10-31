"""
G7 (28 Oct 2026) — leave from the phone, approval by the site manager (the worker's mandor)
or HR, HR's paper form, and approved leave showing on the attendance pages.
"""
import shutil
import tempfile
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.employees.worker_login import enable_login
from apps.leave.models import LeaveRequest
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
TODAY = date(2026, 10, 28)                      # a Wednesday
MINE = "/api/worker/leave/"
HR = "/api/hr/leave/"


class LeaveApiTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 28, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Tol Bersih")
        self.hr = CustomUser.objects.create_user(email="hr@tol.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=self.hr, role="hr")
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                     working_days="123456")

        def emp(no, name, joined, mandor=None):
            e = Employee.objects.create(organization=self.org, employee_no=no, full_name=name, join_date=joined,
                                        default_shift=shift, mandor=mandor, base_rate=Decimal("4690000"))
            enable_login(e, f"08120000000{no[-1]}", "482913")
            e.refresh_from_db()
            return e

        self.rudi = emp("T-1", "Rudi Mandor", date(2020, 3, 1))
        self.budi = emp("T-2", "Budi", date(2025, 1, 6), mandor=self.rudi)
        self.citra = emp("T-3", "Citra", date(2026, 6, 1))           # under 12 months, no mandor

    def as_(self, who):
        self.client.force_authenticate(self.hr if who == "hr" else who.user)

    def ask(self, who, **body):
        self.as_(who)
        data = {"kind": "annual", "start_date": "2026-11-02", "end_date": "2026-11-07", "reason": "Pulang kampung"}
        data.update(body)
        return self.client.post(MINE, data, format="multipart")

    # ── the phone ──
    def test_worker_asks_and_the_mandor_approves_on_the_phone(self):
        resp = self.ask(self.budi)                                     # Mon-Sat on a Mon-Sat shift
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual((resp.data["leave"]["days"], resp.data["leave"]["status"]), (6, "pending"))
        self.assertIn("Rudi Mandor", resp.data["message"])

        self.as_(self.rudi)
        mine = self.client.get(MINE).data
        self.assertTrue(mine["is_approver"])
        self.assertEqual([r["employee"]["full_name"] for r in mine["to_approve"]], ["Budi"])
        resp = self.client.post(f"{MINE}{resp.data['leave']['id']}/decide/", {"action": "approve"}, format="json")
        self.assertEqual((resp.status_code, resp.data["leave"]["status"]), (200, "approved"), resp.data)
        self.assertEqual(resp.data["leave"]["decided_by"], "Rudi Mandor")

        self.as_(self.budi)
        self.assertEqual(self.client.get(MINE).data["annual"], {"year": 2026, "entitled": 12, "used": 6, "left": 6,
                                                                "from_date": "2026-01-06"})

    def test_only_the_workers_own_mandor_can_decide(self):
        leave_id = self.ask(self.budi).data["leave"]["id"]
        self.as_(self.budi)
        self.assertEqual(self.client.post(f"{MINE}{leave_id}/decide/", {"action": "approve"}, format="json").status_code, 403)
        self.as_(self.citra)
        self.assertEqual(self.client.post(f"{MINE}{leave_id}/decide/", {"action": "approve"}, format="json").status_code, 403)

    def test_annual_balance_and_overlap_are_checked(self):
        resp = self.ask(self.budi, end_date="2026-11-17")             # 14 working days
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Sisa cuti tahunan 12 hari", resp.data["message"])
        self.assertEqual(self.ask(self.budi).status_code, 201)
        resp = self.ask(self.budi, kind="sick", start_date="2026-11-05", end_date="2026-11-05")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Sudah ada cuti tahunan", resp.data["message"])

    def test_a_new_worker_has_no_annual_leave_yet_and_sick_goes_to_hr(self):
        resp = self.ask(self.citra)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Belum ada sisa", resp.data["message"])
        resp = self.ask(self.citra, kind="sick", start_date="2026-10-27", end_date="2026-10-28")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIn("persetujuan HR", resp.data["message"])
        self.assertIsNone(resp.data["leave"]["approver"])

    def test_worker_can_cancel_only_while_waiting(self):
        leave_id = self.ask(self.budi).data["leave"]["id"]
        resp = self.client.post(f"{MINE}{leave_id}/cancel/")
        self.assertEqual(resp.data["leave"]["status"], "cancelled")
        leave_id = self.ask(self.budi).data["leave"]["id"]                    # the days are free again
        LeaveRequest.objects.filter(pk=leave_id).update(status="approved")
        self.assertEqual(self.client.post(f"{MINE}{leave_id}/cancel/").status_code, 400)

    def test_doctors_letter_upload(self):
        pdf = SimpleUploadedFile("surat.pdf", b"%PDF-1.4 surat dokter", content_type="application/pdf")
        resp = self.ask(self.budi, kind="sick", start_date="2026-10-26", end_date="2026-10-28", attachment=pdf)
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data["leave"]["has_attachment"])
        self.assertFalse(resp.data["leave"]["sick_note_missing"])
        self.as_("hr")
        file = self.client.get(f"{HR}{resp.data['leave']['id']}/attachment/")
        self.assertEqual((file.status_code, file["Content-Type"]), (200, "application/pdf"))
        bad = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")
        resp = self.ask(self.citra, kind="sick", start_date="2026-10-28", end_date="2026-10-28", attachment=bad)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("attachment", resp.data["errors"])

    # ── HR ──
    def test_hr_records_a_paper_form_and_absensi_shows_the_leave(self):
        self.as_("hr")
        resp = self.client.post(HR, {"employee": str(self.citra.id), "kind": "sick", "start_date": "2026-10-28",
                                     "end_date": "2026-10-28", "reason": "Demam"}, format="multipart")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual((resp.data["leave"]["status"], resp.data["leave"]["source"]), ("approved", "form"))

        daily = self.client.get("/api/hr/attendance/daily/", {"date": "2026-10-28"}).data
        citra = next(r for r in daily["rows"] if r["employee"]["full_name"] == "Citra")
        self.assertEqual((citra["status"], citra["status_label"], citra["needs_review"]), ("leave", "Sakit", False))
        counters = {c["key"]: c["count"] for c in daily["counters"]}
        self.assertEqual((counters["leave"], counters["absent"]), (1, 2))      # Rudi and Budi didn't come

        summary = self.client.get("/api/hr/summary/").data
        self.assertEqual(summary["leave"], {"pending": 0, "today": 1})

    def test_hr_list_counts_and_rejecting_needs_a_reason(self):
        a = self.ask(self.budi).data["leave"]["id"]
        self.ask(self.citra, kind="unpaid", start_date="2026-11-02", end_date="2026-11-02")
        self.as_("hr")
        data = self.client.get(HR).data
        self.assertEqual(data["counts"]["pending"], 2)
        self.assertEqual(len(data["requests"]), 2)
        self.assertEqual(self.client.post(f"{HR}{a}/decide/", {"action": "reject"}, format="json").status_code, 400)
        resp = self.client.post(f"{HR}{a}/decide/", {"action": "reject", "note": "Proyek sedang padat"}, format="json")
        self.assertEqual(resp.data["leave"]["status"], "rejected")
        data = self.client.get(HR, {"status": "all", "q": "budi"}).data
        self.assertEqual([r["status"] for r in data["requests"]], ["rejected"])
        self.assertEqual(data["counts"]["rejected"], 1)
        actions = sorted(AuditEntry.objects.filter(target_id=a).values_list("action", flat=True))   # same mocked clock
        self.assertEqual(actions, ["leave.create", "leave.reject"])

    def test_a_locked_payroll_day_blocks_approval(self):
        leave_id = self.ask(self.budi).data["leave"]["id"]
        AttendanceDay.objects.create(organization=self.org, employee=self.budi, date=date(2026, 11, 3), is_locked=True)
        self.as_("hr")
        resp = self.client.post(f"{HR}{leave_id}/decide/", {"action": "approve"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("pay run", resp.data["message"])

    def test_workers_cannot_open_hr_leave(self):
        self.as_(self.budi)
        self.assertEqual(self.client.get(HR).status_code, 403)
