"""
G17-E1 (23 Nov 2026) — the SPL decides whether overtime is paid, the taps how much: SPL mode vs HR's decisions,
HR always wins, "Lembur tanpa SPL", the past-the-plan note, numbering, locked payrolls and
the law row. Made-up people and times.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.attendance import spl as S
from apps.attendance.day_status import DayResult
from apps.attendance.models import AttendanceDay, OvertimeOrder
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.payroll.models import PayrollSettings
from apps.payroll.tests import test_payrun as base

URL = "/api/hr/attendance/spl/"
WIB = ZoneInfo("Asia/Jakarta")
DAY = date(2026, 10, 14)                                  # a Wednesday in October's pay period


def proposal(minutes=210, out=(20, 30)):
    return DayResult(status="on_time", overtime_proposed_minutes=minutes,
                     last_out=datetime(2026, 10, 14, *out, tzinfo=WIB),
                     review_reasons=[f"Lembur {minutes} menit menunggu persetujuan"], needs_review=True)


class SplRuleTests(SimpleTestCase):
    def test_spl_mode(self):
        ref = S.SplRef("x", 7, "Cor lantai 2")
        r = S.apply_spl(proposal(), DAY, ref, spl_mode=True, tz=WIB)
        self.assertEqual((r.overtime_spl_minutes, r.review_reasons, r.needs_review, r.spl), (210, [], False,
                                                                                              "SPL 7 · Cor lantai 2"))
        r = S.apply_spl(proposal(), DAY, None, spl_mode=True, tz=WIB)
        self.assertTrue(r.overtime_no_spl)
        self.assertEqual(r.review_reasons, ["Lembur 210 menit tanpa SPL (tidak dibayar)"])
        r = S.apply_spl(proposal(), DAY, ref, spl_mode=True, decision="approved", tz=WIB)      # HR decided: untouched
        self.assertEqual(r.overtime_spl_minutes, 0)
        r = S.apply_spl(proposal(), DAY, ref, spl_mode=False, tz=WIB)                          # HR decides per day
        self.assertEqual((r.overtime_spl_minutes, r.spl), (0, "SPL 7 · Cor lantai 2"))

    def test_past_the_plan_is_a_note(self):
        ref = S.SplRef("x", 7, "Cor", time(17, 0), time(19, 0))
        self.assertEqual(S.apply_spl(proposal(), DAY, ref, spl_mode=True, tz=WIB).spl_over_plan, 90)
        late = S.SplRef("x", 7, "Cor malam", time(17, 0), time(1, 0))                          # ends after midnight
        self.assertEqual(S.apply_spl(proposal(), DAY, late, spl_mode=True, tz=WIB).spl_over_plan, 0)


class SplApiTests(base.PayRunTests):
    def setUp(self):
        super().setUp()
        self.eka = Employee.objects.create(organization=self.org, employee_no="B-5", full_name="Eka",
                                           join_date=date(2024, 1, 1), default_shift=self.shift, base_rate="4000000")
        self.work(self.eka, DAY, out=(20, 30))                                   # 210 min after 17:00
        self.work(self.eka, date(2026, 10, 15), out=(19, 0))                     # 120 min, no SPL

    def mode(self, value):
        PayrollSettings.objects.filter(organization=self.org).update(overtime_source=value)

    def spl(self, **kw):
        body = {"start_date": DAY.isoformat(), "work": "Cor lantai 2", "employee_ids": [str(self.eka.id)],
                "planned_start": "17:00", "planned_end": "21:00", "issued_by_name": "SPV Plant"}
        body.update(kw)
        return self.client.post(URL + "?month=2026-10", body, format="json")

    def eka_auto(self):
        return self.line(self.make_run()["id"], "Eka")

    def test_numbered_and_audited(self):
        self.assertEqual(self.spl().status_code, 201)
        r = self.spl(start_date="2026-10-15")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(sorted(OvertimeOrder.objects.values_list("number", flat=True)), [1, 2])
        self.assertTrue(AuditEntry.objects.filter(organization=self.org, action="attendance.spl_create").exists())

    def test_only_people_entitled_to_overtime(self):
        Employee.objects.filter(pk=self.eka.pk).update(overtime_eligible=False)
        r = self.spl()
        self.assertEqual(r.status_code, 400)
        self.assertIn("Tidak berhak upah lembur", r.data["message"])

    def test_spl_mode_pays_with_an_spl_only(self):
        self.mode("spl")
        self.spl()
        line = self.eka_auto()
        self.assertEqual([(o["date"], o["minutes"]) for o in line["auto"]["overtime"]], [(DAY.isoformat(), 210)])
        self.assertTrue(any("tanpa SPL" in w for w in line["result"]["warnings"]))       # 15 Okt: not paid

    def test_hr_decision_always_wins(self):
        self.mode("spl")
        self.spl()
        AttendanceDay.objects.filter(employee=self.eka, date=DAY).update(decision="approved")   # Hadir, tanpa lembur
        self.assertEqual(self.eka_auto()["auto"]["overtime"], [])

    def test_decision_mode_keeps_hr_deciding(self):
        self.spl()
        auto = self.eka_auto()["auto"]
        self.assertEqual((auto["overtime"], auto["overtime_open_days"]), ([], 2))

    def test_the_page(self):
        self.mode("spl")
        self.spl()
        page = self.client.get(URL, {"month": "2026-10"}).data
        days = page["orders"][0]["people"][0]["days"]
        self.assertEqual([(d["date"], d["state"], d["paid"]) for d in days], [(DAY.isoformat(), "spl", 210)])
        self.assertEqual([(u["employee"]["full_name"], u["date"]) for u in page["unmatched"]], [("Eka", "2026-10-15")])

    def test_cancel_and_locked_payroll(self):
        self.mode("spl")
        order = self.spl().data["orders"][0]
        r = self.client.post(f"{URL}{order['id']}/cancel/?month=2026-10", {"note": "salah tanggal"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        run = self.make_run()
        self.assertEqual(self.line(run["id"], "Eka")["auto"]["overtime"], [])
        self.client.post(f"{base.RUNS}{run['id']}/lock/", {"action": "lock"}, format="json")
        r = self.spl()
        self.assertEqual(r.status_code, 400)
        self.assertIn("dikunci", r.data["message"])

    def test_law_row(self):
        rows = {x["key"]: x for x in self.client.get("/api/hr/payroll/law-check/").data["rows"]}
        self.assertEqual(rows["overtime_order"]["status"], "differs")
        self.mode("spl")
        rows = {x["key"]: x for x in self.client.get("/api/hr/payroll/law-check/").data["rows"]}
        self.assertEqual(rows["overtime_order"]["status"], "ok")


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(SplApiTests, _name, None)
