"""
G21-3a (25 Nov 2026) — Saran SeeGaji, read-only: SeeGaji finds the dots, HR decides (G21-3 v0.2).
Made-up people on test_payrun's PT Beton Bintan (shift Pagi 08:00-17:00):
  Rudi  shaped like the 14/15 Okt power cut: 14 Okt no taps + lembur 9 j approved, 15 Okt taps 02:00, 12:43, 21:00
  Sari  20 Okt clock-in only, 21 Okt one tap 01:30 (a lone night tap: s3, costs a day)
  Tono  22 Okt clock-in only + lembur 2 j approved, nothing next morning (s2)
"""
from datetime import date

from apps.attendance.models import AttendanceDay, ClockEvent, DayNote
from apps.employees.models import Employee
from apps.payroll.tests import test_payrun as base
from apps.payroll.tests.test_payrun import at

RINGKASAN = "/api/hr/attendance/ringkasan/"
CHECK = "/api/hr/attendance/checklist/"


class SaranTests(base.PayRunTests):
    def person(self, no, name):
        return Employee.objects.create(organization=self.org, employee_no=no, full_name=name, join_date=date(2025, 1, 6),
                                       default_shift=self.shift, base_rate="3000000", meal_rule="late_out")

    def taps(self, emp, d, *times, **day_kw):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift, **day_kw)
        for i, (h, m) in enumerate(times):
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind="in" if i == 0 else "out",
                                      site=self.site, occurred_at=at(d, h, m), received_at=at(d, h, m))
        return day

    def saran(self, emp):
        r = self.client.get(RINGKASAN, {"employee": str(emp.id), "month": "2026-10"})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data["suggestions"]

    def rudi(self, note=True):
        rudi = self.person("B-9", "Rudi")
        AttendanceDay.objects.create(organization=self.org, employee=rudi, date=date(2026, 10, 14), shift=self.shift,
                                     decision="approved", overtime_approved_minutes=540)
        self.taps(rudi, date(2026, 10, 15), (2, 0), (12, 43), (21, 0))
        if note:
            DayNote.objects.create(organization=self.org, employee=rudi, date=date(2026, 10, 15), code="Catatan",
                                   text="Masuk jam 13.00 wib, OT sampai jam 02.00 wib")
        return rudi

    def test_night_tap_belongs_to_the_day_before_kuat(self):
        found = self.saran(self.rudi())
        self.assertEqual([(s["kind"], s["date"], s["to_date"], s["strength"]) for s in found],
                         [("s1", "2026-10-15", "2026-10-14", "kuat")])            # no s2 for 14 Okt: s1 covers it
        s = found[0]
        self.assertEqual(s["text"], "Tap 02:00 di 15 Okt adalah jam pulang 14 Okt.")
        self.assertEqual(len(s["evidence"]), 2)                                  # lembur 9 j + the note naming 02.00
        self.assertIn("Masuk 15 Okt jadi 12:43", s["cost"])
        self.assertIn("dihitung tidak masuk", s["evidence"][0])                 # G21-3a.1: the conflict, told once

    def test_without_evidence_it_is_a_question(self):
        rudi = self.person("B-9", "Rudi")
        self.taps(rudi, date(2026, 10, 14), (8, 0))
        self.taps(rudi, date(2026, 10, 15), (2, 0), (12, 43), (21, 0))
        s = self.saran(rudi)[0]
        self.assertEqual((s["kind"], s["strength"], s["question"]), ("s1", "lemah", True))
        self.assertTrue(s["text"].startswith("Apakah tap 02:00 di 15 Okt jam pulang 14 Okt?"))

    def test_lone_night_tap_says_its_cost(self):
        sari = self.person("B-10", "Sari")
        self.taps(sari, date(2026, 10, 20), (8, 0))
        self.taps(sari, date(2026, 10, 21), (1, 30))
        s = self.saran(sari)[0]
        self.assertEqual((s["kind"], s["date"], s["strength"]), ("s3", "2026-10-21", "lemah"))
        self.assertIn("potong 1 hari, Rp 100.000", s["cost"])

    def test_overtime_without_clock_out_prefills_a_form(self):
        tono = self.person("B-11", "Tono")
        self.taps(tono, date(2026, 10, 22), (8, 0), decision="approved", overtime_approved_minutes=120)
        s = self.saran(tono)[0]
        self.assertEqual((s["kind"], s["strength"]), ("s2", "lemah"))
        self.assertEqual(s["prefill"], {"clock_in": None, "clock_out": "19:00",
                                        "source": "perkiraan: jam pulang shift + lembur", "clock_in_source": ""})
        DayNote.objects.create(organization=self.org, employee=tono, date=date(2026, 10, 22), code="Lain",
                               text="lembur sampai 20.30")
        s = self.saran(tono)[0]
        self.assertEqual((s["strength"], s["prefill"]["clock_out"], s["prefill"]["source"]), ("kuat", "20:30", "catatan HR"))

    def test_fixed_or_locked_days_are_never_suggested(self):
        rudi = self.rudi()
        AttendanceDay.objects.filter(employee=rudi, date=date(2026, 10, 14)).update(is_locked=True)
        self.assertEqual(self.saran(rudi), [])

    def test_hr_already_fixed_the_day(self):
        rudi = self.rudi()
        AttendanceDay.objects.filter(employee=rudi, date=date(2026, 10, 14)).update(
            hr_in=at(date(2026, 10, 14), 8), hr_out=at(date(2026, 10, 15), 2))
        self.assertEqual(self.saran(rudi), [])                                    # what Chris did on live

    def test_siap_gajian_counts_people(self):
        self.rudi()
        sari = self.person("B-10", "Sari")
        self.taps(sari, date(2026, 10, 20), (8, 0))
        self.taps(sari, date(2026, 10, 21), (1, 30))
        saran = self.client.get(CHECK, {"month": "2026-10"}).data["saran"]
        self.assertEqual(saran["count"], 2)
        self.assertEqual([p["employee"]["full_name"] for p in saran["people"]], ["Rudi", "Sari"])

    def test_slip_label(self):
        run = self.make_run()
        labels = [d["label"] for d in self.line(run["id"], "Budi")["result"]["deductions"]]
        self.assertIn("Potongan izin tanpa upah", labels)


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(SaranTests, _name, None)
