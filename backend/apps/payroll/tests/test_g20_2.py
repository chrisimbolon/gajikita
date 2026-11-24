"""
G20-2 (24 Nov 2026) — (1) the G12e night rule's excused days are visible (DayResult.night_excused_minutes, the
Terlambat tab lists them with Rp 0); (2) "Siap gajian?" step "Tidak cocok": a tap on a leave day, uang makan on a
leave day, overtime on a leave / absent day, ½ day cut with overtime paid; "Sudah benar" (audited). Made-up people,
except Ganda's October taps already in test_ganda_october (no salary in them).
"""
from datetime import date

from django.test import SimpleTestCase

from apps.attendance.tests.test_ganda_october import month as ganda_month
from apps.core.models import AuditEntry
from apps.payroll.tests import test_payrun as base

CHECK = "/api/hr/attendance/checklist/"
DISMISS = "/api/hr/attendance/checklist/dismiss/"


class NightRuleVisibleTests(SimpleTestCase):
    def test_excused_by_the_night_rule(self):
        days = ganda_month()
        d22, d24, d20 = days[date(2026, 10, 22)], days[date(2026, 10, 24)], days[date(2026, 10, 20)]
        self.assertEqual((d22.late_minutes, d22.night_excused_minutes), (0, 27))      # 08:27, in at 10:00 allowed
        self.assertEqual((d24.late_minutes, d24.night_excused_minutes), (0, 19))      # 08:19
        self.assertIn("masuk jam 10:00", d22.night_note)
        self.assertEqual((d20.late_minutes, d20.night_excused_minutes), (19, 120))   # 10:19: late from 10:00 only


class ConflictTests(base.PayRunTests):
    def conflicts(self):
        r = self.client.get(CHECK, {"month": "2026-10"})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data["conflicts"]

    def test_tap_on_a_leave_day(self):
        self.assertEqual(self.conflicts(), {"days": 0, "people": []})
        self.work(self.budi, date(2026, 10, 21))                       # Budi has cuti tahunan on 21 Okt
        c = self.conflicts()
        self.assertEqual(c["days"], 1)
        item = c["people"][0]["items"][0]
        self.assertEqual((c["people"][0]["employee"]["full_name"], item["date"], item["kind"]),
                         ("Budi", "2026-10-21", "taps_on_leave"))
        self.assertIn("dihitung masuk kerja", item["text"])

    def test_sudah_benar(self):
        self.work(self.budi, date(2026, 10, 21))
        body = {"conflict": {"employee": str(self.budi.id), "date": "2026-10-21", "kind": "taps_on_leave"}}
        self.assertEqual(self.client.post(DISMISS, body, format="json").status_code, 200)
        self.assertEqual(self.conflicts()["days"], 0)
        self.assertTrue(AuditEntry.objects.filter(organization=self.org, action="attendance.conflict_dismiss").exists())
        bad = {"conflict": {"employee": str(self.budi.id), "date": "2026-10-21", "kind": "whatever"}}
        self.assertEqual(self.client.post(DISMISS, bad, format="json").status_code, 400)


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(ConflictTests, _name, None)
