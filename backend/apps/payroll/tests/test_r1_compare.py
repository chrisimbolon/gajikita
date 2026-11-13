"""
R1 (12 Nov 2026) — the SeeGaji-vs-book comparison. Made-up names and amounts only; the layout copies
the payroll book's register sheet (two header rows, numbered people, a second section, a totals row).
"""
import os
import tempfile
from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.employees.models import Employee
from apps.organizations.models import Organization
from apps.payroll import r1_compare as r1
from apps.payroll.models import PayRun, PayRunLine

D = Decimal
HEADER = ["No.", "Nama", "Posisi", "PENGHASILAN (A)", None, None, None, None, None, None,
          "PENGURANGAN (B)", None, None, None, None, None, "PENERIMAAN"]
SUB = [None, None, None, "Gaji Pokok", "Lembur 12.5k/jam", "Lembur\nHari Libur 120K/hr", "Uang Makan", "Kubikasi CP",
       "Insentif BPJS kesehatan", "Insentif/Lainnya", "Keterlambatan", "Unpaid Leave", "BPJSTK\nJHT 2%", "Pinjaman",
       "Lainnya", "PPh21", None]


def book_rows():
    return [
        [None, "Rekapan Gaji", None],
        ["1. Karyawan Tetap ", None, None],
        HEADER, SUB, [None] * 17,
        [1, "Andi Saputra", "Driver", 3000000, 125000, 120000, 45000, 0, 35000, 0, 10000, 0, 60000, 500000, 0, 0, 2755000],
        [2, "Budi H.S", "Helper", 2800000, 0, 0, 0, 21600, 35000, 0, 0, 98333.33, 56000, 0, 0, 0, 2702266.67],
        [3, "Citra Hutasoid", "Admin", 3500000, 0, 0, 0, 0, 35000, 0, 0, 0, 70000, 0, 0, 12000, 3453000],
        [None, None, None, 9300000],                                     # totals row: not a person
        [],
        ["2. Karyawan Tidak Tetap ", None, None],
        HEADER, SUB, [None] * 17,
        [1, "Dodi", "Harian", 700000, 0, 0, 50000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 750000],
        [None, "Eka", "Harian", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],   # unnumbered: ignored
    ]


def result(*earn, deduct=()):
    as_lines = lambda items: [{"code": c, "label": l, "amount": str(a), "quantity": q, "unit": u}
                              for c, l, a, q, u in items]
    return {"earnings": as_lines(earn), "deductions": as_lines(deduct), "employer": [], "warnings": []}


class ReadBookTests(SimpleTestCase):
    def test_people_sections_and_components(self):
        book = r1.read_book(book_rows())
        self.assertEqual([b.name for b in book], ["Andi Saputra", "Budi H.S", "Citra Hutasoid", "Dodi"])
        self.assertEqual(book[3].section, "2. Karyawan Tidak Tetap")
        a = book[0].amounts
        self.assertEqual((a["base"], a["overtime"], a["overtime_rest_day"], a["meal"]), (3000000, 125000, 120000, 45000))
        self.assertEqual((a["bpjs_incentive"], a["late"], a["jht"], a["loan"], a["net"]), (35000, 10000, 60000, 500000, 2755000))
        self.assertEqual(book[1].amounts["piece"], D("21600"))
        self.assertEqual(book[1].amounts["unpaid_leave"], D("98333.33"))
        self.assertEqual(book[2].amounts["pph21"], 12000)

    def test_columns_are_found_by_name_not_position(self):
        sub = list(SUB)
        sub[4], sub[6] = sub[6], sub[4]                                  # swap Lembur and Uang Makan
        rows = [HEADER, sub, [1, "X", "", 1000, 50, 0, 70, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1120]]
        a = r1.read_book(rows)[0].amounts
        self.assertEqual((a["meal"], a["overtime"]), (50, 70))

    def test_no_header_no_people(self):
        self.assertEqual(r1.read_book([[1, "Andi", 5], [2, "Budi", 6]]), [])


class SeeGajiAmountTests(SimpleTestCase):
    def test_codes_and_typed_items(self):
        res = result(("base", "Gaji pokok", 3000000, None, ""), ("fixed_allowance", "Tunjangan tetap", 200000, None, ""),
                     ("meal", "Uang makan", 45000, "3", "hari"), ("breakfast", "Uang sarapan", 10000, "1", "hari"),
                     ("kubikasi_cp", "Kubikasi CP", 21600, None, ""), ("insentif_bpjs", "Insentif BPJS Kesehatan", 35000, None, ""),
                     deduct=[("jht_employee", "JHT", 60000, None, ""), ("pph21", "PPh 21", 12000, None, ""),
                             ("kasbon", "Kasbon", 100000, None, "")])
        a = r1.seegaji_amounts(res)
        self.assertEqual((a["base"], a["meal"], a["piece"], a["bpjs_incentive"]), (3200000, 55000, 21600, 35000))
        self.assertEqual((a["jht"], a["pph21"], a["loan"]), (60000, 12000, 100000))
        self.assertEqual(a["net"], D("3311600") - D("172000"))

    def test_stored_net_wins(self):
        self.assertEqual(r1.seegaji_amounts(result(("base", "", 100, None, "")), net=D("90"))["net"], 90)


class MatchNameTests(SimpleTestCase):
    def test_exact_then_words_then_spelling(self):
        pairs, book_only, emp_only = r1.match_names(
            ["Andi Saputra", "Budi H.S", "Citra Hutasoid", "Akhmad Joan", "Zul"],
            ["Joan", "Citra Hutasoit", "Budi HS", "Andi Saputra", "Maya"])
        self.assertEqual(pairs, {0: 3, 1: 2, 2: 1, 3: 0})
        self.assertEqual((book_only, emp_only), ([4], [4]))

    def test_ambiguous_is_left_alone(self):
        pairs, book_only, _ = r1.match_names(["Andi"], ["Andi Saputra", "Andi Wijaya"])
        self.assertEqual((pairs, book_only), ({}, [0]))

    def test_initials_stand_for_a_word(self):
        pairs, book_only, _ = r1.match_names(["M Iqbal Hidayat", "M. Kamarol"],
                                             ["Muhammad Iqbal Hidayat", "Mohamad Kamarol", "Iqbal Ramadhan"])
        self.assertEqual((pairs, book_only), ({0: 0, 1: 1}, []))

    def test_each_employee_used_once(self):
        pairs, book_only, _ = r1.match_names(["Andi Saputra", "Andi Saputra"], ["Andi Saputra"])
        self.assertEqual((pairs, book_only), ({0: 0}, [1]))


class CompareTests(SimpleTestCase):
    def test_tolerance_and_hints(self):
        book = {"base": D("3000000"), "unpaid_leave": D("98333.33"), "piece": D("21600"), "pph21": D("12000"),
                "late": D("10000"), "net": D("2900000")}
        sg = {"base": D("3000000"), "unpaid_leave": D("98333"), "late": D("15000"), "net": D("2850000")}
        diffs = {d.key: d for d in r1.compare(book, sg)}
        self.assertNotIn("unpaid_leave", diffs)                          # 0.33 apart: same
        self.assertIn("G13", diffs["piece"].hint)
        self.assertIn("G16", diffs["pph21"].hint)
        self.assertIn("absensi", diffs["late"].hint)
        self.assertEqual(diffs["late"].delta, 5000)
        self.assertEqual(r1.status(list(diffs.values())), "beda")

    def test_status(self):
        self.assertEqual(r1.status([]), "cocok")
        only_manual = r1.compare({"piece": D("100"), "net": D("100")}, {"net": D("0")})
        self.assertEqual(r1.status(only_manual), "beda hanya di item manual / pinjaman / PPh")


class CommandTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PT Beton Contoh")
        run = PayRun.objects.create(organization=self.org, name="Payroll Oktober 2026",
                                    period_start=date(2026, 9, 26), period_end=date(2026, 10, 25))

        def line(no, name, res, net):
            emp = Employee.objects.create(organization=self.org, employee_no=no, full_name=name,
                                          join_date=date(2025, 1, 6), base_rate=D("3000000"))
            PayRunLine.objects.create(run=run, employee=emp, result=res, net=D(net))

        line("K1", "Andi Saputra", result(("base", "", 3000000, None, ""), ("overtime", "Lembur", 125000, "10", "jam"),
                                          ("overtime_rest_day", "", 120000, "1", "hari"), ("meal", "", 45000, "3", "hari"),
                                          ("insentif_bpjs", "Insentif BPJS Kesehatan", 35000, None, ""),
                                          deduct=[("late", "", 10000, "20", "menit"), ("jht_employee", "", 60000, None, ""),
                                                  ("loan", "", 500000, None, "")]), "2755000")
        line("K2", "Budi HS", result(("base", "", 2800000, None, ""), deduct=[("jht_employee", "", 56000, None, ""),
                                     ("unpaid_leave", "", 186667, "2", "hari")]), "2557333")
        line("K3", "Maya", result(("base", "", 1000, None, "")), "1000")

    def test_report(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as tmp:
            book_path = os.path.join(tmp, "buku.xlsx")
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Data Gaji (Real)"
            for r in book_rows():
                ws.append(r)
            wb.save(book_path)
            out = StringIO()
            call_command("r1_compare", book=book_path, period="2026-10", org="Beton", stdout=out)
            report = openpyxl.load_workbook(os.path.join(tmp, "R1 2026-10 SeeGaji vs buku.xlsx"))

        self.assertEqual(report.sheetnames, ["Ringkasan", "Selisih", "Nama"])
        people = {r[1]: r for r in report["Ringkasan"].iter_rows(min_row=5, values_only=True) if r[0]}
        self.assertEqual(people["Andi Saputra"][7], "cocok")
        self.assertEqual(people["Budi H.S"][7], "beda")
        diffs = [r for r in report["Selisih"].iter_rows(min_row=5, values_only=True) if r[0]]
        budi = {r[2]: r for r in diffs if r[0] == "Budi H.S"}
        self.assertEqual(budi["Potongan unpaid leave"][3], "2 hari")         # SeeGaji's own quantity shown
        self.assertIn("G13", budi["Kubikasi / semen / insentif kubikasi"][7])
        sides = {(r[0], r[1]) for r in report["Nama"].iter_rows(min_row=5, values_only=True) if r[0]}
        self.assertEqual(sides, {("Hanya di buku", "Citra Hutasoid"), ("Hanya di buku", "Dodi"),
                                 ("Hanya di SeeGaji", "Maya")})
        self.assertIn("2 orang dibandingkan: 1 cocok, 1 beda", out.getvalue())

    def test_missing_run_is_a_clear_error(self):
        from django.core.management.base import CommandError
        with self.assertRaisesMessage(CommandError, "Belum ada pay run 2026-11"):
            call_command("r1_compare", book="x.xlsx", period="2026-11", org="Beton", stdout=StringIO())
