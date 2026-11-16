"""
G17-7.1 (16 Nov 2026) — people who never tap completely are asked "Tidak wajib absen?" and don't make every date
look like a power cut (seegaji.com, 26 Sep: 12 people "missing"). Made-up people.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
URL = "/api/hr/attendance/checklist/"
CUT = date(2026, 10, 12)


class NoTrackTests(APITestCase):
    def setUp(self):
        p = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        p.start()
        self.addCleanup(p.stop)
        self.org = Organization.objects.create(name="PT Contoh Tap")
        hr = CustomUser.objects.create_user(email="hr@tap.id", password="pass12345!", full_name="HR Tap")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                     grace_minutes=5, working_days="123456")
        mk = lambda no, name: Employee.objects.create(organization=self.org, employee_no=no, full_name=name,
                                                      join_date=date(2025, 1, 6), default_shift=shift,
                                                      base_rate=Decimal("3000000"))
        self.never = [mk(f"N-{i}", f"Jauh {i}") for i in range(4)]          # sales, off-site: never tap
        self.guard = mk("S-1", "Satpam Contoh")                              # night shift: one tap a day
        workers = [mk(f"W-{i}", f"Pekerja {i}") for i in range(6)]
        d = date(2026, 9, 26)
        while d <= date(2026, 10, 25):
            if d.isoweekday() != 7 and d != CUT:
                for w in workers:
                    self.work(w, d, [("in", 7, 55), ("out", 17, 0)])
                self.work(self.guard, d, [("in", 7, 2)])
            d += timedelta(days=1)

    def work(self, emp, d, taps):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=emp.default_shift)
        for kind, h, m in taps:
            t = datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                      occurred_at=t, received_at=t)

    def get(self):
        return self.client.get(URL, {"month": "2026-10"}).data

    def test_never_tapping_people_are_asked_and_kept_out_of_the_pattern(self):
        c = self.get()
        self.assertEqual(sorted(p["employee"]["full_name"] for p in c["no_track"]),
                         ["Jauh 0", "Jauh 1", "Jauh 2", "Jauh 3", "Satpam Contoh"])
        guard = next(p for p in c["no_track"] if p["employee"]["full_name"] == "Satpam Contoh")
        self.assertEqual((guard["complete"], guard["start"]), (0, "2026-09-26"))
        self.assertEqual([(s["start"], s["people"], s["absent"]) for s in c["events"]["suggestions"]],
                         [("2026-10-12", 6, 6)])                     # only the real power cut, only the workers

    def test_answering_removes_the_question(self):
        self.client.post(f"{URL}dismiss/", {"employee": str(self.guard.pk)}, format="json")
        resp = self.client.post(f"/api/hr/employees/{self.never[0].pk}/attendance-exemptions/",
                                {"start": "2026-09-26", "reason": "Sales"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        names = [p["employee"]["full_name"] for p in self.get()["no_track"]]
        self.assertEqual(names, ["Jauh 1", "Jauh 2", "Jauh 3"])
