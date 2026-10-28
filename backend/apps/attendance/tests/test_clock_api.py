"""
G1 (26 Oct 2026) — POST /api/attendance/clock/ and GET /api/attendance/today/.
A tap is never refused: it is recorded with flags for HR.
"""
import io
import shutil
import tempfile
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization
from apps.sites.models import Shift, Site
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

CLOCK = "/api/attendance/clock/"
TODAY = "/api/attendance/today/"
WIB = ZoneInfo("Asia/Jakarta")
M_PER_DEG_LAT = 111_195.08
PIN = (Decimal("1.130000"), Decimal("104.050000"))


def north(metres):
    return float(PIN[0]) + metres / M_PER_DEG_LAT, float(PIN[1])


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=WIB)


def tiny_jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "JPEG")
    return SimpleUploadedFile("selfie.jpg", buf.getvalue(), content_type="image/jpeg")


class ClockApiTests(APITestCase):
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
        self.org = Organization.objects.create(name="PT Bangun Wira Indah")
        self.yard = Site.objects.create(organization=self.org, name="Workshop Tanjung Uban")
        self.yard.move_pin(*PIN, radius_m=150, valid_from=at(2026, 1, 1, 0))
        self.day_shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17))
        self.user = CustomUser.objects.create_user(email="budi@test.id", password="pass12345!", full_name="Budi")
        self.emp = Employee.objects.create(
            organization=self.org, employee_no="BWI-001", full_name="Budi Santoso", join_date=date(2025, 1, 6),
            default_site=self.yard, default_shift=self.day_shift, user=self.user,
        )
        self.client.force_authenticate(self.user)

    def _clock(self, kind, when, metres=50, **extra):
        lat, lng = north(metres)
        data = {"kind": kind, "latitude": lat, "longitude": lng, "accuracy": 12, "selfie": tiny_jpeg()}
        data.update(extra)
        data = {k: v for k, v in data.items() if v is not None}
        with mock.patch("django.utils.timezone.now", return_value=when):
            return self.client.post(CLOCK, data, format="multipart")

    # ── the basics ──
    def test_clock_in_inside_the_site(self):
        resp = self._clock("in", at(2026, 10, 27, 7, 55))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        ev = resp.data["event"]
        self.assertEqual((ev["date"], ev["site"]["name"], ev["distance_m"], ev["flags"]),
                         ("2026-10-27", "Workshop Tanjung Uban", 50, []))
        self.assertTrue(ev["has_selfie"])
        self.assertEqual(resp.data["message"], "Masuk tercatat.")

    def test_outside_the_site_is_recorded_with_a_flag(self):
        resp = self._clock("in", at(2026, 10, 27, 7, 55), metres=400)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["event"]["flags"], ["outside_site"])
        self.assertIn("Di luar lokasi (400 m)", resp.data["message"])

    def test_no_selfie_is_flagged(self):
        resp = self._clock("in", at(2026, 10, 27, 7, 55), selfie=None)
        self.assertEqual(resp.data["event"]["flags"], ["no_selfie"])

    def test_clock_out_closes_the_same_day(self):
        self._clock("in", at(2026, 10, 27, 7, 55))
        resp = self._clock("out", at(2026, 10, 27, 17, 5))
        self.assertEqual((resp.data["event"]["date"], resp.data["event"]["flags"]), ("2026-10-27", []))
        self.assertEqual(AttendanceDay.objects.count(), 1)
        self.assertEqual(ClockEvent.objects.count(), 2)

    def test_clock_out_without_clock_in_is_flagged(self):
        resp = self._clock("out", at(2026, 10, 27, 17, 5))
        self.assertEqual(resp.data["event"]["flags"], ["no_clock_in"])

    def test_second_clock_in_is_flagged(self):
        self._clock("in", at(2026, 10, 27, 7, 55))
        resp = self._clock("in", at(2026, 10, 27, 8, 30))
        self.assertEqual(resp.data["event"]["flags"], ["already_in"])
        self.assertEqual(AttendanceDay.objects.count(), 1)

    # ── night shift ──
    def test_night_shift_clock_out_lands_on_the_day_it_started(self):
        night = Shift.objects.create(organization=self.org, name="Malam", start_time=time(22), end_time=time(6))
        Employee.objects.filter(pk=self.emp.pk).update(default_shift=night)
        self._clock("in", at(2026, 10, 27, 21, 50))
        resp = self._clock("out", at(2026, 10, 28, 6, 10))
        self.assertEqual(resp.data["event"]["date"], "2026-10-27")

    def test_night_shift_late_clock_in_after_midnight(self):
        night = Shift.objects.create(organization=self.org, name="Malam", start_time=time(22), end_time=time(6))
        Employee.objects.filter(pk=self.emp.pk).update(default_shift=night)
        resp = self._clock("in", at(2026, 10, 28, 0, 20))
        self.assertEqual(resp.data["event"]["date"], "2026-10-27")

    # ── offline and retries ──
    def test_retry_with_the_same_client_id_does_not_duplicate(self):
        cid = str(uuid.uuid4())
        first = self._clock("in", at(2026, 10, 27, 7, 55), client_id=cid)
        again = self._clock("in", at(2026, 10, 27, 7, 56), client_id=cid)
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.data["event"]["id"], again.data["event"]["id"])
        self.assertEqual(ClockEvent.objects.count(), 1)

    def test_offline_tap_keeps_its_phone_time(self):
        resp = self._clock("in", at(2026, 10, 27, 10, 0), queued="true",
                           phone_time=at(2026, 10, 27, 7, 50).isoformat())
        ev = ClockEvent.objects.get(pk=resp.data["event"]["id"])
        self.assertEqual(ev.occurred_at, at(2026, 10, 27, 7, 50))
        self.assertEqual(ev.received_at, at(2026, 10, 27, 10, 0))
        self.assertEqual(ev.flags, ["offline"])

    def test_phone_clock_wrong_uses_server_time(self):
        resp = self._clock("in", at(2026, 10, 27, 8, 30), phone_time=at(2026, 10, 27, 7, 50).isoformat())
        ev = ClockEvent.objects.get(pk=resp.data["event"]["id"])
        self.assertEqual((ev.occurred_at, ev.flags), (at(2026, 10, 27, 8, 30), ["time_gap"]))

    # ── history and isolation ──
    def test_moving_the_pin_later_does_not_rewrite_old_taps(self):
        resp = self._clock("in", at(2026, 10, 27, 7, 55))
        old_pin = ClockEvent.objects.get(pk=resp.data["event"]["id"]).site_location
        self.yard.move_pin(Decimal("1.200000"), Decimal("104.100000"), valid_from=at(2026, 10, 28, 0))
        ev = ClockEvent.objects.get(pk=resp.data["event"]["id"])
        self.assertEqual((ev.site_location, ev.distance_m), (old_pin, 50))

    def test_cannot_clock_in_at_another_companys_site(self):
        other = Organization.objects.create(name="PT Lain")
        theirs = Site.objects.create(organization=other, name="Pabrik Lain")
        resp = self._clock("in", at(2026, 10, 27, 7, 55), site_id=str(theirs.id))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ClockEvent.objects.count(), 0)

    def test_login_without_an_employee_gets_403(self):
        stranger = CustomUser.objects.create_user(email="x@test.id", password="pass12345!", full_name="X")
        self.client.force_authenticate(stranger)
        self.assertEqual(self._clock("in", at(2026, 10, 27, 7, 55)).status_code, status.HTTP_403_FORBIDDEN)

    def test_resigned_employee_gets_403(self):
        Employee.objects.filter(pk=self.emp.pk).update(status=Employee.Status.RESIGNED)
        self.assertEqual(self._clock("in", at(2026, 10, 27, 7, 55)).status_code, status.HTTP_403_FORBIDDEN)

    def test_logged_out_gets_401(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(CLOCK, {"kind": "in"}).status_code, status.HTTP_401_UNAUTHORIZED)

    # ── today ──
    def test_today_lists_my_sites_and_taps(self):
        self._clock("in", at(2026, 10, 27, 7, 55))
        with mock.patch("django.utils.timezone.now", return_value=at(2026, 10, 27, 12, 0)):
            resp = self.client.get(TODAY)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["clocked_in"])
        self.assertEqual(resp.data["sites"][0]["radius_m"], 150)
        self.assertEqual([e["kind"] for e in resp.data["events"]], ["in"])
        self.assertEqual(resp.data["shift"], {"name": "Pagi", "start": "08:00", "end": "17:00"})
