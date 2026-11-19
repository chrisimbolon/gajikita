"""
G18-0 (19 Nov 2026) — soft wage notes (UU No. 27/2026 Pasal 140 and 150). Made-up people and amounts.
"""
from datetime import date
from decimal import Decimal as D

from django.test import SimpleTestCase

from apps.employees.models import Employee
from apps.payroll.engine import EmployeeTerms, PayrollRules, PeriodInput, calculate, serves_under_one_year, wage_notes
from apps.payroll.models import PayrollSettings
from apps.payroll.tests import test_payrun as base

UMK = D("4583221")


class WageNoteRuleTests(SimpleTestCase):
    def test_base_below_75_percent(self):
        notes = wage_notes(D("3000000"), D("1500000"), D("0"), False)
        self.assertEqual(len(notes), 1)
        self.assertIn("66%", notes[0])
        self.assertIn("Pasal 150", notes[0])

    def test_exactly_75_percent_and_no_allowance_are_fine(self):
        self.assertEqual(wage_notes(D("3000000"), D("1000000"), D("0"), False), [])
        self.assertEqual(wage_notes(D("3000000"), D("0"), D("0"), False), [])
        self.assertEqual(wage_notes(D("0"), D("500000"), D("0"), False), [])          # gaji pokok not filled yet

    def test_umk_only_under_one_year(self):
        self.assertIn("UMK", wage_notes(D("4000000"), D("0"), UMK, True)[0])
        self.assertEqual(wage_notes(D("4000000"), D("0"), UMK, False), [])           # 1 year or more
        self.assertEqual(wage_notes(D("4000000"), D("0"), UMK, None), [])            # join date unknown
        self.assertEqual(wage_notes(D("4000000"), D("0"), D("0"), True), [])         # UMK not set
        self.assertEqual(wage_notes(D("4000000"), D("600000"), UMK, True), [])       # pokok + tunjangan tetap >= UMK

    def test_one_year_boundary(self):
        self.assertTrue(serves_under_one_year(date(2025, 11, 26), date(2026, 11, 25)))
        self.assertFalse(serves_under_one_year(date(2025, 11, 26), date(2026, 11, 26)))
        self.assertTrue(serves_under_one_year(date(2024, 2, 29), date(2025, 2, 28)))
        self.assertFalse(serves_under_one_year(date(2024, 2, 29), date(2025, 3, 1)))

    def test_notes_are_not_warnings_and_change_no_amount(self):
        rules = PayrollRules(minimum_wage=UMK)
        plain = calculate(EmployeeTerms(base_salary=D("3000000"), fixed_allowance=D("1500000")), PeriodInput(), rules)
        noted = calculate(EmployeeTerms(base_salary=D("3000000"), fixed_allowance=D("1500000"), under_one_year=True),
                          PeriodInput(), rules)
        self.assertEqual(len(noted.notes), 2)
        self.assertFalse(any("UMK" in w for w in noted.warnings))
        self.assertEqual((noted.gross, noted.net), (plain.gross, plain.net))

    def test_daily_and_piece_workers_are_not_checked(self):
        terms = EmployeeTerms(base_salary=D("100000"), under_one_year=True, check_minimum_wage=False)
        self.assertEqual(calculate(terms, PeriodInput(), PayrollRules(minimum_wage=UMK)).notes, [])


class WageNoteRunTests(base.PayRunTests):
    def test_notes_on_the_run(self):
        PayrollSettings.objects.filter(organization=self.org).update(minimum_wage=UMK)
        eka = Employee.objects.create(organization=self.org, employee_no="B-9", full_name="Eka", join_date=date(2026, 6, 1),
                                      default_shift=self.shift, base_rate=D("3000000"), fixed_allowance=D("1500000"))
        for d in self.working:
            self.work(eka, d)
        run = self.make_run()
        rows, data = self.rows(run["id"])
        line = self.line(run["id"], "Eka")
        self.assertEqual(len(line["result"]["notes"]), 2)
        self.assertFalse(any("UMK" in w for w in line["result"]["warnings"]))
        self.assertEqual((rows["Eka"]["note_count"], rows["Andi"]["note_count"]), (2, 0))   # Andi: joined Jan 2025
        self.assertEqual(data["run"]["notes"], 2)


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(WageNoteRunTests, _name, None)
