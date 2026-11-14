"""
G17-2 (14 Nov 2026) — company events ("Kejadian"): a power cut or a holiday, entered once.
Made-up people; the days copy R1 (DKCB, October 2026): the power went out 12-14 Okt.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.attendance.company_events import DISRUPTION, HOLIDAY, Event, event_for
from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day
from apps.attendance.models import AttendanceDay, ClockEvent, CompanyEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings, PayRun
from apps.sites.models import Shift, Site

WIB = ZoneInfo("Asia/Jakarta")
MON, WED, THU = date(2026, 10, 12), date(2026, 10, 14), date(2026, 10, 15)
PAGI = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
LATER = datetime(2026, 10, 20, 12, tzinfo=WIB)
CUT = (DISRUPTION, "Mati lampu")


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


def ev(*taps, day=WED, **kw):
    return evaluate_day(day, PAGI, list(taps), LATER, WIB, **kw)


class EventRuleTests(SimpleTestCase):
    def test_who_is_covered(self):
        plant, office = "site-plant", "site-office"
        everyone = Event(MON, WED, DISRUPTION, "Mati lampu")
        plant_only = Event(MON, WED, DISRUPTION, "Mati lampu", everyone=False, site_ids=frozenset({plant}))
        one = Event(MON, MON, DISRUPTION, "Mesin rusak", everyone=False, employee_ids=frozenset({"budi"}))
        self.assertEqual(event_for([everyone], "andi", office, WED), CUT)
        self.assertIsNone(event_for([everyone], "andi", office, THU))                 # outside the dates
        self.assertEqual(event_for([plant_only], "andi", plant, MON), CUT)
        self.assertIsNone(event_for([plant_only], "andi", office, MON))
        self.assertIsNone(event_for([plant_only], "andi", None, MON))                   # no main location
        self.assertEqual(event_for([one], "budi", office, MON), (DISRUPTION, "Mesin rusak"))
        self.assertIsNone(event_for([one], "andi", office, MON))

    def test_a_holiday_wins(self):
        events = [Event(MON, WED, DISRUPTION, "Mati lampu"), Event(WED, WED, HOLIDAY, "Libur perusahaan")]
        self.assertEqual(event_for(events, "andi", None, WED), (HOLIDAY, "Libur perusahaan"))


class DisruptedDayTests(SimpleTestCase):
    def test_no_taps_is_present_not_absent(self):
        r = ev(day=MON, event=CUT)
        self.assertEqual((r.status, r.needs_review, r.disrupted), (Status.ON_TIME, False, True))
        self.assertEqual(r.note, "Gangguan absen: Mati lampu")
        self.assertEqual(ev(day=MON).status, Status.ABSENT)                             # without the event

    def test_one_tap_is_not_cut_or_late(self):
        afternoon = ev(Tap("in", at(WED, 17, 12)), event=CUT)                           # Hadi
        morning = ev(Tap("in", at(WED, 8, 40)), event=CUT)
        for r in (afternoon, morning):
            self.assertEqual((r.late_minutes, r.half_day, r.needs_review, r.status), (0, False, False, Status.ON_TIME))

    def test_overtime_from_a_real_late_tap_still_counts(self):
        r = ev(Tap("out", at(WED, 22, 16)), event=CUT)                                 # Arief: 5.5 h in the book
        self.assertEqual((r.overtime_proposed_minutes, r.review_reasons), (316, ["Lembur 316 menit menunggu persetujuan"]))

    def test_leave_and_rejection_still_win(self):
        self.assertEqual(ev(day=MON, event=CUT, leave="Sakit").status, Status.LEAVE)
        r = ev(Tap("in", at(WED, 8)), Tap("out", at(WED, 17)), event=CUT, decision="rejected")
        self.assertEqual((r.status, r.disrupted), (Status.REJECTED, False))

    def test_a_day_off_stays_a_day_off(self):
        sunday = date(2026, 10, 18)
        r = ev(day=sunday, event=CUT)
        self.assertEqual((r.status, r.disrupted, r.event), (Status.DAY_OFF, False, ""))


class HolidayTests(SimpleTestCase):
    def test_a_working_day_becomes_a_day_off(self):
        r = ev(day=THU, event=(HOLIDAY, "Libur perusahaan"))
        self.assertEqual((r.status, r.holiday, r.note), (Status.DAY_OFF, True, "Libur: Libur perusahaan"))

    def test_working_on_a_holiday_is_rest_day_work(self):
        r = ev(Tap("in", at(THU, 8)), Tap("out", at(THU, 12)), day=THU, event=(HOLIDAY, "Libur perusahaan"))
        self.assertEqual((r.status, r.overtime_proposed_minutes, r.late_minutes), (Status.DAY_OFF_WORK, 240, 0))


class EventApiTests(APITestCase):
    URL = "/api/hr/attendance/events/"

    def setUp(self):
        self.org = Organization.objects.create(name="PT Contoh Kejadian")
        self.hr = CustomUser.objects.create_user(email="hr@kejadian.id", password="pass12345!", full_name="HR Kejadian")
        OrganizationMembership.objects.create(organization=self.org, user=self.hr, role="hr")
        self.client.force_authenticate(self.hr)
        self.plant = Site.objects.create(organization=self.org, name="Plant")
        self.emp = Employee.objects.create(organization=self.org, employee_no="K-1", full_name="Andi Contoh",
                                           join_date=date(2025, 1, 6), base_rate=Decimal("3000000"))
        other = Organization.objects.create(name="PT Lain")
        self.foreign = Site.objects.create(organization=other, name="Bukan punya kita")

    def body(self, **kw):
        b = {"start": "2026-10-12", "end": "2026-10-14", "kind": "gangguan", "reason": "Mati lampu", "everyone": True}
        b.update(kw)
        return b

    def test_create_list_update_delete(self):
        resp = self.client.post(self.URL, self.body(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        e = resp.data["event"]
        self.assertEqual((e["days"], e["who"], e["kind_label"]), (3, "Semua karyawan", "Gangguan absen"))
        resp = self.client.patch(f"{self.URL}{e['id']}/", {"everyone": False, "site_ids": [str(self.plant.pk)],
                                                           "employee_ids": [str(self.emp.pk)]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["event"]["who"], "Lokasi Plant · Andi Contoh")
        self.assertEqual(len(self.client.get(self.URL).data["events"]), 1)
        self.assertEqual(self.client.delete(f"{self.URL}{e['id']}/").status_code, 200)
        self.assertFalse(CompanyEvent.objects.exists())

    def test_plain_refusals(self):
        cases = [
            (self.body(end="2026-10-11"), "Tanggal selesai tidak boleh sebelum"),
            (self.body(end="2026-12-31"), "paling lama 62 hari"),
            (self.body(everyone=False), "Pilih minimal satu lokasi atau satu karyawan"),
            (self.body(everyone=False, site_ids=[str(self.foreign.pk)]), "tidak ditemukan di perusahaan ini"),
        ]
        for body, words in cases:
            resp = self.client.post(self.URL, body, format="json")
            self.assertEqual(resp.status_code, 400, body)
            self.assertIn(words, resp.data["message"])
        self.assertEqual(self.client.post(self.URL, self.body(reason="x"), format="json").status_code, 400)

    def test_a_locked_payroll_is_never_touched(self):
        PayRun.objects.create(organization=self.org, name="Payroll Oktober 2026", period_start=date(2026, 9, 26),
                              period_end=date(2026, 10, 25), status=PayRun.Status.LOCKED)
        resp = self.client.post(self.URL, self.body(), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("sudah dikunci", resp.data["message"])
        self.assertEqual(self.client.post(self.URL, self.body(start="2026-10-27", end="2026-10-27"),
                                          format="json").status_code, 201)


class EventPayrollTests(APITestCase):
    RUNS = "/api/hr/payroll/runs/"

    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Contoh Listrik")
        hr = CustomUser.objects.create_user(email="hr@listrik.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                     grace_minutes=5, working_days="123456")
        PayrollSettings.objects.create(organization=self.org, late_fine_per_minute=Decimal("500"),
                                       late_tolerance_minutes=5, single_tap_half_day=True)
        self.emp = Employee.objects.create(organization=self.org, employee_no="L-1", full_name="Hadi Contoh",
                                           join_date=date(2025, 1, 6), default_shift=shift,
                                           base_rate=Decimal("3000000"), bpjs_tk_enrolled=False)
        start = date(2026, 9, 26)
        for i in range(30):
            d = start + timedelta(days=i)
            if d.isoweekday() == 7 or d in (MON, THU):          # 12 Okt: no taps (power cut); 15 Okt: see the test
                continue
            taps = [("in", 17, 12)] if d == WED else [("in", 7, 55), ("out", 17, 0)]
            day = AttendanceDay.objects.create(organization=self.org, employee=self.emp, date=d, shift=shift)
            for kind, h, m in taps:
                ClockEvent.objects.create(organization=self.org, day=day, employee=self.emp, kind=kind,
                                          source="fingerprint", occurred_at=at(d, h, m), received_at=at(d, h, m))

    def auto(self):
        run = self.client.post(self.RUNS, {"month": "2026-10"}, format="json").data["run"]
        rows = self.client.get(f"{self.RUNS}{run['id']}/").data["rows"]
        line = self.client.get(f"{self.RUNS}{run['id']}/lines/{rows[0]['id']}/").data["line"]
        return line["auto"], line["result"]["warnings"]

    def add(self, **kw):
        body = {"start": "2026-10-12", "end": "2026-10-14", "kind": "gangguan", "reason": "Mati lampu", "everyone": True}
        body.update(kw)
        self.assertEqual(self.client.post("/api/hr/attendance/events/", body, format="json").status_code, 201)

    def test_without_events_the_power_cut_costs_pay(self):
        a, _ = self.auto()
        self.assertEqual((a["absent_days"], a["half_days"], a["unpaid_days"]), (2, 1, 2.5))      # 12 + 15 Okt, ½ 14 Okt

    def test_a_disruption_makes_the_days_whole(self):
        self.add()
        a, warnings = self.auto()
        self.assertEqual((a["absent_days"], a["half_days"], a["disrupted_days"]), (1, 0, 3))    # only 15 Okt left
        self.assertIn("Gangguan absen: Mati lampu (3 hari): dihitung hadir penuh, tanpa potongan terlambat atau ½ hari.",
                      warnings)

    def test_a_holiday_is_not_a_working_day(self):
        self.add(start="2026-10-15", end="2026-10-15", kind="libur", reason="Libur perusahaan")
        a, warnings = self.auto()
        self.assertEqual((a["working_days"], a["absent_days"], a["holiday_days"]), (24, 1, 1))  # 12 Okt still absent
        self.assertIn("Libur: Libur perusahaan (1 hari): bukan hari kerja.", warnings)
