"""
G17-7 (16 Nov 2026) — "Siap gajian?": late / early / one tap are facts fined by the rules, overtime and patterns
are the questions. Made-up people; the shapes copy DKCB's October (a power cut on 12 Okt, one-tap days, late days).
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.attendance import checklist_rules as R
from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day
from apps.attendance.models import AttendanceDay, ClockEvent, CompanyEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
URL, BULK, UNDO = "/api/hr/attendance/checklist/", "/api/hr/attendance/review/bulk/", "/api/hr/attendance/review/undo/"
CUT, LATE, OT, ONE = date(2026, 10, 12), date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8)


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class RuleTests(SimpleTestCase):
    def test_rules(self):
        self.assertEqual((R.late_charge(30, 0, 5), R.late_charge(3, 10, 5), R.late_charge(0, 0, 5)), (25, 10, 0))
        self.assertEqual((R.is_cluster(18, 26), R.is_cluster(4, 5), R.is_cluster(6, 26)), (True, False, False))
        d = date
        self.assertEqual(R.group_dates([d(2026, 10, 14), d(2026, 10, 12), d(2026, 10, 13), d(2026, 10, 20)]),
                         [(d(2026, 10, 12), d(2026, 10, 14)), (d(2026, 10, 20), d(2026, 10, 20))])
        self.assertEqual(R.group_dates([d(2026, 10, 17), d(2026, 10, 19)], gap_ok=lambda x: x.isoweekday() == 7),
                         [(d(2026, 10, 17), d(2026, 10, 19))])

    def test_forgiving_a_day_forgives_its_early_leave_too(self):
        shift = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
        taps = [Tap("in", at(OT, 7, 55)), Tap("out", at(OT, 15, 0))]
        now = datetime(2026, 10, 20, tzinfo=WIB)
        self.assertIn(Status.EARLY_OUT, evaluate_day(OT, shift, taps, now, WIB).tags)
        self.assertNotIn(Status.EARLY_OUT, evaluate_day(OT, shift, taps, now, WIB, waive_late=True).tags)


class ChecklistTests(APITestCase):
    def setUp(self):
        p = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        p.start()
        self.addCleanup(p.stop)
        self.org = Organization.objects.create(name="PT Contoh Gajian")
        hr = CustomUser.objects.create_user(email="hr@gajian.id", password="pass12345!", full_name="HR Gajian")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        PayrollSettings.objects.create(organization=self.org, late_fine_per_minute=Decimal("500"),
                                       late_tolerance_minutes=5, single_tap_half_day=True)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        self.people = {}
        for i, name in enumerate(["Andi", "Budi", "Citra", "Dewi", "Eko", "Fajar"]):
            self.people[name] = Employee.objects.create(organization=self.org, employee_no=f"G-{i}", full_name=f"{name} Contoh",
                                                        join_date=date(2025, 1, 6), default_shift=self.shift,
                                                        base_rate=Decimal("3000000"))
        self.days = {}
        d = date(2026, 9, 26)
        while d <= date(2026, 10, 25):
            if d.isoweekday() != 7 and d != CUT:
                for name, emp in self.people.items():
                    taps = [("in", 7, 55), ("out", 17, 0)]
                    if (name, d) == ("Andi", LATE):
                        taps = [("in", 8, 30), ("out", 17, 0)]
                    elif (name, d) == ("Budi", OT):
                        taps = [("in", 7, 55), ("out", 20, 0)]
                    elif (name, d) == ("Citra", ONE):
                        taps = [("in", 7, 55)]
                    self.days[(name, d)] = self.work(emp, d, taps)
            d += timedelta(days=1)

    def work(self, emp, d, taps):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift)
        for kind, h, m in taps:
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                      occurred_at=at(d, h, m), received_at=at(d, h, m))
        return day

    def get(self):
        resp = self.client.get(URL, {"month": "2026-10"})
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data

    def test_the_steps(self):
        c = self.get()
        self.assertEqual((c["import"]["people"], c["import"]["employees"]), (6, 6))
        self.assertEqual([(s["start"], s["end"], s["people"]) for s in c["events"]["suggestions"]], [("2026-10-12", "2026-10-12", 6)])
        ot = c["overtime"]["people"]
        self.assertEqual((len(ot), ot[0]["employee"]["full_name"], ot[0]["days"][0]["proposed"]), (1, "Budi Contoh", 180))
        self.assertEqual((c["missing"]["cut_days"], c["missing"]["rupiah"]), (1, 50000))       # 3.000.000 / 30 / 2
        late = c["late"]["people"]
        self.assertEqual((len(late), late[0]["minutes"], late[0]["rupiah"], c["late"]["rupiah"]), (1, 25, 12500, 12500))

    def test_forgive_and_undo(self):
        ids = [str(self.days[("Andi", LATE)].pk), str(self.days[("Citra", ONE)].pk)]
        r = self.client.post(BULK, {"action": "forgive", "ids": ids, "note": "izin atasan", "waive_late": False}, format="json").data
        self.assertEqual(r["decided"], 2)
        day = AttendanceDay.objects.get(pk=ids[0])
        self.assertEqual((day.waive_late, day.decision), (True, "approved"))
        c = self.get()
        self.assertEqual((c["late"]["count"], c["late"]["rupiah"], c["late"]["people"][0]["days"][0]["forgiven"]), (0, 0, True))
        self.assertEqual(c["missing"]["cut_days"], 0)
        self.assertEqual(self.client.post(UNDO, {"batch": r["batch"]}, format="json").data["undone"], 2)
        self.assertEqual(self.get()["late"]["count"], 1)

    def test_forgiving_keeps_open_overtime_open(self):
        day = self.days[("Budi", OT)]
        self.client.post(BULK, {"action": "forgive", "ids": [str(day.pk)], "note": "", "waive_late": False}, format="json")
        day.refresh_from_db()
        self.assertEqual((day.waive_late, day.decision), (True, ""))
        self.assertEqual(self.get()["overtime"]["open_days"], 1)

    def test_a_suggestion_goes_away(self):
        self.assertEqual(self.client.post(f"{URL}dismiss/", {"start": "2026-10-12", "end": "2026-10-12"}, format="json").status_code, 200)
        self.assertEqual(self.get()["events"]["suggestions"], [])

    def test_a_kejadian_covers_it(self):
        CompanyEvent.objects.create(organization=self.org, start=CUT, end=CUT, kind="gangguan", reason="Mati lampu", everyone=True)
        c = self.get()
        self.assertEqual((c["events"]["suggestions"], len(c["events"]["existing"])), ([], 1))
