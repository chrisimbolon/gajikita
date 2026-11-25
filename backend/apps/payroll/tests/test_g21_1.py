"""
G21-1 (25 Nov 2026) — Ringkasan Karyawan: one person, one period. Every day with its colour, chips, rupiah and the
reasons ("Kenapa begini"); the money from the payroll line, and whether the line still matches. Read-only.
Made-up people (test_payrun's PT Beton Bintan), plus Rudi, shaped like the 14 Okt power cut (made-up name and salary).
"""
from datetime import date, time

from django.test import SimpleTestCase

from apps.attendance.models import AttendanceDay
from apps.employees.models import Employee
from apps.organizations.models import Organization
from apps.payroll.models import PayrollSettings
from apps.payroll.tests import test_payrun as base

URL = "/api/hr/attendance/ringkasan/"


class RingkasanTests(base.PayRunTests):
    def get(self, emp, month="2026-10", status=200):
        r = self.client.get(URL, {"employee": str(emp.id) if hasattr(emp, "id") else emp, "month": month})
        self.assertEqual(r.status_code, status, getattr(r, "data", None))
        return r.data

    def day(self, data, iso):
        return next(d for d in data["days"] if d["date"] == iso)

    def test_one_person_one_period(self):
        data = self.get(self.andi)
        self.assertEqual((data["employee"]["full_name"], data["employee"]["shift"]["name"], data["label"]),
                         ("Andi", "Pagi", "Oktober 2026"))
        self.assertEqual(len(data["days"]), 30)                                   # 26 Sep - 25 Okt
        self.assertEqual([p["full_name"] for p in data["people"]], ["Andi", "Budi", "Citra"])
        t = data["totals"]
        self.assertEqual((t["present_days"], t["meals"], t["overtime_days"], t["late_minutes"]), (25, 3, 3, 25))
        self.assertEqual(self.day(data, "2026-09-27")["kind"], "off")             # a Sunday

    def test_late_day_says_why_and_costs(self):
        d = self.day(self.get(self.andi), "2026-10-06")                          # 08:30: 30 min, tolerance 5
        self.assertEqual((d["kind"], d["in"], d["out"], d["rupiah"]), ("late", "08:30", "17:00", "-12500"))
        self.assertIn("late", [c["key"] for c in d["chips"]])
        self.assertTrue(any("denda 25 menit × Rp 500" in w for w in d["why"]), d["why"])
        self.assertEqual((d["in_min"], d["out_min"], d["shift"]), (510, 1020, {"start": 480, "end": 1020}))

    def test_overtime_and_meal_day(self):
        d = self.day(self.get(self.andi), "2026-10-03")                          # 21:36, 276 min approved
        self.assertEqual(d["overtime_minutes"], 276)
        self.assertEqual({m["group"]: m["amount"] for m in d["money"]}, {"overtime": "56250", "meal": "15000"})
        self.assertEqual(d["rupiah"], "71250")                                    # 4,5 j x 12.500 + 1 x 15.000
        self.assertTrue(any(w.startswith("Lembur 4 j 36 mnt disetujui HR: Rp 56.250") for w in d["why"]), d["why"])

    def test_without_payroll_only_attendance_parts(self):
        money = self.get(self.andi)["money"]
        self.assertEqual(money["source"], "attendance")
        self.assertEqual({p["group"]: p["amount"] for p in money["parts"]},
                         {"overtime": "181250", "meal": "45000", "late": "-12500"})   # 14,5 j as on the slip

    def test_money_from_the_slip_and_stale_after_a_change(self):
        run = self.make_run()
        money = self.get(self.andi)["money"]
        self.assertEqual((money["source"], money["net"], money["check"]["state"]), ("slip", "4133750", "same"))
        self.assertIn("overtime", [e["code"] for e in money["earnings"]])
        self.work(self.budi, date(2026, 10, 7))                                   # attendance changed after payroll
        check = self.get(self.budi)["money"]["check"]
        self.assertEqual(check["state"], "stale")
        self.assertIn("hari potong gaji", check["changed"])
        self.assertEqual(self.line(run["id"], "Budi")["auto"]["unpaid_days"], 3)  # the line itself is untouched

    def test_absent_leave_and_attention(self):
        data = self.get(self.budi)
        d7, d20, d21 = (self.day(data, x) for x in ("2026-10-07", "2026-10-20", "2026-10-21"))
        self.assertEqual((d7["kind"], d7["rupiah"]), ("absent", "-100000"))
        self.assertTrue(any("potong 1 hari (Rp 100.000)" in w for w in d7["why"]), d7["why"])
        self.assertEqual((d20["kind"], d20["rupiah"]), ("unpaid", "-100000"))
        self.assertEqual((d21["kind"], d21["rupiah"]), ("leave", "0"))
        self.assertEqual([a["date"] for a in data["attention"] if a["kind"] == "absent"], ["2026-10-07", "2026-10-08"])

    def test_daily_worker(self):
        data = self.get(self.citra)                                               # joined 1 Okt, 150.000 a day
        self.assertEqual(self.day(data, "2026-09-26")["kind"], "outside")
        self.assertEqual(self.day(data, "2026-09-26")["money"], [])               # a daily worker loses nothing extra
        self.assertEqual(self.day(data, "2026-10-01")["rupiah"], "150000")
        d7 = self.day(data, "2026-10-07")
        self.assertEqual((d7["kind"], d7["money"]), ("absent", []))
        self.assertTrue(any("upah harian tidak dibayar" in w for w in d7["why"]), d7["why"])

    def test_night_clock_out_fixed_by_hr(self):
        """Shaped like the 14 Okt power cut: no taps, HR's times 08:00 - 02:00, overtime 9 j approved."""
        from apps.payroll.tests.test_payrun import at
        cfg = PayrollSettings.objects.get(organization=self.org)
        cfg.meal_late_after, cfg.meal_midnight_extra = time(19), True
        cfg.save()
        rudi = Employee.objects.create(organization=self.org, employee_no="B-9", full_name="Rudi",
                                       join_date=date(2025, 1, 6), default_shift=self.shift, base_rate="3000000",
                                       meal_rule="late_out")
        AttendanceDay.objects.create(organization=self.org, employee=rudi, date=date(2026, 10, 14), shift=self.shift,
                                     hr_in=at(date(2026, 10, 14), 8), hr_out=at(date(2026, 10, 15), 2),
                                     decision="approved", overtime_approved_minutes=540)
        d = self.day(self.get(rudi), "2026-10-14")
        self.assertEqual((d["in"], d["out"], d["out_min"], d["meals"], d["overtime_minutes"]),
                         ("08:00", "02:00", 26 * 60, 2, 540))
        self.assertEqual({m["group"]: m["amount"] for m in d["money"]}, {"overtime": "112500", "meal": "30000"})
        self.assertIn("hr_time", [c["key"] for c in d["chips"]])
        self.assertTrue(any("dikoreksi HR" in w for w in d["why"]))

    def test_errors_and_other_companies(self):
        self.get("not-an-id", status=404)
        r = self.client.get(URL, {"month": "2026-10"})
        self.assertEqual(r.status_code, 400)
        other = Organization.objects.create(name="PT Lain")
        stranger = Employee.objects.create(organization=other, employee_no="X-1", full_name="Orang Lain",
                                           join_date=date(2025, 1, 1), base_rate="3000000")
        self.get(stranger, status=404)

    def test_reads_only(self):
        before = list(AttendanceDay.objects.order_by("id").values_list("id", "decision", "waive_late", "hr_in"))
        self.get(self.andi)
        self.get(self.budi)
        self.assertEqual(list(AttendanceDay.objects.order_by("id").values_list("id", "decision", "waive_late", "hr_in")),
                         before)


class NightDayExplainedTests(SimpleTestCase):
    """The day after a night shift (15 Okt shape): the night rule says why 12:43 is not late. Pure, no database."""
    def test_night_rule_and_meal(self):
        from datetime import datetime
        from types import SimpleNamespace as NS
        from zoneinfo import ZoneInfo
        from apps.attendance import ringkasan as R
        from apps.attendance.attendance_log import Rates
        wib, d = ZoneInfo("Asia/Jakarta"), date(2026, 10, 15)
        note = "Lembur malam sampai 02:00: masuk jam 13:00"
        t = {"date": d, "day_id": "x", "working": True, "status": "on_time", "event": "", "late_raw": 0, "early_raw": 0,
             "first_in": datetime(2026, 10, 15, 12, 43, tzinfo=wib), "last_out": datetime(2026, 10, 15, 21, 0, tzinfo=wib),
             "inside_grace": 0, "night_excused": 283, "night_note": note, "night_rule": note, "locked": False,
             "late_tag": False, "early_tag": False, "late": 0, "early": 0, "late_half": False, "early_half": False,
             "one_tap": False, "permit": False, "half_leave": "", "forgiven": False, "hr_fixed": False,
             "decision": "approved", "rejected": False, "leave_kind": "", "leave_label": "", "absent": False,
             "unpaid_leave": False, "exempt": False, "meal": 1, "breakfast": False, "overtime": 240,
             "meal_rule": "late_out", "present": True, "holiday": False, "disrupted": False, "worked_minutes": 497, "spl": ""}
        cell = {"d": d.isoformat(), "c": "H", "s": "on_time", "l": "Tepat waktu", "day": "x", "rv": False, "ot": 240,
                "otp": 0, "late": 0, "early": 0, "n": note}
        emp = NS(id="E1", pay_type="monthly", default_shift=NS(start_time=time(8), end_time=time(17), saturday_end_time=None))
        cfg = NS(meal_late_after=time(19), breakfast_before=None)
        rates = Rates(fine=500, tolerance=5, per_day=100000, half_day=50000, meal=15000)
        price = lambda t: {"mode": "flat", "rest_day": False, "rounded_minutes": 240, "rate": "12500", "amount": "50000"}
        day = R.build_days(emp, [t], [cell], rates, cfg, {}, price)[0]
        self.assertEqual((day["kind"], day["rupiah"], day["in_min"], day["out_min"]), ("present", "65000", 763, 1260))
        self.assertIn("Boleh masuk siang", [c["label"] for c in day["chips"]])
        self.assertTrue(any("tidak dihitung terlambat" in w for w in day["why"]), day["why"])
        self.assertEqual(R.attention([day]), [])


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(RingkasanTests, _name, None)
