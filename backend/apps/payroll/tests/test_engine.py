"""
G8a (1 Nov 2026) — the payroll engine.

The big test rebuilds a real payroll register: PT DKCB, period 26 Sep - 25 Oct 2026,
29 permanent staff. Names are replaced by codes K01-K29; the amounts are the real ones.
Every net pay visible in the register (22 of 29) must match to the rupiah, and every
column total must match the register's total row.
"""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.payroll.demo_dkcb import DKCB, OCT_2026, REGISTER_TOTALS, dkcb_slip
from apps.payroll.engine import (
    DOWN_HALF, NEAREST_HALF, PP35, EmployeeTerms, OvertimeDay, PayrollRules, PeriodInput, calculate,
    chargeable_late_minutes, round_overtime,
)


class DkcbOctoberRegisterTests(SimpleTestCase):
    def test_every_visible_net_pay_matches_to_the_rupiah(self):
        checked = 0
        for row in OCT_2026:
            if row[-1] is not None:
                self.assertEqual(dkcb_slip(row).net, Decimal(row[-1]), row[0])
                checked += 1
        self.assertEqual(checked, 22)

    def test_every_column_total_matches_the_register(self):
        slips = [dkcb_slip(r) for r in OCT_2026]
        for code, expected in REGISTER_TOTALS.items():
            self.assertEqual(sum(s.amount(code) for s in slips), Decimal(expected), code)

    def test_one_slip_line_by_line(self):
        slip = dkcb_slip(OCT_2026[18])          # K19, an operator loader: the printed slip we saw
        self.assertEqual([(l.label, l.amount) for l in slip.earnings], [
            ("Gaji pokok", Decimal("4000000")), ("Lembur", Decimal("181250")), ("Uang makan", Decimal("45000")),
            ("Insentif BPJS Kesehatan", Decimal("35000"))])
        self.assertEqual([(l.label, l.amount) for l in slip.deductions], [
            ("Iuran BPJS Ketenagakerjaan (JHT 2%)", Decimal("80000")), ("Pinjaman", Decimal("500000"))])
        self.assertEqual((slip.gross, slip.total_deductions, slip.net),
                         (Decimal("4261250"), Decimal("580000"), Decimal("3681250")))
        self.assertEqual(slip.earnings[1].quantity, Decimal("14.5"))

    def test_employer_bpjs_cost(self):
        slip = dkcb_slip(OCT_2026[18])
        self.assertEqual({l.code: l.amount for l in slip.employer},
                         {"jht_company": Decimal("148000"), "jkk": Decimal("35600"), "jkm": Decimal("12000")})

    def test_compliance_warnings(self):
        slips = [dkcb_slip(r) for r in OCT_2026]
        below_umk = sum(1 for s in slips if any("UMK" in w for w in s.warnings))
        not_enrolled = sum(1 for s in slips if any("BPJS Ketenagakerjaan" in w for w in s.warnings))
        self.assertEqual((below_umk, not_enrolled), (23, 3))


class OvertimeRulesTests(SimpleTestCase):
    # K19's three overtime days, from the taps (shift ends 17:00): out 21:36, 21:16, 22:37
    K19_DAYS = (OvertimeDay(date(2026, 10, 3), 276), OvertimeDay(date(2026, 10, 15), 256),
                OvertimeDay(date(2026, 10, 17), 337))

    def test_rounding(self):
        self.assertEqual([round_overtime(m, NEAREST_HALF) for m in (276, 256, 337, 202, 192, 14, 15)],
                         [270, 270, 330, 210, 180, 0, 30])
        self.assertEqual([round_overtime(m, DOWN_HALF) for m in (276, 256, 337)], [270, 240, 330])

    def test_flat_rate_from_taps_reproduces_the_register_and_warns_against_pp35(self):
        slip = calculate(EmployeeTerms(base_salary=Decimal("4000000")),
                         PeriodInput(overtime_days=self.K19_DAYS), DKCB)
        self.assertEqual(slip.amount("overtime"), Decimal("181250"))          # 14.5 h x 12,500
        pp35 = [w for w in slip.warnings if "PP 35/2021 Rp" in w]
        self.assertEqual(pp35, ["Upah lembur Rp 181.250; menurut PP 35/2021 Rp 635.838 (kurang Rp 454.588)"])
        self.assertEqual(sum("melebihi 4 jam" in w for w in slip.warnings), 3)

    def test_pp35_mode_pays_the_legal_amount(self):
        rules = PayrollRules(overtime_mode=PP35, overtime_rounding=NEAREST_HALF)
        slip = calculate(EmployeeTerms(base_salary=Decimal("4000000")), PeriodInput(overtime_days=self.K19_DAYS), rules)
        self.assertEqual(slip.amount("overtime"), Decimal("635838"))

    def test_rest_day_flat_rate(self):
        days = (OvertimeDay(date(2026, 10, 4), 300, rest_day=True), OvertimeDay(date(2026, 10, 5), 60))
        slip = calculate(EmployeeTerms(base_salary=Decimal("4000000")), PeriodInput(overtime_days=days), DKCB)
        self.assertEqual((slip.amount("overtime_rest_day"), slip.amount("overtime")),
                         (Decimal("120000"), Decimal("12500")))

    def test_not_eligible_gets_no_overtime(self):
        slip = calculate(EmployeeTerms(base_salary=Decimal("10000000"), overtime_eligible=False),
                         PeriodInput(overtime_hours=Decimal("10")), DKCB)
        self.assertEqual(slip.amount("overtime"), Decimal("0"))

    def test_pp35_needs_daily_detail(self):
        slip = calculate(EmployeeTerms(base_salary=Decimal("4000000")), PeriodInput(overtime_hours=Decimal("5")),
                         PayrollRules())
        self.assertIn("perlu rincian per hari", slip.warnings[0])


class OtherRulesTests(SimpleTestCase):
    def test_late_tolerance_comes_off_each_day(self):
        # 83 late + 20 early, tolerance 5 -> 98 minutes (the register's 49,000 at Rp 500)
        self.assertEqual(chargeable_late_minutes([(83, 20), (3, 0), (0, 0)], 5), 98)

    def test_unpaid_leave_half_days_and_divisor(self):
        slip = calculate(EmployeeTerms(base_salary=Decimal("2800000")), PeriodInput(unpaid_days=Decimal("2.5")), DKCB)
        self.assertEqual(slip.amount("unpaid_leave"), Decimal("233333"))

    def test_bpjs_wage_includes_fixed_allowance(self):
        slip = calculate(EmployeeTerms(base_salary=Decimal("4000000"), fixed_allowance=Decimal("500000")),
                         PeriodInput(), PayrollRules())
        self.assertEqual(slip.amount("jht_employee"), Decimal("90000"))
        self.assertEqual(slip.amount("fixed_allowance"), Decimal("500000"))

    def test_negative_net_is_flagged(self):
        slip = calculate(EmployeeTerms(base_salary=Decimal("1000000")), PeriodInput(loan_repayment=Decimal("2000000")),
                         PayrollRules())
        self.assertLess(slip.net, 0)
        self.assertIn("minus", slip.warnings[-1])
