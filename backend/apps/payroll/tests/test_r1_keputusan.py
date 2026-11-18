"""
R1-3 (18 Nov 2026) — R1 remembers HR's decision on each difference, and only while the difference is the same.
Made-up names and amounts (the shapes of test_r1_compare).
"""
import os
import tempfile
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase

from apps.payroll import r1_compare as r1
from apps.payroll.tests import test_r1_compare as base                    # module, so its tests run once
from apps.payroll.tests.test_r1_compare import book_rows

D = Decimal


class DecisionTests(SimpleTestCase):
    def test_kinds(self):
        self.assertEqual([r1.decision_kind(c) for c in r1.CHOICES], [r1.EXPLAINED, r1.EXPLAINED, r1.WAITING, r1.BUG])
        self.assertEqual((r1.decision_kind(""), r1.decision_kind(None), r1.decision_kind("hmm")), (None, None, r1.UNKNOWN))
        self.assertEqual(r1.decision_kind("salah BUKU (human error)"), r1.EXPLAINED)

    def test_read_and_match(self):
        rows = [["judul"], [], ["Nama", "No. Karyawan", "Komponen", "SeeGaji (Rp)", "Buku (Rp)", "Selisih (Rp)",
                                "Dugaan penyebab", "Keputusan", "Catatan"],
                ["Budi H.S", "K2", "PPh 21", 0, 12000, -12000, "", "Aturan belum ada", "G16"],
                ["Andi", "K1", "Uang makan", 15000, 0, 15000, "", "", ""]]              # not decided: skipped
        ds = r1.read_decisions(rows)
        self.assertEqual([(d.name, d.component, d.delta, d.note) for d in ds], [("Budi H.S", "PPh 21", D("-12000"), "G16")])
        self.assertEqual(r1.match_decision("Budi H.S", "PPh 21", D("-12000.4"), ds)[1], r1.DECIDED)
        self.assertEqual(r1.match_decision("budi h s", "PPh 21", D("-15000"), ds)[1], r1.STALE)   # the amount moved
        self.assertEqual(r1.match_decision("Budi H.S", "Uang makan", D("1"), ds), (None, r1.NEW))

    def test_person_state(self):
        E, W, B = r1.EXPLAINED, r1.WAITING, r1.BUG
        self.assertEqual([r1.person_state(k) for k in ([], [E, E], [E, W], [E, None], [W, B])],
                         ["cocok", "dijelaskan", "menunggu jawaban", "beda: belum diputuskan", "beda: bug SeeGaji"])


class KeputusanCommandTests(base.CommandTests):
    test_report = test_missing_run_is_a_clear_error = None        # run once, in CommandTests

    def run_r1(self, tmp, **kw):
        out = StringIO()
        call_command("r1_compare", book=os.path.join(tmp, "buku.xlsx"), period="2026-10", org="Beton", stdout=out, **kw)
        return out.getvalue(), os.path.join(tmp, "R1 2026-10 SeeGaji vs buku.xlsx")

    def test_decide_then_rerun(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as tmp:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Data Gaji (Real)"
            for r in book_rows():
                ws.append(r)
            wb.save(os.path.join(tmp, "buku.xlsx"))

            text, report = self.run_r1(tmp)
            self.assertIn("Keputusan: 0 dijelaskan, 0 menunggu jawaban, 3 belum diputuskan", text)
            wb = openpyxl.load_workbook(report)
            self.assertEqual(wb.sheetnames, ["Ringkasan", "Selisih", "Keputusan", "Nama"])
            ws = wb["Keputusan"]
            rows = {r[2].value: r for r in ws.iter_rows(min_row=5) if r[0].value}
            self.assertEqual(set(rows), {"Kubikasi / semen / insentif kubikasi", "Insentif BPJS Kesehatan",
                                         "Potongan unpaid leave"})              # net is never listed
            rows["Kubikasi / semen / insentif kubikasi"][7].value = "Salah buku"
            rows["Insentif BPJS Kesehatan"][7].value = "Aturan belum ada"
            rows["Potongan unpaid leave"][7].value = "Tunggu jawaban HR"
            rows["Potongan unpaid leave"][8].value = "2 hari atau 1?"
            wb.save(report)

            text, report = self.run_r1(tmp, keputusan=report)                    # the same file: read, then rewritten
            self.assertIn("Keputusan: 2 dijelaskan, 1 menunggu jawaban, 0 belum diputuskan, 0 bug", text)
            wb = openpyxl.load_workbook(report)
            people = {r[1]: r for r in wb["Ringkasan"].iter_rows(min_row=5, values_only=True) if r[0]}
            self.assertEqual((people["Andi Saputra"][10], people["Budi H.S"][10]), ("cocok", "menunggu jawaban"))
            kept = {r[2]: r for r in wb["Keputusan"].iter_rows(min_row=5, values_only=True) if r[0]}
            self.assertEqual((kept["Potongan unpaid leave"][7], kept["Potongan unpaid leave"][8]),
                             ("Tunggu jawaban HR", "2 hari atau 1?"))
            sel = {r[2]: r for r in wb["Selisih"].iter_rows(min_row=5, values_only=True) if r[0] == "Budi H.S"}
            self.assertEqual(sel["Insentif BPJS Kesehatan"][8], "Aturan belum ada")

            # the amount moves: the decision no longer counts
            from apps.payroll.models import PayRunLine
            line = PayRunLine.objects.get(employee__full_name="Budi HS")
            res = line.result
            res["deductions"] = [x if x["code"] != "unpaid_leave" else {**x, "amount": "93333"} for x in res["deductions"]]
            PayRunLine.objects.filter(pk=line.pk).update(result=res)
            text, report = self.run_r1(tmp, keputusan=report)
            self.assertIn("2 dijelaskan, 0 menunggu jawaban, 0 belum diputuskan, 0 bug, 1 selisih berubah", text)
            wb = openpyxl.load_workbook(report)
            moved = {r[2]: r for r in wb["Keputusan"].iter_rows(min_row=5, values_only=True) if r[0]}["Potongan unpaid leave"]
            self.assertIsNone(moved[7])
            self.assertIn("Keputusan lama 'Tunggu jawaban HR'", moved[8])
