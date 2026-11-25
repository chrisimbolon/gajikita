"""
G21-3b (25 Nov 2026) — Saran SeeGaji buttons: preview (always rolled back), Pindahkan (the tap moves, D73),
the s2 form (approved lembur kept, D70), Bukan (D74), Kembalikan, refused when stale. Made-up people (test_g21_3a).
"""
from datetime import date

from django.utils import timezone

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.core.models import AuditEntry
from apps.payroll.tests import test_g21_3a as saran
from apps.payroll.tests import test_payrun as base

S = "/api/hr/attendance/suggestions/"
CHECK = "/api/hr/attendance/checklist/"


class SaranButtonTests(saran.SaranTests):
    def post(self, what, emp, status=200, **data):
        r = self.client.post(f"{S}{what}/", {"employee": str(emp.id), "month": "2026-10", **data}, format="json")
        self.assertEqual(r.status_code, status, r.data)
        return r.data

    def tap_on(self, emp, d):
        return [(e.kind, e.occurred_at) for e in ClockEvent.objects.filter(employee=emp, day__date=d).order_by("occurred_at")]

    def test_preview_changes_nothing(self):
        rudi = self.rudi()
        data = self.post("preview", rudi, id="s1:2026-10-15")
        changes = {(c["date"], c["label"]): (c["before"], c["after"]) for c in data["changes"]}
        self.assertEqual(changes[("2026-10-14", "Pulang")], ("–", "02:00 (+1)"))
        self.assertEqual(changes[("2026-10-15", "Masuk")], ("02:00", "12:43"))
        self.assertEqual(len(self.tap_on(rudi, date(2026, 10, 15))), 3)              # still where it was
        self.assertFalse(AuditEntry.objects.filter(action="attendance.suggestion_apply").exists())

    def test_pindahkan_moves_the_tap_and_recalculates(self):
        rudi = self.rudi()
        self.make_run()
        data = self.post("apply", rudi, id="s1:2026-10-15")
        self.assertIn("dipindah ke 14-10-2026 sebagai jam pulang", data["message"])
        self.assertIsNotNone(data["payroll"]["net_after"])
        self.assertEqual([k for k, _ in self.tap_on(rudi, date(2026, 10, 14))], ["out"])
        self.assertEqual(len(self.tap_on(rudi, date(2026, 10, 15))), 2)
        day14 = AttendanceDay.objects.get(employee=rudi, date=date(2026, 10, 14))
        self.assertEqual((day14.decision, day14.overtime_approved_minutes, day14.hr_out), ("approved", 540, None))
        self.assertEqual(self.saran(rudi), [])                     # done: nothing left, and the moved tap is not
                                                                   # suggested again for 13 Okt (G21-3b.1)
        r = self.client.get(saran.RINGKASAN, {"employee": str(rudi.id), "month": "2026-10"}).data
        moved = next(d for d in r["days"] if d["date"] == "2026-10-14")["moved"]
        self.assertEqual([(m["time"], m["from"]) for m in moved], [("02:00", "2026-10-15")])
        # a second click on the same (now gone) suggestion is refused
        self.post("apply", rudi, status=409, id="s1:2026-10-15")

    def test_kembalikan(self):
        rudi = self.rudi()
        self.post("apply", rudi, id="s1:2026-10-15")
        event = ClockEvent.objects.get(employee=rudi, day__date=date(2026, 10, 14))
        self.post("undo", rudi, event=str(event.id))
        self.assertEqual([k for k, _ in self.tap_on(rudi, date(2026, 10, 15))], ["in", "out", "out"])
        self.assertEqual([s["id"] for s in self.saran(rudi)], ["s1:2026-10-15"])     # the suggestion is back
        self.post("undo", rudi, status=400, event=str(event.id))                     # not twice

    def test_bukan(self):
        rudi = self.rudi()
        self.post("dismiss", rudi, id="s1:2026-10-15")
        # HR says the 02:00 tap is not his pulang: the s1 card goes, and the problem it explained is real again
        self.assertEqual([s["id"] for s in self.saran(rudi)], ["s4:2026-10-14:overtime_on_leave"])
        self.assertEqual(self.client.get(CHECK, {"month": "2026-10"}).data["saran"]["count"], 0)
        self.assertEqual(len(self.tap_on(rudi, date(2026, 10, 15))), 3)              # nothing moved

    def test_s2_form_keeps_approved_overtime(self):
        tono = self.person("B-11", "Tono")
        self.taps(tono, date(2026, 10, 22), (8, 0), decision="approved", overtime_approved_minutes=120)
        preview = self.post("preview", tono, id="s2:2026-10-22", clock_out="20:30")
        self.assertIn(("2026-10-22", "Pulang"), {(c["date"], c["label"]) for c in preview["changes"]})
        self.post("apply", tono, id="s2:2026-10-22", clock_out="20:30")
        day = AttendanceDay.objects.get(employee=tono, date=date(2026, 10, 22))
        self.assertEqual((day.overtime_approved_minutes, day.decision), (120, "approved"))   # not re-derived (D70)
        self.assertEqual(timezone.localtime(day.hr_out).strftime("%Y-%m-%d %H:%M"), "2026-10-22 20:30")

    def test_bad_time_and_unknown(self):
        tono = self.person("B-11", "Tono")
        self.taps(tono, date(2026, 10, 22), (8, 0), decision="approved", overtime_approved_minutes=120)
        self.post("apply", tono, status=400, id="s2:2026-10-22", clock_out="jam tujuh")
        self.post("apply", tono, status=409, id="s1:2026-10-01")


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")] + \
             [n for n in vars(saran.SaranTests) if n.startswith("test_")]:
    setattr(SaranButtonTests, _name, None)
