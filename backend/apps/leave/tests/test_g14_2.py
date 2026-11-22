"""
G14-2 (23 Nov 2026) — leave depth under UU No. 27/2026: cuti melahirkan (75% in months 5-6), istirahat keguguran,
istirahat panjang, the attendance bonus during long leave, the long-sickness note, the settings and law rows.
Made-up people and amounts.
"""
from datetime import date
from decimal import Decimal as D

from django.test import SimpleTestCase

from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.leave import rules
from apps.leave.models import LeaveRequest, LeaveSettings
from apps.leave.tests import test_leave_api as leave_base
from apps.payroll import pph21
from apps.payroll.tests import test_payrun as pay_base

SETTINGS = "/api/hr/leave/settings/"
LAW = "/api/hr/payroll/law-check/"


class LeaveDepthRuleTests(SimpleTestCase):
    def test_default_end_dates(self):
        start = date(2026, 11, 2)
        self.assertEqual(rules.default_end(rules.MATERNITY, start), date(2027, 2, 1))       # 3 months
        self.assertEqual(rules.default_end(rules.MISCARRY, start), date(2026, 12, 16))      # 1,5 months
        self.assertEqual(rules.default_end(rules.LONG_REST, start), date(2026, 12, 1))      # 30 days
        self.assertEqual(rules.add_months(date(2027, 1, 31), 1), date(2027, 2, 28))
        self.assertEqual(rules.maternity_reduced_from(date(2026, 5, 26)), date(2026, 9, 26))

    def test_long_rest_every_five_years(self):
        joined = date(2020, 3, 1)
        self.assertIsNone(rules.long_rest_since(joined, date(2025, 2, 28)))
        self.assertEqual(rules.long_rest_since(joined, date(2026, 10, 28)), date(2025, 3, 1))
        self.assertEqual(rules.next_long_rest(joined, date(2026, 10, 28)), date(2030, 3, 1))
        self.assertEqual(rules.long_rest_since(joined, date(2030, 3, 1)), date(2030, 3, 1))
        self.assertEqual(rules.next_long_rest(joined, date(2024, 6, 1)), date(2025, 3, 1))

    def test_long_sickness_steps(self):
        first = date(2026, 5, 1)
        self.assertEqual(rules.long_sick_text(first, date(2026, 8, 31)), "")                 # month 4: full pay
        self.assertIn("bulan ke-5", rules.long_sick_text(first, date(2026, 9, 25)))
        self.assertIn("75%", rules.long_sick_text(first, date(2026, 9, 25)))
        self.assertIn("50%", rules.long_sick_text(first, date(2027, 3, 1)))                  # month 11
        self.assertIn("25%", rules.long_sick_text(first, date(2027, 6, 1)))                  # month 14

    def test_hr_only_and_six_months_at_most(self):
        start = date(2026, 11, 2)
        common = dict(kind=rules.MATERNITY, special_reason="", start=start, annual_left=0, today=date(2026, 10, 28))
        self.assertIn("kind", rules.check_request(end=date(2027, 2, 1), days=92, by_worker=True, **common))
        self.assertEqual(rules.check_request(end=date(2027, 5, 1), days=181, by_worker=False, **common), {})
        self.assertIn("end_date", rules.check_request(end=date(2027, 5, 2), days=182, by_worker=False, **common))

    def test_soft_notes(self):
        start = date(2026, 11, 2)
        self.assertEqual(rules.leave_notes(rules.MATERNITY, start, date(2027, 2, 1), False), [])
        self.assertIn("paling singkat", rules.leave_notes(rules.MATERNITY, start, date(2026, 12, 31), False)[0])
        self.assertIn("surat keterangan dokter", rules.leave_notes(rules.MATERNITY, start, date(2027, 4, 1), False)[0])
        self.assertEqual(rules.leave_notes(rules.MATERNITY, start, date(2027, 4, 1), True), [])
        self.assertIn("Pasal 118 ayat 4", rules.leave_notes(rules.LONG_REST, start, date(2026, 12, 1), False, 3)[0])

    def test_the_cut_is_not_bruto(self):
        result = {"earnings": [{"code": "base", "amount": "3000000"}],
                  "deductions": [{"code": "maternity_cut", "amount": "750000"}], "employer": []}
        self.assertEqual(pph21.bruto_from_slip(result).total, D("2250000"))


class LeaveDepthApiTests(leave_base.LeaveApiTests):
    def record(self, who, kind, start, end, **extra):
        self.as_("hr")
        body = {"employee": str(who.id), "kind": kind, "start_date": start, "end_date": end, "reason": "Formulir"}
        body.update(extra)
        return self.client.post(leave_base.HR, body, format="multipart")

    def test_maternity_is_recorded_by_hr_in_calendar_days(self):
        Employee.objects.filter(pk=self.citra.pk).update(gender="P")
        r = self.ask(self.citra, kind="maternity", start_date="2026-11-02", end_date="2027-02-01")
        self.assertEqual(r.status_code, 400)                                 # not from the phone
        self.assertNotIn("maternity", [k["value"] for k in self.client.get(leave_base.MINE).data["kinds"]])
        r = self.record(self.citra, "maternity", "2026-11-02", "2027-02-01")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["leave"]["days"], r.data["leave"]["calendar_days"], r.data["leave"]["notes"]),
                         (92, True, []))
        r = self.record(self.budi, "maternity", "2026-11-02", "2027-02-01")
        self.assertEqual(r.status_code, 400)                                 # women only

    def test_an_extension_without_a_letter_is_a_note_not_a_refusal(self):
        Employee.objects.filter(pk=self.citra.pk).update(gender="P")
        r = self.record(self.citra, "maternity", "2026-11-02", "2027-05-02")
        self.assertEqual(r.status_code, 400)                                 # more than 6 months
        r = self.record(self.citra, "maternity", "2026-11-02", "2027-04-01")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIn("surat keterangan dokter", r.data["leave"]["notes"][0])

    def test_long_rest_after_five_years_takes_that_years_annual_leave(self):
        r = self.record(self.rudi, "long_rest", "2026-11-02", "2026-12-02")
        self.assertEqual(r.status_code, 400)                                 # 31 days: only 30
        r = self.record(self.rudi, "long_rest", "2026-11-02", "2026-12-01")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["leave"]["days"], 30)
        bal = self.client.get(f"/api/hr/leave/balance/{self.rudi.id}/").data["annual"]
        self.assertEqual((bal["entitled"], bal["long_rest_year"], bal["long_rest"]["left"]), (0, True, 0))
        r = self.record(self.budi, "long_rest", "2026-11-02", "2026-12-01")
        self.assertEqual(r.status_code, 400)                                 # joined 2025
        self.assertIn("Belum berhak", r.data["message"])

    def test_settings_and_law_rows(self):
        self.as_("hr")
        rows = {x["key"]: x for x in self.client.get(LAW).data["rows"]}
        self.assertEqual((rows["maternity"]["status"], rows["long_rest"]["status"]), ("ok", "ok"))
        self.assertEqual(rows["long_rest"]["people"], ["Rudi Mandor"])
        r = self.client.patch(SETTINGS, {"maternity_extension_pay": 50, "long_rest": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(AuditEntry.objects.filter(organization=self.org, action="leave.settings").exists())
        rows = {x["key"]: x for x in self.client.get(LAW).data["rows"]}
        self.assertEqual((rows["maternity"]["status"], rows["long_rest"]["status"]), ("differs", "differs"))
        self.assertNotIn("long_rest", [k["value"] for k in self.client.get(leave_base.HR).data["kinds"]])
        self.assertEqual(self.record(self.rudi, "long_rest", "2026-11-02", "2026-12-01").status_code, 400)


class LeaveDepthPayrollTests(pay_base.PayRunTests):
    def setUp(self):
        super().setUp()
        self.eka = Employee.objects.create(organization=self.org, employee_no="B-5", full_name="Eka", gender="P",
                                           join_date=date(2024, 1, 1), default_shift=self.shift,
                                           base_rate=D("3000000"), attendance_bonus=D("100000"))

    def leave(self, kind, start, end):
        LeaveRequest.objects.create(organization=self.org, employee=self.eka, kind=kind, start_date=start,
                                    end_date=end, days=(end - start).days + 1, status="approved")

    def eka_result(self):
        return self.line(self.make_run()["id"], "Eka")["result"]

    def test_months_five_and_six_are_paid_at_75_percent(self):
        self.leave("maternity", date(2026, 5, 26), date(2026, 11, 25))     # month 5 starts 26 Sep = the period
        res = self.eka_result()
        deds = {x["code"]: x for x in res["deductions"]}
        self.assertEqual(D(deds["maternity_cut"]["amount"]), D("750000"))    # 30 days x 100.000 x 25%
        self.assertNotIn("unpaid_leave", deds)
        self.assertNotIn("attendance_bonus", [x["code"] for x in res["earnings"]])
        self.assertTrue(any("cuti melahirkan" in w for w in res["warnings"]))

    def test_a_company_may_pay_in_full_and_keep_the_bonus(self):
        LeaveSettings.objects.update_or_create(organization=self.org, defaults={
            "maternity_extension_pay": 100, "long_leave_keeps_attendance_bonus": True})
        self.leave("maternity", date(2026, 5, 26), date(2026, 11, 25))
        res = self.eka_result()
        self.assertNotIn("maternity_cut", [x["code"] for x in res["deductions"]])
        self.assertIn("attendance_bonus", [x["code"] for x in res["earnings"]])

    def test_long_sickness_is_a_note(self):
        self.leave("sick", date(2026, 5, 4), date(2026, 10, 25))
        res = self.eka_result()
        self.assertTrue(any("Pasal 149 ayat 3" in n and "bulan ke-6" in n for n in res["notes"]))
        self.assertEqual([x["code"] for x in res["deductions"] if x["code"] in ("unpaid_leave", "maternity_cut")], [])


for _cls, _base in ((LeaveDepthApiTests, leave_base.LeaveApiTests), (LeaveDepthPayrollTests, pay_base.PayRunTests)):
    for _name in [n for n in dir(_base) if n.startswith("test_")]:
        setattr(_cls, _name, None)
