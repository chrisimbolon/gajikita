"""
G17-7.2 (16 Nov 2026) — "Sudah keluar?" for someone who stopped tapping, days not imported yet are not "absent",
and a Kejadian longer than 7 days asks "Benar?" first. Made-up people.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent, CompanyEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
URL = "/api/hr/attendance/checklist/"


class LeaverTests(APITestCase):
    def setUp(self):
        p = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        p.start()
        self.addCleanup(p.stop)
        self.org = Organization.objects.create(name="PT Contoh Keluar")
        hr = CustomUser.objects.create_user(email="hr@keluar.id", password="pass12345!", full_name="HR Keluar")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                     grace_minutes=5, working_days="123456")
        mk = lambda no, name: Employee.objects.create(organization=self.org, employee_no=no, full_name=name,
                                                      join_date=date(2025, 1, 6), default_shift=shift,
                                                      base_rate=Decimal("3000000"))
        self.workers = [mk(f"W-{i}", f"Pekerja {i}") for i in range(6)]
        self.gone = mk("G-1", "Budi Pergi")

    def work(self, emp, d, taps=(("in", 7, 55), ("out", 17, 0))):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=emp.default_shift)
        for kind, h, m in taps:
            t = datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                      occurred_at=t, received_at=t)

    def fill(self, last, gone_last):
        d = date(2026, 9, 26)
        while d <= last:
            if d.isoweekday() != 7:
                for w in self.workers:
                    self.work(w, d)
                if d <= gone_last:
                    self.work(self.gone, d)
            d += timedelta(days=1)

    def get(self):
        return self.client.get(URL, {"month": "2026-10"}).data

    def test_someone_who_stopped_tapping_is_asked_sudah_keluar(self):
        self.fill(date(2026, 10, 24), gone_last=date(2026, 10, 1))
        c = self.get()
        self.assertEqual([(p["employee"]["full_name"], p["kind"], p["last_tap"], p["missing_after"]) for p in c["no_track"]],
                         [("Budi Pergi", "left", "2026-10-01", 20)])
        self.assertEqual(c["events"]["suggestions"], [])
        self.assertFalse(c["import"]["short"])
        resp = self.client.patch(f"/api/hr/employees/{self.gone.pk}/", {"end_date": "2026-10-01"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.get()["no_track"], [])

    def test_bukan_hides_the_question(self):
        self.fill(date(2026, 10, 24), gone_last=date(2026, 10, 1))
        self.client.post(f"{URL}dismiss/", {"employee": str(self.gone.pk)}, format="json")
        self.assertEqual(self.get()["no_track"], [])

    def test_four_quiet_days_are_not_a_leaver(self):
        self.fill(date(2026, 10, 24), gone_last=date(2026, 10, 19))        # 20-24 Okt: 5 days, 4 would not ask
        self.assertEqual([p["kind"] for p in self.get()["no_track"]], ["left"])
        AttendanceDay.objects.filter(employee=self.gone).delete()
        self.fill_gone(date(2026, 9, 26), date(2026, 10, 20))
        self.assertEqual(self.get()["no_track"], [])

    def fill_gone(self, a, b):
        d = a
        while d <= b:
            if d.isoweekday() != 7:
                self.work(self.gone, d)
            d += timedelta(days=1)

    def test_days_not_imported_yet_are_not_absent(self):
        self.fill(date(2026, 10, 15), gone_last=date(2026, 10, 15))        # file only up to 15 Okt, today 26 Okt
        c = self.get()
        self.assertEqual((c["import"]["until"], c["import"]["short"]), ("2026-10-15", True))
        self.assertEqual(c["events"]["suggestions"], [])                    # 16-24 Okt is not a power cut
        self.assertEqual(c["no_track"], [])                                 # and nobody "left"


class LongEventTests(APITestCase):
    URL = "/api/hr/attendance/events/"

    def setUp(self):
        self.org = Organization.objects.create(name="PT Contoh Panjang")
        hr = CustomUser.objects.create_user(email="hr@panjang.id", password="pass12345!", full_name="HR Panjang")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)

    def body(self, **kw):
        b = {"start": "2026-10-12", "end": "2026-10-14", "kind": "gangguan", "reason": "Mati lampu", "everyone": True}
        b.update(kw)
        return b

    def test_long_range_asks_first(self):
        resp = self.client.post(self.URL, self.body(end="2026-11-14"), format="json")
        self.assertEqual((resp.status_code, resp.data["code"]), (400, "confirm_long"))
        self.assertIn("34 hari", resp.data["message"])
        self.assertFalse(CompanyEvent.objects.exists())
        resp = self.client.post(self.URL, self.body(end="2026-11-14", confirm_long=True), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_up_to_seven_days_saves_straight_away(self):
        self.assertEqual(self.client.post(self.URL, self.body(end="2026-10-18"), format="json").status_code, 201)

    def test_libur_says_libur(self):
        resp = self.client.post(self.URL, self.body(start="2027-03-08", end="2027-03-17", kind="libur",
                                                    reason="Cuti bersama Lebaran"), format="json")
        self.assertEqual(resp.data["code"], "confirm_long")
        self.assertIn("Libur ini 10 hari", resp.data["message"])

    def test_edit_asks_only_when_the_dates_change(self):
        e = self.client.post(self.URL, self.body(end="2026-10-22", confirm_long=True), format="json").data["event"]
        self.assertEqual(self.client.patch(f"{self.URL}{e['id']}/", {"reason": "Mesin rusak"},
                                           format="json").status_code, 200)
        resp = self.client.patch(f"{self.URL}{e['id']}/", {"end": "2026-10-24"}, format="json")
        self.assertEqual(resp.data.get("code"), "confirm_long")
        resp = self.client.patch(f"{self.URL}{e['id']}/", {"end": "2026-10-14"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_over_62_days_keeps_its_own_message(self):
        resp = self.client.post(self.URL, self.body(end="2026-12-31", confirm_long=True), format="json")
        self.assertIn("paling lama 62 hari", resp.data["message"])
