"""
G17-E3 (23 Nov 2026) — the SPL log (by issuer, by work, by person) and UU 27/2026 Pasal 116 ayat 1 huruf c
(4 h a day, 18 h a week) with names on "Aturan perusahaan vs UU". Made-up people and times.
"""
from datetime import date

from django.test import SimpleTestCase

from apps.attendance import spl as S
from apps.employees.models import Employee
from apps.payroll.models import PayrollSettings
from apps.payroll.tests import test_payrun as base

URL = "/api/hr/attendance/spl/"
LAW = "/api/hr/payroll/law-check/"


class OverLimitRuleTests(SimpleTestCase):
    def test_four_hours_a_day(self):
        days = [(date(2026, 10, 3), 276), (date(2026, 10, 15), 240), (date(2026, 10, 17), 337)]
        long_days, heavy = S.over_limits(days)
        self.assertEqual((long_days, heavy), ([date(2026, 10, 3), date(2026, 10, 17)], []))
        self.assertEqual(S.limit_text("Andi", long_days, heavy), "Andi (2 hari lebih dari 4 jam)")

    def test_eighteen_hours_a_week(self):
        days = [(date(2026, 10, d), 230) for d in (12, 13, 14, 15, 16)]                  # Mon-Fri, 19 h 10 m
        long_days, heavy = S.over_limits(days)
        self.assertEqual((long_days, heavy), ([], [(date(2026, 10, 12), 1150)]))
        self.assertEqual(S.limit_text("Eka", long_days, heavy), "Eka (1 minggu lebih dari 18 jam)")
        self.assertEqual(S.over_limits([(date(2026, 10, d), 216) for d in (12, 13, 14, 15, 16)]), ([], []))   # 18 h


class SplLogTests(base.PayRunTests):
    def setUp(self):
        super().setUp()
        self.eka = Employee.objects.create(organization=self.org, employee_no="B-5", full_name="Eka",
                                           join_date=date(2024, 1, 1), default_shift=self.shift, base_rate="4000000")
        self.work(self.eka, date(2026, 10, 14), out=(20, 30))                     # 210 min, with an SPL
        self.work(self.eka, date(2026, 10, 15), out=(19, 0))                      # 120 min, no SPL
        PayrollSettings.objects.filter(organization=self.org).update(overtime_source="spl")
        self.client.post(URL + "?month=2026-10", {"start_date": "2026-10-14", "work": "Cor lantai 2",
                                                  "employee_ids": [str(self.eka.id)], "issued_by_name": "SPV Plant"},
                         format="json")

    def test_the_log(self):
        s = self.client.get(URL, {"month": "2026-10"}).data["summary"]
        self.assertEqual(s["by_issuer"], [{"name": "SPV Plant", "orders": 1, "person_days": 1, "minutes": 210}])
        self.assertEqual([w["name"] for w in s["by_work"]], ["Cor lantai 2"])
        people = {p["employee"]["full_name"]: p for p in s["by_person"]}
        self.assertEqual((people["Eka"]["minutes"], people["Andi"]["minutes"]), (210, 276 + 256 + 337))
        self.assertEqual(people["Andi"]["long_days"], ["2026-10-03", "2026-10-15", "2026-10-17"])
        self.assertEqual((s["no_spl_minutes"], s["over_limit"]), (120, 1))

    def test_the_law_row_names_people(self):
        rows = {x["key"]: x for x in self.client.get(LAW).data["rows"]}
        self.assertNotIn("overtime_length", rows)                                  # no payroll yet
        self.make_run()
        row = {x["key"]: x for x in self.client.get(LAW).data["rows"]}["overtime_length"]
        self.assertEqual(row["status"], "found")
        self.assertEqual(row["people"], ["Andi (3 hari lebih dari 4 jam)"])


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(SplLogTests, _name, None)
