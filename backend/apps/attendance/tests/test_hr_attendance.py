"""
G3 (28 Oct 2026) — HR's attendance API: the daily page, the review queue,
approve / reject / fix times, the audit log and the protected selfie.
"""
import io
import shutil
import tempfile
import uuid
from datetime import date, datetime, time
from unittest import mock
from zoneinfo import ZoneInfo

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift, Site
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

WIB = ZoneInfo("Asia/Jakarta")
TUE = date(2026, 10, 27)
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=WIB)
BASE = "/api/hr/attendance/"


def at(h, m=0, d=TUE):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class HrAttendanceTests(APITestCase):
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
        self.now = mock.patch("django.utils.timezone.now", return_value=NOW)
        self.now.start()
        self.addCleanup(self.now.stop)
        self.org = Organization.objects.create(name="PT Bangun Wira Indah")
        self.hr = CustomUser.objects.create_user(email="hr@test.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=self.hr, role="hr")
        self.client.force_authenticate(self.hr)
        self.site = Site.objects.create(organization=self.org, name="Workshop")
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=10, working_days="123456")
        self.emps = {}
        for no, name in (("A", "Andi"), ("B", "Budi"), ("C", "Citra"), ("D", "Dedi")):
            self.emps[no] = Employee.objects.create(organization=self.org, employee_no=no, full_name=name,
                                                    join_date=date(2026, 1, 5), default_shift=self.shift)
        self.day_a = self._day("A", ("in", at(7, 55)), ("out", at(17, 5)))
        self.day_b = self._day("B", ("in", at(8, 30)), ("out", at(17)))
        self.day_d = self._day("D", ("in", at(7, 58)))                       # never clocked out
        # C has no taps at all: absent

    def _day(self, no, *taps, flags=()):
        emp = self.emps[no]
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=TUE, shift=self.shift)
        for kind, when in taps:
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, site=self.site,
                                      occurred_at=when, received_at=when, flags=list(flags))
        return day

    def _counter(self, data, key):
        return next(c["count"] for c in data["counters"] if c["key"] == key)

    # ── the daily page ──
    def test_daily_page_counts_every_status(self):
        resp = self.client.get(f"{BASE}daily/", {"date": "2026-10-27"})
        self.assertEqual(resp.status_code, 200, resp.data)
        status_of = {r["employee"]["employee_no"]: r["status"] for r in resp.data["rows"]}
        self.assertEqual(status_of, {"A": "on_time", "B": "late", "C": "absent", "D": "no_clock_out"})
        for key, n in (("on_time", 1), ("late", 1), ("absent", 1), ("no_clock_out", 1), ("needs_review", 2)):
            self.assertEqual(self._counter(resp.data, key), n, key)

    def test_sunday_is_a_day_off(self):
        resp = self.client.get(f"{BASE}daily/", {"date": "2026-11-01"})
        self.assertEqual(self._counter(resp.data, "day_off"), 4)

    def test_people_who_joined_later_are_not_listed(self):
        Employee.objects.create(organization=self.org, employee_no="E", full_name="Eka", join_date=date(2026, 11, 1))
        names = [r["employee"]["employee_no"] for r in self.client.get(f"{BASE}daily/", {"date": "2026-10-27"}).data["rows"]]
        self.assertNotIn("E", names)

    # ── the review queue ──
    def test_review_queue_lists_only_what_needs_hr(self):
        resp = self.client.get(f"{BASE}review/", {"days": 7})
        self.assertEqual(sorted(r["employee"]["employee_no"] for r in resp.data["rows"]), ["B", "D"])
        labels = {s["label"]: s["count"] for s in resp.data["summary"]}
        self.assertEqual(labels, {"Terlambat": 1, "Tidak absen pulang": 1})

    def test_outside_site_needs_review(self):
        self.emps["E"] = Employee.objects.create(organization=self.org, employee_no="E", full_name="Eka",
                                                 join_date=date(2026, 1, 5), default_shift=self.shift)
        self._day("E", ("in", at(7, 50)), ("out", at(17)), flags=("outside_site",))
        rows = self.client.get(f"{BASE}review/").data["rows"]
        eka = next(r for r in rows if r["employee"]["employee_no"] == "E")
        self.assertEqual(eka["review_reasons"], ["Di luar lokasi"])

    # ── decisions ──
    def test_approve_and_excuse_the_lateness_writes_the_audit_log(self):
        resp = self.client.post(f"{BASE}days/{self.day_b.id}/decide/", {"action": "approve", "waive_late": True,
                                                                         "note": "Ban bocor"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual((resp.data["day"]["status"], resp.data["day"]["decision"]), ("on_time", "approved"))
        self.assertEqual(len(resp.data["day"]["audit"]), 1)
        self.assertEqual(resp.data["day"]["audit"][0]["actor"], "Anthony")
        entry = AuditEntry.objects.get()
        self.assertEqual((entry.data["before"]["decision"], entry.data["after"]["decision"]), ("", "approved"))
        self.assertNotIn("B", [r["employee"]["employee_no"] for r in self.client.get(f"{BASE}review/").data["rows"]])

    def test_reject_needs_a_reason(self):
        url = f"{BASE}days/{self.day_b.id}/decide/"
        self.assertEqual(self.client.post(url, {"action": "reject"}, format="json").status_code, 400)
        resp = self.client.post(url, {"action": "reject", "note": "Titip absen"}, format="json")
        self.assertEqual(resp.data["day"]["status"], "rejected")

    def test_reset_a_decision(self):
        url = f"{BASE}days/{self.day_b.id}/decide/"
        self.client.post(url, {"action": "approve"}, format="json")
        resp = self.client.post(url, {"action": "reset"}, format="json")
        self.assertEqual((resp.data["day"]["decision"], resp.data["day"]["needs_review"]), ("", True))
        self.assertEqual(AuditEntry.objects.count(), 2)

    def test_approve_overtime(self):
        day = self._day("C", ("in", at(7, 55)), ("out", at(19)))
        resp = self.client.post(f"{BASE}days/{day.id}/decide/", {"action": "approve", "overtime_minutes": 90}, format="json")
        self.assertEqual((resp.data["day"]["overtime_proposed_minutes"], resp.data["day"]["overtime_approved_minutes"]),
                         (120, 90))

    # ── fixing times ──
    def test_fix_a_forgotten_clock_out(self):
        resp = self.client.post(f"{BASE}fix/", {"employee": str(self.emps["D"].id), "date": "2026-10-27",
                                                "clock_out": "17:00", "reason": "Lupa absen pulang, dicek mandor"},
                                format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        d = resp.data["day"]
        self.assertEqual((d["status"], d["last_out"], d["decision"], d["hr_fixed"]), ("on_time", "17:00", "approved", True))
        self.assertIn("pulang 17:00", d["audit"][0]["summary"])

    def test_fix_creates_the_day_for_someone_absent(self):
        resp = self.client.post(f"{BASE}fix/", {"employee": str(self.emps["C"].id), "date": "2026-10-27",
                                                "clock_in": "08:00", "clock_out": "17:00", "reason": "HP rusak"},
                                format="json")
        self.assertEqual(resp.data["day"]["status"], "on_time")
        self.assertTrue(AttendanceDay.objects.filter(employee=self.emps["C"], date=TUE).exists())

    def test_fix_needs_a_reason_and_a_time(self):
        url, emp = f"{BASE}fix/", str(self.emps["D"].id)
        self.assertEqual(self.client.post(url, {"employee": emp, "date": "2026-10-27", "clock_out": "17:00", "reason": ""},
                                          format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"employee": emp, "date": "2026-10-27", "reason": "x"},
                                          format="json").status_code, 400)

    def test_locked_day_cannot_change(self):
        AttendanceDay.objects.filter(pk=self.day_b.pk).update(is_locked=True)
        resp = self.client.post(f"{BASE}days/{self.day_b.id}/decide/", {"action": "approve"}, format="json")
        self.assertEqual(resp.status_code, 400)

    # ── access ──
    def test_other_company_and_workers_are_kept_out(self):
        other = Organization.objects.create(name="PT Lain")
        boss = CustomUser.objects.create_user(email="boss@lain.id", password="pass12345!", full_name="Boss")
        OrganizationMembership.objects.create(organization=other, user=boss, role="owner")
        self.client.force_authenticate(boss)
        self.assertEqual(self.client.get(f"{BASE}days/{self.day_b.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"{BASE}daily/").data["rows"], [])
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f"{BASE}daily/").status_code, 401)

    def test_selfie_only_for_hr_of_the_same_company(self):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "white").save(buf, "JPEG")
        ev = self.day_a.events.first()
        ev.selfie = SimpleUploadedFile("s.jpg", buf.getvalue(), content_type="image/jpeg")
        ev.save()
        resp = self.client.get(f"{BASE}events/{ev.id}/selfie/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b"".join(resp.streaming_content)[:2], b"\xff\xd8")     # a JPEG
        self.assertEqual(self.client.get(f"{BASE}events/{uuid.uuid4()}/selfie/").status_code, 404)
