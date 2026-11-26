"""
G16-5b (26 Nov 2026) — saldo awal PPh 21 says which masa it covers (D77): the range, the checks against the person's
own SeeGaji payrolls (overlap red and the year waits; gap, before join, no range amber), the CSV columns, and the
December slip that will not settle a year counted twice. Made-up people and amounts (test_payrun's PT Beton Bintan:
period 26-25, paid on the 5th; October's payroll is masa Oktober under the law).
"""
from datetime import date
from decimal import Decimal as D
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase

from apps.employees.models import Employee
from apps.payroll import payrun
from apps.payroll import pph21_year as Y
from apps.payroll.models import PayRun, PayRunLine, PayrollSettings, Pph21Opening
from apps.payroll.tests import test_payrun as base

URL = "/api/hr/payroll/pph21-opening/"
HEAD = "no_karyawan;nama;masa_dari;masa_sampai;bulan;bruto;pph21;iuran_jht_jp\n"


class PureTests(SimpleTestCase):
    def test_months_as_people_write_them(self):
        self.assertEqual([Y.parse_month(x) for x in ("9", "09", "Sep", "september", "Agu", "Agustus", "9/2026",
                                                     "Okt 2026", "")],
                         [9, 9, 9, 9, 8, 8, 9, 10, None])
        self.assertEqual([Y.parse_month(x) for x in ("13", "0", "Sepet")], [0, 0, 0])
        self.assertEqual((Y.range_text(1, 9, 2026), Y.range_text(9, 9), Y.range_text(None, None)),
                         ("Jan–Sep 2026", "Sep", ""))

    def test_the_four_checks(self):
        ok = Y.opening_checks(1, 9, 9, {10, 11})
        self.assertEqual(ok, [])                                                   # Jan-Sep, SeeGaji from Okt
        overlap = Y.opening_checks(1, 10, 10, {10, 11})
        self.assertEqual([(c["kind"], c["level"]) for c in overlap], [("overlap", "red")])
        self.assertIn("Masa Oktober ada di saldo awal dan di payroll SeeGaji", overlap[0]["text"])
        gap = Y.opening_checks(1, 8, 8, {10})
        self.assertEqual([(c["kind"], c["text"]) for c in gap],
                         [("gap", "Masa September tidak ada di saldo awal maupun di payroll SeeGaji.")])
        self.assertEqual(Y.opening_checks(7, 9, 3, {10}, join_month=7), [])           # joined July: fine
        self.assertEqual([c["kind"] for c in Y.opening_checks(1, 9, 9, {10}, join_month=7)], ["before_join"])
        self.assertEqual([c["kind"] for c in Y.opening_checks(None, None, 9, {10})], ["no_range"])
        self.assertEqual(Y.opening_checks(None, None, 0, {10}), [])

    def test_csv_with_a_range(self):
        rows, problems = Y.parse_opening_csv(HEAD + "B-1;Andi;Jan;Sep;;36.000.000;0;720.000\n"
                                                    "B-2;Budi;1;9;8;1;0;0\n"
                                                    "B-3;Cici;Jan;;9;1;0;0\n"
                                                    "B-4;Dodi;Okt;Sep;;1;0;0\n")
        self.assertEqual(problems, [])
        self.assertEqual((rows[0]["masa_from"], rows[0]["masa_to"], rows[0]["months"], rows[0]["errors"]), (1, 9, 9, []))
        self.assertEqual(rows[1]["errors"], ["bulan (8) tidak sama dengan masa Jan–Sep (9 bulan)"])
        self.assertIn("isi masa_dari dan masa_sampai, atau kosongkan keduanya", rows[2]["errors"])
        self.assertIn("masa_dari sesudah masa_sampai", rows[3]["errors"])
        rows, problems = Y.parse_opening_csv("no_karyawan;masa_dari;masa_sampai\nB-1;1;9\n")    # no "bulan": fine
        self.assertEqual((problems, rows[0]["months"]), ([], 9))
        rows, _ = Y.parse_opening_csv("no_karyawan;bulan\nB-1;9\n")                            # the G16-2 file still works
        self.assertEqual((rows[0]["months"], rows[0]["masa_from"], rows[0]["errors"]), (9, None, []))


class RangeApiTests(base.PayRunTests):
    def save(self, emp, status=200, **kw):
        body = {"employee_id": str(emp.pk), "year": 2026, "months": 0, "bruto": "36000000", "pph": "0", "iuran": "0", **kw}
        r = self.client.patch(URL, body, format="json")
        self.assertEqual(r.status_code, status, r.data)
        return r.data

    def row(self, data, name):
        return next(x for x in data["rows"] if x["employee"]["full_name"] == name)

    def test_range_sets_the_months(self):
        data = self.save(self.andi, masa_from=1, masa_to=9)
        row = self.row(data, "Andi")
        self.assertEqual((row["months"], row["masa_from"], row["masa_to"], row["masa_text"]), (9, 1, 9, "Jan–Sep 2026"))
        o = Pph21Opening.objects.get(employee=self.andi)
        self.assertEqual((o.months, o.masa_from, o.masa_to), (9, 1, 9))
        self.save(self.andi, status=400, months=8, masa_from=1, masa_to=9)              # a different count: refused
        self.save(self.andi, status=400, masa_from=1)                                    # one end only
        self.save(self.andi, status=400, masa_from=10, masa_to=9)

    def test_overlap_and_gap_on_the_page(self):
        self.make_run()                                                                  # masa Oktober
        data = self.save(self.andi, masa_from=1, masa_to=10)
        andi = self.row(data, "Andi")
        self.assertEqual(andi["seegaji_masa"], ["Okt"])
        self.assertEqual([c["kind"] for c in andi["checks"]], ["overlap"])
        data = self.save(self.budi, masa_from=1, masa_to=8)
        self.assertEqual([c["kind"] for c in self.row(data, "Budi")["checks"]], ["gap"])
        self.assertEqual((data["totals"]["overlap"], data["totals"]["amber"]), (1, 1))
        ready = self.client.get("/api/hr/payroll/settings/").data["pph21_readiness"]
        self.assertEqual(ready["opening_overlap"], 1)
        data = self.save(self.andi, masa_from=1, masa_to=9)                              # fixed
        self.assertEqual(self.row(data, "Andi")["checks"], [])

    def test_csv_range_saved_and_checked(self):
        self.make_run()
        f = HEAD + "B-1;Andi;Jan;Sep;;36.000.000;0;720.000\nB-2;Budi;1;10;;27.000.000;0;0\n"
        r = self.client.post(f"{URL}import/", {"year": "2026", "commit": "0",
                                               "file": SimpleUploadedFile("s.csv", f.encode())}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([(x["masa_text"], [c["kind"] for c in x["checks"]]) for x in r.data["rows"]],
                         [("Jan–Sep", []), ("Jan–Okt", ["overlap"])])                    # shown before saving
        r = self.client.post(f"{URL}import/", {"year": "2026", "commit": "1",
                                               "file": SimpleUploadedFile("s.csv", f.encode())}, format="multipart")
        self.assertTrue(r.data["saved"])                                                 # a warning, not an error
        self.assertEqual(Pph21Opening.objects.get(employee=self.budi).masa_to, 10)

    def test_yearly_preview_leaves_an_overlap_out(self):
        self.make_run()
        Pph21Opening.objects.create(organization=self.org, employee=self.andi, year=2026, months=10, masa_from=1,
                                    masa_to=10, bruto=D("40000000"), pph=D("0"), iuran=D("0"))
        Pph21Opening.objects.create(organization=self.org, employee=self.budi, year=2026, months=9, masa_from=1,
                                    masa_to=9, bruto=D("27000000"), pph=D("0"), iuran=D("0"))
        out = StringIO()
        call_command("pph21_annual_preview", year=2026, org="Beton", stdout=out)
        text = out.getvalue()
        self.assertIn("TUMPANG TINDIH: Masa Oktober ada di saldo awal", text)
        self.assertIn("Belum lengkap, tidak dijumlah: 1 orang", text)                   # Andi; Budi is counted

    def test_december_slip_waits_for_an_overlap(self):
        Employee.objects.filter(pk=self.andi.pk).update(base_rate=D("10000000"))
        PayrollSettings.objects.filter(organization=self.org).update(pph21_tax_month="paid", pph21_enabled=True)
        run = self.make_run()
        PayRun.objects.filter(pk=run["id"]).update(pay_date=date(2026, 12, 5))           # masa Desember
        Pph21Opening.objects.create(organization=self.org, employee=self.andi, year=2026, months=12, masa_from=1,
                                    masa_to=12, bruto=D("101000000"), pph=D("1515000"), iuran=D("0"))
        line = PayRunLine.objects.select_related("employee", "run").get(run_id=run["id"], employee=self.andi)
        res = payrun.calculate_line(line, PayrollSettings.for_org(self.org)).result
        self.assertTrue(any("belum dihitung: Masa Desember ada di saldo awal" in w for w in res["warnings"]), res["warnings"])
        self.assertFalse(any(n.startswith("PPh 21 setahun") for n in res["notes"]))      # not settled
        Pph21Opening.objects.filter(employee=self.andi).update(months=11, masa_to=11)
        res = payrun.calculate_line(line, PayrollSettings.for_org(self.org)).result
        self.assertTrue(any(n.startswith("PPh 21 setahun 2026: 12 bulan") for n in res["notes"]))


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(RangeApiTests, _name, None)
