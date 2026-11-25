"""
G21-2 (25 Nov 2026) — Ringkasan Karyawan: after HR fixes a day, only that person's payroll line is read again
from attendance (POST .../lines/<id>/recalculate/), audited when the slip changes. Made-up people (test_payrun).
"""
from datetime import date

from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.payroll.models import PayRun
from apps.payroll.tests import test_payrun as base

RINGKASAN = "/api/hr/attendance/ringkasan/"


class LineRecalculateTests(base.PayRunTests):
    def recalc(self, run_id, name, status=200):
        rows, _ = self.rows(run_id)
        r = self.client.post(f"{base.RUNS}{run_id}/lines/{rows[name]['id']}/recalculate/", {}, format="json")
        self.assertEqual(r.status_code, status, r.data)
        return r.data

    def test_only_this_persons_line_is_read_again(self):
        run = self.make_run()
        self.assertEqual(self.line(run["id"], "Budi")["net"], "2640000.00")
        self.work(self.budi, date(2026, 10, 7))                       # HR fixed one of Budi's absent days
        self.work(self.andi, date(2026, 9, 27))                       # and Andi worked a Sunday (not recalculated)
        andi_before = self.line(run["id"], "Andi")
        data = self.recalc(run["id"], "Budi")
        self.assertEqual((data["changed"], data["net_before"], data["line"]["net"]), (True, "2640000.00", "2740000.00"))
        self.assertEqual(data["line"]["auto"]["unpaid_days"], 2)
        andi = self.line(run["id"], "Andi")
        self.assertEqual((andi["net"], andi["auto"]), (andi_before["net"], andi_before["auto"]))
        entry = AuditEntry.objects.get(action="payroll.line_recalc")
        self.assertIn("Budi: dihitung ulang dari absensi", entry.summary)
        check = self.client.get(RINGKASAN, {"employee": str(self.budi.id), "month": "2026-10"}).data["money"]["check"]
        self.assertEqual(check["state"], "same")

    def test_nothing_changed_nothing_audited(self):
        run = self.make_run()
        data = self.recalc(run["id"], "Andi")
        self.assertFalse(data["changed"])
        self.assertFalse(AuditEntry.objects.filter(action="payroll.line_recalc").exists())

    def test_keeps_hr_corrections_and_items(self):
        run = self.make_run()
        rows, _ = self.rows(run["id"])
        url = f"{base.RUNS}{run['id']}/lines/{rows['Andi']['id']}/"
        self.client.patch(url, {"override": {"meal_days": 5}}, format="json")
        self.client.post(f"{url}items/", {"kind": "earning", "label": "Bonus", "amount": "50000"}, format="json")
        line = self.recalc(run["id"], "Andi")["line"]
        self.assertEqual(line["override"], {"meal_days": "5"})
        self.assertEqual([i["label"] for i in line["items"]], ["Bonus"])
        self.assertEqual(line["net"], "4213750.00")                    # 4.133.750 + 2 meals + 50.000

    def test_locked_payroll_is_not_touched(self):
        run = self.make_run()
        PayRun.objects.filter(pk=run["id"]).update(status="locked")
        self.work(self.budi, date(2026, 10, 7))
        self.assertIn("dikunci", self.recalc(run["id"], "Budi", status=400)["message"])
        self.assertEqual(self.line(run["id"], "Budi")["auto"]["unpaid_days"], 3)

    def test_person_not_in_the_payroll_yet(self):
        self.make_run()
        eko = Employee.objects.create(organization=self.org, employee_no="B-7", full_name="Eko", join_date=date(2026, 10, 1),
                                      default_shift=self.shift, base_rate="3000000")
        money = self.client.get(RINGKASAN, {"employee": str(eko.id), "month": "2026-10"}).data["money"]
        self.assertEqual((money["source"], money["check"]["state"]), ("attendance", "missing"))


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(LineRecalculateTests, _name, None)
