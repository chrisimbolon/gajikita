"""
G16-0 (19 Nov 2026) — PPh 21 groundwork: DJP's TER tables, rounding and the annual calculation, tested on the five
October 2026 figures DKCB's book already holds (numbers only; no names needed) and on hand-worked examples.
"""
from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.employees.models import Employee
from apps.organizations.models import Organization
from apps.payroll import pph21 as P
from apps.payroll.models import PayRun, PayRunLine

D = Decimal
OCT = date(2026, 10, 1)


class TerTests(SimpleTestCase):
    def test_tables_have_djp_bracket_counts_and_run_in_order(self):
        tables = P._dated(P.TER_TABLES, OCT)
        self.assertEqual({k: len(v) for k, v in tables.items()}, {"A": 44, "B": 40, "C": 41})
        for rows in tables.values():
            bounds = [u for u, _ in rows if u is not None]
            self.assertEqual(bounds, sorted(bounds))
            self.assertEqual(rows[-1], (None, D("0.34")))
            rates = [r for _, r in rows]
            self.assertEqual(rates, sorted(rates))

    def test_categories(self):
        self.assertEqual([P.ter_category(s) for s in ("TK/0", "TK/1", "K/0", "TK/2", "TK/3", "K/1", "K/2", "K/3")],
                         list("AAABBBBC"))
        with self.assertRaises(ValueError):
            P.ter_category("X/9")

    def test_the_five_october_figures_from_the_book(self):
        cases = [("TK/0", D("5997600"), D("0.0075"), D("44982")),         # A, bruto with JKK/JKM 47.600
                 ("K/1", D("7624250"), D("0.01"), D("76243")),             # B
                 ("K/1", D("9333333"), D("0.015"), D("140000")),           # B, unpaid leave taken off
                 ("K/2", D("10119000"), D("0.015"), D("151785")),          # B, company-borne in the book
                 ("K/1", D("6255000"), D("0.0025"), D("15638"))]           # B, non-permanent paid monthly
        for ptkp, bruto, rate, tax in cases:
            self.assertEqual(P.monthly_pph(bruto, ptkp, OCT), (rate, tax), (ptkp, bruto))

    def test_bracket_edges(self):
        self.assertEqual(P.ter_rate("A", D("5400000"), OCT), D("0"))
        self.assertEqual(P.ter_rate("A", D("5400001"), OCT), D("0.0025"))
        self.assertEqual(P.ter_rate("B", D("9200000"), OCT), D("0.01"))
        self.assertEqual(P.ter_rate("C", D("2000000000"), OCT), D("0.34"))
        self.assertEqual(P.monthly_pph(D("0"), "TK/0", OCT), (D("0"), D("0")))
        with self.assertRaisesMessage(ValueError, "Tidak ada tarif"):
            P.ter_rate("A", D("1"), date(2023, 12, 1))                    # before TER existed

    def test_gross_up_pays_itself(self):
        rate, tax = P.gross_up(D("10119000"), "K/2", OCT)
        self.assertEqual(tax, P.rupiah((D("10119000") + tax) * rate))
        self.assertEqual(rate, D("0.015"))
        self.assertGreater(tax, D("151785"))
        self.assertEqual(P.gross_up(D("3000000"), "TK/0", OCT), (D("0"), D("0")))


class SlipBrutoTests(SimpleTestCase):
    def slip(self):
        line = lambda c, a: {"code": c, "label": c, "amount": str(a)}
        return {"earnings": [line("base", 10000000), line("bpjs_incentive", 35000)],
                "deductions": [line("unpaid_leave", 666667), line("late", 5000), line("jht_employee", 0)],
                "employer": [line("jkk", 89000), line("jkm", 30000), line("jht_company", 370000),
                             line("jht_employee_company", 200000)]}

    def test_parts(self):
        b = P.bruto_from_slip(self.slip())
        self.assertEqual(b.total, D("10000000") + D("35000") - D("666667") + D("119000"))
        late = P.bruto_from_slip(self.slip(), late_reduces=True, company_jht_in_bruto=True)
        self.assertEqual(late.total - b.total, D("-5000") + D("200000"))
        self.assertNotIn("JHT perusahaan", [label for label, _ in late.parts])     # 3,7% is never bruto


class AnnualTests(SimpleTestCase):
    def test_worked_examples(self):
        a = P.annual_pph(D("72000000"), 12, D("1440000"), "TK/0", D("600000"), date(2026, 12, 1))
        self.assertEqual((a.biaya_jabatan, a.netto, a.ptkp, a.pkp, a.tax_year, a.due),
                         (D("3600000"), D("66960000"), D("54000000"), D("12960000"), D("648000"), D("48000")))
        b = P.annual_pph(D("300000000"), 12, D("0"), "K/3", on=date(2026, 12, 1))
        self.assertEqual((b.biaya_jabatan, b.ptkp, b.pkp, b.tax_year), (D("6000000"), D("72000000"),
                                                                       D("222000000"), D("27300000")))
        part = P.annual_pph(D("30000000"), 3, D("0"), "TK/0", on=date(2026, 12, 1))   # joined in October
        self.assertEqual((part.biaya_jabatan, part.pkp, part.tax_year), (D("1500000"), D("0"), D("0")))

    def test_pkp_is_rounded_down_to_thousands(self):
        a = P.annual_pph(D("70000999"), 12, D("0"), "TK/0", on=date(2026, 12, 1))
        self.assertEqual(a.pkp % 1000, 0)

    def test_daily(self):
        self.assertEqual((P.daily_rate(D("120000")), P.daily_rate(D("450001")), P.daily_rate(D("3000000"))),
                         (D("0"), D("0.005"), None))


class PreviewTests(TestCase):
    def test_preview_reads_a_run_and_changes_nothing(self):
        org = Organization.objects.create(name="PT Contoh Pajak")
        run = PayRun.objects.create(organization=org, name="Payroll Oktober 2026",
                                    period_start=date(2026, 9, 26), period_end=date(2026, 10, 25))
        emp = Employee.objects.create(organization=org, employee_no="P-1", full_name="Andi Contoh",
                                      join_date=date(2025, 1, 6), base_rate=D("7500000"), ptkp_status="K/1")
        result = {"earnings": [{"code": "base", "amount": "7500000"}, {"code": "bpjs_incentive", "amount": "35000"}],
                  "deductions": [], "employer": [{"code": "jkk", "amount": "66750"}, {"code": "jkm", "amount": "22500"}]}
        PayRunLine.objects.create(run=run, employee=emp, result=result, net=D("7385000"))
        out = StringIO()
        call_command("pph21_preview", period="2026-10", org="Pajak", stdout=out)
        text = out.getvalue()
        self.assertIn("76.243", text)                                      # 1% x 7.624.250
        self.assertIn("Total PPh 21: Rp 76.243", text)
        self.assertEqual(PayRunLine.objects.get().result, result)          # read-only
