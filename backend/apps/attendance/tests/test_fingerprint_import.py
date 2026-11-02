"""
G9 (1 Nov 2026) — fingerprint taps into Absensi: match by machine ID, preview, save, repeat safely.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
URL = "/api/hr/attendance/fingerprint/import/"
ATTLOG = (b"    32\t2026-09-26 07:14:21\t1\t0\t1\t0\n"
          b"    32\t2026-09-26 07:14:50\t1\t0\t1\t0\n"
          b"    32\t2026-09-26 17:00:05\t1\t1\t1\t0\n"
          b"    32\t2026-10-03 07:12:00\t1\t0\t1\t0\n"
          b"    32\t2026-10-03 21:36:00\t1\t1\t1\t0\n"
          b"  0010\t2026-09-26 18:52:00\t1\t0\t1\t0\n"
          b"  0010\t2026-09-27 07:00:00\t1\t1\t1\t0\n"
          b"    99\t2026-09-26 08:00:00\t1\t0\t1\t0\n")


class FingerprintImportTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        day = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                   working_days="123456")
        night = Shift.objects.create(organization=self.org, name="Malam", start_time=time(19), end_time=time(7),
                                     working_days="1234567")
        mk = lambda no, name, fp, shift: Employee.objects.create(
            organization=self.org, employee_no=no, full_name=name, join_date=date(2025, 1, 6), fingerprint_id=fp,
            default_shift=shift, base_rate=Decimal("4000000"))
        self.sudar = mk("DK-019", "Sudarmono", "32", day)
        self.iqbal = mk("DK-021", "Iqbal", "10", night)
        mk("DK-099", "Belum Dihubungkan", "", day)

    def post(self, commit, data=ATTLOG, name="1_attlog.dat"):
        return self.client.post(URL, {"file": SimpleUploadedFile(name, data), "commit": commit}, format="multipart")

    def test_preview_matches_people_and_lists_unknown_ids(self):
        resp = self.post("0")
        self.assertEqual(resp.status_code, 200, resp.data)
        d = resp.data
        self.assertEqual((d["format"], d["punches"], d["period"]),
                         ("attlog.dat (download dari mesin)", 8, {"start": "2026-09-26", "end": "2026-10-03"}))
        self.assertEqual(d["totals"], {"people": 2, "unknown": 1, "new_days": 3, "already_days": 0, "locked_days": 0})
        self.assertEqual([u["machine_id"] for u in d["unknown"]], ["99"])
        self.assertEqual([n["employee_no"] for n in d["not_linked"]], ["DK-099"])
        self.assertFalse(ClockEvent.objects.exists())

    def test_commit_creates_fingerprint_taps_and_attendance_reads_them(self):
        resp = self.post("1")
        self.assertEqual(resp.data["applied"], {"events": 6, "days": 3})
        ev = ClockEvent.objects.filter(employee=self.sudar, day__date=date(2026, 10, 3)).order_by("occurred_at")
        self.assertEqual([(e.kind, e.source, e.occurred_at.astimezone(WIB).strftime("%H:%M")) for e in ev],
                         [("in", "fingerprint", "07:12"), ("out", "fingerprint", "21:36")])
        night = AttendanceDay.objects.get(employee=self.iqbal)          # the night shift stays on 26 Sep
        self.assertEqual(night.date, date(2026, 9, 26))
        self.assertEqual(night.events.get(kind="out").occurred_at.astimezone(WIB), datetime(2026, 9, 27, 7, tzinfo=WIB))

        daily = self.client.get("/api/hr/attendance/daily/", {"date": "2026-09-26"}).data
        status = {r["employee"]["full_name"]: r["status"] for r in daily["rows"]}
        self.assertEqual((status["Sudarmono"], status["Iqbal"], status["Belum Dihubungkan"]), ("on_time", "on_time", "absent"))
        review = self.client.get("/api/hr/attendance/review/", {"days": 31}).data
        self.assertTrue(any("Lembur 276 menit" in reason for r in review["rows"] for reason in r["review_reasons"]))

        again = self.post("1")
        self.assertEqual((again.data["applied"], again.data["totals"]["already_days"]), ({"events": 0, "days": 0}, 3))

    def test_locked_days_are_left_alone(self):
        AttendanceDay.objects.create(organization=self.org, employee=self.sudar, date=date(2026, 9, 26), is_locked=True)
        resp = self.post("1")
        self.assertEqual((resp.data["totals"]["locked_days"], resp.data["applied"]["events"]), (1, 4))
        self.assertFalse(ClockEvent.objects.filter(employee=self.sudar, day__date=date(2026, 9, 26)).exists())

    def test_files_that_cannot_be_read(self):
        resp = self.post("0", b"\xd0\xcf\x11\xe0", "Absen.xls")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("xlsx", resp.data["message"])
