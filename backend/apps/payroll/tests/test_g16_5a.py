"""
G16-5a (25 Nov 2026) — masa pajak by the law ("whichever comes first", PMK 168/2023 Pasal 19), a dated rule
that never moves an earlier payroll, the masa frozen when a payroll is locked, the two-salary / empty-masa
warnings HR confirms (D76, D79, D80), and JP 1% paid by the company as its own setting (D78).
Made-up people and amounts (test_payrun's PT Beton Bintan: period 26-25, paid on the 5th).
"""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from apps.payroll import payrun
from apps.payroll import pph21 as P
from apps.payroll import pph21_year as Y
from apps.payroll.models import PayRun, PayrollSettings
from apps.payroll.tests import test_payrun as base

SETTINGS = "/api/hr/payroll/settings/"


def run(name, start, end, paid):
    return NS(name=name, period_start=start, period_end=end, pay_date=paid, masa_year=None, masa_month=None)


def cfg(mode, since=None, history=()):
    return NS(pph21_tax_month=mode, pph21_tax_month_since=since, pph21_tax_month_history=list(history))


SEP = run("Payroll September 2026", date(2026, 8, 26), date(2026, 9, 25), date(2026, 10, 5))
OKT = run("Payroll Oktober 2026", date(2026, 9, 26), date(2026, 10, 25), date(2026, 11, 5))
NOV = run("Payroll November 2026", date(2026, 10, 26), date(2026, 11, 25), date(2026, 12, 5))


class MasaRuleTests(SimpleTestCase):
    def test_whichever_comes_first(self):
        self.assertEqual(Y.tax_month(date(2026, 11, 25), date(2026, 12, 5), Y.EARLIEST), (2026, 11))  # DKCB: period
        self.assertEqual(Y.tax_month(date(2026, 12, 2), date(2026, 11, 28), Y.EARLIEST), (2026, 11))  # paid first
        self.assertEqual(Y.tax_month(date(2026, 11, 25), None, Y.EARLIEST), (2026, 11))

    def test_a_dated_change_never_moves_earlier_periods(self):
        c = cfg("period_end", date(2026, 10, 1), [{"mode": "paid", "since": None}])
        self.assertEqual(Y.mode_for(c, SEP.period_end), "paid")
        self.assertEqual(Y.mode_for(c, OKT.period_end), "period_end")
        self.assertEqual(Y.run_masa(SEP, c)[:2], (2026, 10))            # paid 5 Okt
        self.assertEqual(Y.run_masa(OKT, c)[:2], (2026, 10))            # ends 25 Okt

    def test_two_salaries_in_one_masa_and_an_empty_masa(self):
        c = cfg("period_end", date(2026, 10, 1), [{"mode": "paid", "since": None}])
        w = Y.masa_checks([SEP, OKT, NOV], c)
        self.assertEqual([(x["kind"], x["masa"]) for x in w], [("double", "Okt 2026")])
        gap = Y.masa_checks([SEP, NOV], cfg("period_end"))
        self.assertEqual([(x["kind"], x["masa"]) for x in gap], [("gap", "Okt 2026")])

    def test_frozen_masa_wins(self):
        locked = run("Payroll Oktober 2026", OKT.period_start, OKT.period_end, OKT.pay_date)
        locked.masa_year, locked.masa_month = 2026, 11
        self.assertEqual(Y.run_masa(locked, cfg("earliest")), (2026, 11, True))

    def test_plan_shows_moves_and_warnings_before_saving(self):
        plan = Y.plan_masa_change([SEP, OKT, NOV], cfg("paid"), "period_end", date(2026, 10, 1))
        self.assertEqual(plan["history"], [{"mode": "paid", "since": None}])
        self.assertEqual([(m["run"], m["before"], m["after"]) for m in plan["moves"]],
                         [("Payroll Oktober 2026", "Nov 2026", "Okt 2026"), ("Payroll November 2026", "Des 2026", "Nov 2026")])
        self.assertEqual([w["kind"] for w in plan["warnings"]], ["midyear", "double"])
        clean = Y.plan_masa_change([SEP, OKT, NOV], cfg("paid"), "period_end", date(2027, 1, 1))
        self.assertEqual((clean["moves"], clean["warnings"]), ([], []))            # from January: nothing moves

    def test_jp_paid_by_the_company_is_a_switch(self):
        slip = {"earnings": [{"code": "base", "amount": "5000000"}],
                "employer": [{"code": "jp_employee_company", "amount": "40000"}]}
        with_jp = P.bruto_from_slip(slip, company_jp_in_bruto=True).total
        without = P.bruto_from_slip(slip, company_jp_in_bruto=False).total
        self.assertEqual(with_jp - without, D("40000"))
        self.assertEqual(Y.iuran_from_slip(slip, company_jp_in_bruto=False), D("0"))


class MasaSettingsTests(base.PayRunTests):
    def set_paid(self):
        PayrollSettings.objects.filter(organization=self.org).update(pph21_tax_month="paid")

    def test_new_company_follows_the_law(self):
        run_ = self.make_run()                                            # ends 25 Okt, paid 5 Nov
        self.assertEqual((run_["masa"], run_["masa_frozen"]), ("Oktober 2026", False))

    def test_a_change_that_moves_a_payroll_needs_confirmation(self):
        self.set_paid()
        self.assertEqual(self.make_run()["masa"], "November 2026")
        body = {"pph21_tax_month": "period_end", "pph21_tax_month_since": "2026-10-14"}
        r = self.client.patch(SETTINGS, body, format="json")
        self.assertEqual(r.status_code, 409, r.data)
        self.assertEqual([(m["before"], m["after"]) for m in r.data["moves"]], [("Nov 2026", "Okt 2026")])
        self.assertEqual(PayrollSettings.for_org(self.org).pph21_tax_month, "paid")          # nothing saved yet
        r = self.client.patch(SETTINGS, {**body, "confirm_masa": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        cfg_ = PayrollSettings.for_org(self.org)
        self.assertEqual((cfg_.pph21_tax_month, cfg_.pph21_tax_month_since, cfg_.pph21_tax_month_history),
                         ("period_end", date(2026, 10, 1), [{"mode": "paid", "since": None}]))   # whole month
        self.assertEqual(self.client.get(base.RUNS).data["runs"][0]["masa"], "Oktober 2026")

    def test_a_locked_payroll_keeps_its_masa(self):
        self.set_paid()
        run_ = PayRun.objects.get(pk=self.make_run()["id"])
        payrun.lock_run(run_, self.hr)
        run_.refresh_from_db()
        self.assertEqual((run_.masa_year, run_.masa_month), (2026, 11))
        r = self.client.patch(SETTINGS, {"pph21_tax_month": "earliest", "confirm_masa": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        listed = self.client.get(base.RUNS).data["runs"][0]
        self.assertEqual((listed["masa"], listed["masa_frozen"]), ("November 2026", True))

    def test_other_settings_save_without_questions(self):
        self.set_paid()
        self.make_run()
        r = self.client.patch(SETTINGS, {"pph21_company_jp_in_bruto": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(PayrollSettings.for_org(self.org).pph21_company_jp_in_bruto)


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(MasaSettingsTests, _name, None)
