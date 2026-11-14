"""
G17-4 (14 Nov 2026) — HR's notes -> decisions. Made-up people; the notes copy DKCB's October recap:
"UL", "Izin masuk jam 13.00", "Cuti sakit mata", "Cuti 1/2 hari berobat", "Mati lampu", "Belanja alat".
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day
from apps.attendance.models import AttendanceDay, ClockEvent, DayNote
from apps.attendance.note_decisions import CUTI, FORGIVE, HALF, HALF_CUTI, HANDLED, OTHER, UL, classify
from apps.attendance.review import evaluate
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.leave.models import LeaveRequest
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
URL = "/api/hr/attendance/note-decisions/"


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class ClassifyTests(SimpleTestCase):
    def test_dkcb_words(self):
        cases = {
            "UL": UL, "UL 1/2 hari": HALF, "Izin masuk jam 13.00 wib, mau berobat pagi": HALF,
            "Izin pulang cepat ada urusan keluarga mendesak": HALF, "Cuti sakit mata": CUTI, "Cuti": CUTI,
            "Cuti 1/2 hari berobat": HALF_CUTI, "Mati lampu": FORGIVE, "Finger in tidak terbaca": FORGIVE,
            "Belanja alat lori fuso dll": HANDLED, "Kerja di Lobam": HANDLED, "Sudah tidak join": HANDLED,
            "Ketemu klien": OTHER, "": OTHER,
        }
        for text, group in cases.items():
            self.assertEqual(classify("", text), group, text)
        self.assertEqual(classify("UL", ""), UL)                                        # the colour code alone


class HalfDayLeaveRuleTests(SimpleTestCase):
    def test_a_half_day_permit_is_not_late_or_early(self):
        day, shift = date(2026, 10, 5), ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
        now = at(date(2026, 10, 20), 12)
        late = evaluate_day(day, shift, [Tap("in", at(day, 12, 37)), Tap("out", at(day, 17, 1))], now, WIB)
        self.assertEqual((late.status, late.late_minutes), (Status.LATE, 277))
        r = evaluate_day(day, shift, [Tap("in", at(day, 12, 37)), Tap("out", at(day, 17, 1))], now, WIB,
                         half_leave="unpaid")
        self.assertEqual((r.status, r.half_leave, r.needs_review), (Status.ON_TIME, "unpaid", False))
        early = evaluate_day(day, shift, [Tap("in", at(day, 7, 1)), Tap("out", at(day, 12, 4))], now, WIB,
                             half_leave="unpaid")
        self.assertEqual((early.status, early.early_minutes, early.needs_review), (Status.ON_TIME, 296, False))
        none = evaluate_day(day, shift, [], now, WIB, half_leave="unpaid")
        self.assertEqual((none.status, none.half_leave), (Status.ON_TIME, "unpaid"))


class NoteDecisionApiTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Contoh Catatan")
        hr = CustomUser.objects.create_user(email="hr@catatan.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        mk = lambda no, name: Employee.objects.create(organization=self.org, employee_no=no, full_name=name,
                                                      join_date=date(2020, 1, 6), default_shift=self.shift,
                                                      base_rate=Decimal("3000000"), bpjs_tk_enrolled=False)
        self.eko, self.togar, self.vinsen = mk("C-1", "Eko Contoh"), mk("C-2", "Togar Contoh"), mk("C-3", "Vinsen Contoh")
        self.note(self.eko, date(2026, 10, 6), "UL", code="UL")
        self.note(self.togar, date(2026, 10, 5), "Izin masuk jam 13.00 wib, mau berobat pagi")
        self.taps(self.togar, date(2026, 10, 5), (12, 37), (17, 1))
        self.note(self.vinsen, date(2026, 10, 7), "Cuti sakit mata")
        self.note(self.vinsen, date(2026, 10, 8), "Mati lampu")
        self.note(self.eko, date(2026, 10, 9), "Belanja alat")

    def note(self, emp, d, text, code=""):
        DayNote.objects.create(organization=self.org, employee=emp, date=d, text=text, code=code)

    def taps(self, emp, d, *times):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift)
        for kind, (h, m) in zip(("in", "out"), times):
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                      occurred_at=at(d, h, m), received_at=at(d, h, m))
        return day

    def group(self, body, key):
        return next(g for g in body["groups"] if g["key"] == key)

    def apply(self, group, *items):
        return self.client.post(f"{URL}apply/", {"month": "2026-10", "group": group, "items": [
            {"employee": str(e.pk), "date": d.isoformat(), "choice": c} for e, d, c in items]}, format="json")

    def test_groups_and_states(self):
        body = self.client.get(URL, {"month": "2026-10"}).data
        self.assertEqual(body["total"], 5)
        self.assertEqual([r["employee"]["full_name"] for r in self.group(body, UL)["rows"]], ["Eko Contoh"])
        half = self.group(body, HALF)["rows"][0]
        self.assertEqual((half["taps"], half["state"]), ("12:37 – 17:01", "todo"))
        self.assertEqual(self.group(body, CUTI)["rows"][0]["balance_left"], 12)
        self.assertEqual(self.group(body, FORGIVE)["rows"][0]["state"], "no_taps")     # absent, not "done"
        self.assertEqual(self.group(body, HANDLED)["rows"][0]["state"], "info")

    def test_ul_becomes_unpaid_leave(self):
        resp = self.apply(UL, (self.eko, date(2026, 10, 6), ""))
        self.assertEqual((resp.data["applied"], resp.data["errors"]), (1, []))
        lv = LeaveRequest.objects.get(employee=self.eko)
        self.assertEqual((lv.kind, lv.status, lv.start_date), ("unpaid", "approved", date(2026, 10, 6)))
        self.assertEqual(self.group(resp.data, UL)["rows"][0]["state"], "done")
        self.assertEqual(self.apply(UL, (self.eko, date(2026, 10, 6), "")).data["applied"], 0)   # not twice

    def test_ul_on_a_day_with_taps_sets_the_taps_aside(self):
        day = self.taps(self.eko, date(2026, 10, 6), (8, 30), (17, 0))                  # tapped, yet the note says UL
        self.assertEqual(self.apply(UL, (self.eko, date(2026, 10, 6), "")).data["applied"], 1)
        day.refresh_from_db()
        self.assertEqual(day.decision, "rejected")
        r = evaluate(day)
        self.assertEqual((r.status, r.leave), (Status.LEAVE, "Izin tanpa upah"))

    def test_a_half_day_permit_is_decided(self):
        self.assertEqual(self.apply(HALF, (self.togar, date(2026, 10, 5), "")).data["applied"], 1)
        day = AttendanceDay.objects.get(employee=self.togar, date=date(2026, 10, 5))
        self.assertEqual((day.half_day_leave, day.decision, day.waive_late), ("unpaid", "approved", True))
        r = evaluate(day)
        self.assertEqual((r.half_leave, Status.LATE in r.tags), ("unpaid", False))

    def test_cuti_needs_a_choice_each_time(self):
        resp = self.apply(CUTI, (self.vinsen, date(2026, 10, 7), ""))
        self.assertEqual((resp.data["applied"], resp.data["errors"][0]["message"]), (0, "Pilih dulu untuk baris ini."))
        self.assertEqual(self.apply(CUTI, (self.vinsen, date(2026, 10, 7), "unpaid")).data["applied"], 1)
        self.assertEqual(LeaveRequest.objects.get(employee=self.vinsen).kind, "unpaid")

    def test_a_power_cut_event_makes_a_no_tap_day_done(self):
        self.client.post("/api/hr/attendance/events/", {"start": "2026-10-08", "end": "2026-10-08", "kind": "gangguan",
                                                        "reason": "Mati lampu", "everyone": True}, format="json")
        body = self.client.get(URL, {"month": "2026-10"}).data
        self.assertEqual(self.group(body, FORGIVE)["rows"][0]["state"], "done")

    def test_forgive_needs_taps_and_a_wrong_group_is_refused(self):
        resp = self.apply(FORGIVE, (self.vinsen, date(2026, 10, 8), ""))
        self.assertIn("Tidak ada tap", resp.data["errors"][0]["message"])
        resp = self.apply(UL, (self.togar, date(2026, 10, 5), ""))
        self.assertEqual(resp.data["errors"][0]["message"], "Catatan tidak ditemukan di kelompok ini.")


class HalfDayPayrollTests(APITestCase):
    RUNS = "/api/hr/payroll/runs/"

    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Contoh Izin")
        hr = CustomUser.objects.create_user(email="hr@izin.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                     grace_minutes=5, working_days="123456")
        PayrollSettings.objects.create(organization=self.org, late_fine_per_minute=Decimal("500"), late_tolerance_minutes=5)
        emp = Employee.objects.create(organization=self.org, employee_no="I-1", full_name="Togar Contoh",
                                      join_date=date(2025, 1, 6), default_shift=shift, base_rate=Decimal("3000000"),
                                      bpjs_tk_enrolled=False)
        start, permit = date(2026, 9, 26), date(2026, 10, 5)
        for i in range(30):
            d = start + timedelta(days=i)
            if d.isoweekday() == 7:
                continue
            day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=shift,
                                               half_day_leave="unpaid" if d == permit else "",
                                               decision="approved" if d == permit else "", waive_late=d == permit)
            first = (12, 37) if d == permit else (7, 55)
            for kind, (h, m) in (("in", first), ("out", (17, 0))):
                ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, source="fingerprint",
                                          occurred_at=at(d, h, m), received_at=at(d, h, m))

    def test_half_a_day_unpaid_and_no_late_fine(self):
        run = self.client.post(self.RUNS, {"month": "2026-10"}, format="json").data["run"]
        rows = self.client.get(f"{self.RUNS}{run['id']}/").data["rows"]
        line = self.client.get(f"{self.RUNS}{run['id']}/lines/{rows[0]['id']}/").data["line"]
        a = line["auto"]
        self.assertEqual((a["permit_half_days"], a["unpaid_days"], a["late_minutes"], a["present_days"]), (1, 0.5, 0, 25))
        self.assertIn("Izin ½ hari tanpa upah 1 hari: dipotong ½ hari per hari.", line["result"]["warnings"])
