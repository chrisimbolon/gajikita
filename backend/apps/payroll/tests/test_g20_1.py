"""
G20-1 (23 Nov 2026) — Log Kehadiran: late (past the shift's grace, charged after the payroll tolerance), early,
UL / mangkir, uang makan; every day with its basis and rupiah; the log agrees with the payroll line. Made-up people.
"""
from datetime import date

from apps.attendance.models import AttendanceDay
from apps.employees.models import Employee
from apps.payroll.tests import test_payrun as base

URL = "/api/hr/attendance/log/"


class AttendanceLogTests(base.PayRunTests):
    def setUp(self):
        super().setUp()
        self.eka = Employee.objects.create(organization=self.org, employee_no="B-5", full_name="Eka",
                                           join_date=date(2024, 1, 1), default_shift=self.shift, base_rate="3000000")
        self.work(self.eka, date(2026, 10, 1), inn=(8, 3))                       # inside the 5 minutes grace
        self.work(self.eka, date(2026, 10, 2), inn=(8, 20), waive_late=True)    # forgiven by HR

    def log(self):
        r = self.client.get(URL, {"month": "2026-10"})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def by_name(self, tab):
        return {p["employee"]["full_name"]: p for p in tab["people"]}

    def test_late_past_the_grace_and_charged_after_the_tolerance(self):
        data = self.log()
        late = self.by_name(data["late"])
        andi = late["Andi"]                                       # 08:30 on 6 Okt: 30 min, tolerance 5 -> 25 x 500
        self.assertEqual((andi["days"], andi["minutes"], andi["charged_minutes"], andi["rupiah"]), (1, 30, 25, "12500"))
        self.assertEqual([(i["date"], i["basis"]) for i in andi["items"]], [("2026-10-06", "taps")])
        eka = late["Eka"]
        self.assertEqual((eka["days"], eka["forgiven_days"], eka["grace_days"], eka["grace_minutes"], eka["rupiah"]),
                         (1, 1, 1, 3, "0"))
        self.assertEqual([p["employee"]["full_name"] for p in data["late"]["people"]][:2], ["Andi", "Eka"])
        self.assertEqual((data["late"]["summary"]["rupiah"], data["late"]["summary"]["grace_days"]), ("12500", 1))
        self.assertEqual(data["rules"]["shifts"], [{"name": "Pagi", "grace_minutes": 5}])

    def test_ul_and_mangkir_with_their_basis(self):
        absent = self.by_name(self.log()["absent"])
        budi = absent["Budi"]                                     # 7 and 8 Okt no taps, 20 Okt izin tanpa upah
        self.assertEqual((budi["days"], budi["no_basis_days"], budi["unpaid_leave_days"], budi["rupiah"]),
                         (3, 2, 1, "300000"))
        self.assertEqual([i["basis"] for i in budi["items"]], ["none", "none", "unpaid_leave"])
        citra = absent["Citra"]                                   # daily worker, 5 of 21 working days since 1 Okt
        self.assertEqual((citra["days"], citra["daily_worker"], citra["rupiah"]), (16, True, "2400000"))
        self.assertNotIn("Andi", absent)

    def test_meal_money_with_the_rule_that_paid_it(self):
        meal = self.by_name(self.log()["meal"])
        andi = meal["Andi"]                                       # rule: per overtime day, 3 approved overtime days
        self.assertEqual((andi["meals"], andi["rupiah"], andi["rule"]), (3, "45000", "overtime_day"))
        self.assertEqual({i["label"] for i in andi["items"]}, {"Hari lembur"})
        self.assertNotIn("Budi", meal)

    def test_agrees_with_the_payroll_line(self):
        self.assertEqual(self.by_name(self.log()["late"])["Andi"]["slip"]["state"], "none")
        run = self.make_run()
        data = self.log()
        andi, budi = self.by_name(data["late"])["Andi"], self.by_name(data["absent"])["Budi"]
        self.assertEqual((andi["slip"]["state"], budi["slip"]["state"]), ("same", "same"))
        self.assertEqual(andi["charged_minutes"], self.line(run["id"], "Andi")["auto"]["late_minutes"])
        self.assertEqual(budi["days"], self.line(run["id"], "Budi")["auto"]["unpaid_days"])
        self.work(self.budi, date(2026, 10, 7))                  # attendance changed after the payroll
        budi = self.by_name(self.log()["absent"])["Budi"]
        self.assertEqual((budi["days"], budi["slip"]["state"]), (2, "stale"))
        self.assertEqual(self.log()["absent"]["summary"]["stale"], 1)

    def test_reads_only(self):
        before = list(AttendanceDay.objects.order_by("id").values_list("id", "decision", "waive_late"))
        self.log()
        self.assertEqual(list(AttendanceDay.objects.order_by("id").values_list("id", "decision", "waive_late")), before)


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(AttendanceLogTests, _name, None)
