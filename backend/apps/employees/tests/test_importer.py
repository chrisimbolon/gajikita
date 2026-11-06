"""G9 (1 Nov 2026) — reading the employee template (pure, no database)."""
import io
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.employees.importer import FileError, build_template, parse_rows, read_table


def filled_template(rows):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(build_template()))
    ws = wb["Data Karyawan"]
    for r, row in enumerate(rows, start=5):        # below the two example rows
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TemplateRoundTripTests(SimpleTestCase):
    def test_template_rows_are_read_back_cleanly(self):
        data = filled_template([
            ["DK-007", "Sudarmono", "Operator Loader", "2101100107620008", None, "k1", "08/08/2024", "06/11/2024", None,
             "PKWTT (tetap)", "Bulanan", "4.000.000", None, "Ya", "Ya", 24198476079.0, None, "BCA", "0123456789",
             "SUDARMONO", "+62 812-3456-7890", 32.0, "Pagi", "Batching Plant", "DK-001", "Pulang malam"],
        ])
        header, rows, first = read_table("karyawan.xlsx", data)
        items, columns = parse_rows(header, rows, first + 1)
        self.assertEqual(len(columns), 26)                                  # G12d: + Uang Makan
        self.assertEqual(items[-1]["values"]["meal_rule"], "late_out")
        hint, ex1, ex2, real = items
        self.assertEqual((hint["skip"], ex1["skip"], ex2["skip"]),
                         ("Baris petunjuk dari template", "Baris contoh dari template", "Baris contoh dari template"))
        v = real["values"]
        self.assertEqual(real["errors"], [])
        self.assertEqual((v["employee_no"], v["ptkp_status"], v["join_date"], v["probation_end_date"]),
                         ("DK-007", "K/1", date(2024, 8, 8), date(2024, 11, 6)))
        self.assertEqual((v["base_rate"], v["overtime_eligible"], v["bpjs_tk_no"], v["bank_account_no"], v["phone"],
                          v["fingerprint_id"], v["employment_type"], v["pay_type"]),
                         (Decimal("4000000.00"), True, "24198476079", "0123456789", "081234567890", "32", "pkwtt", "monthly"))

    def test_mistakes_are_reported_per_row_in_plain_words(self):
        header = ["No. Karyawan", "Nama", "Tanggal Masuk", "Gaji Pokok", "Status PTKP", "Berhak Lembur", "NIK (KTP)",
                  "Tanggal Keluar"]
        rows = [
            ["A-1", "Andi", "31/02/2026", "abc", "K9", "mungkin", "12345", None],
            ["A-1", "Andi lagi", "01/01/2026", 3000000, "TK/0", "Tidak", None, "01/12/2025"],
            [None, None, None, None, None, None, None, None],
        ]
        items, _ = parse_rows(header, rows)
        self.assertEqual(len(items), 2)                     # the empty row is dropped
        first, second = items
        self.assertEqual(len(first["errors"]), 4)           # date, money, PTKP, Ya/Tidak
        self.assertIn("Tanggal Masuk: format tanggal tidak dikenal", first["errors"][0])
        self.assertEqual(first["warnings"], ["NIK 5 digit (biasanya 16)"])
        self.assertEqual(second["errors"][0], "No. Karyawan A-1 sudah ada di baris 2")
        self.assertIn("Tanggal keluar sebelum tanggal masuk", second["errors"])

    def test_other_layouts_csv_and_aliases(self):
        data = ("NIP;Nama Karyawan;Tgl Masuk;Gapok;No Rek\n"
                "77;Citra;15-Jul-18;Rp 2,950,000;001234\n").encode()
        header, rows, first = read_table("lama.csv", data)
        items, _ = parse_rows(header, rows, first + 1)
        v = items[0]["values"]
        self.assertEqual((v["employee_no"], v["join_date"], v["base_rate"], v["bank_account_no"]),
                         ("77", date(2018, 7, 15), Decimal("2950000.00"), "001234"))

    def test_files_that_cannot_be_read(self):
        with self.assertRaises(FileError):
            read_table("old.xls", b"\xd0\xcf")
        with self.assertRaises(FileError):
            read_table("x.csv", b"a;b\n1;2\n")
