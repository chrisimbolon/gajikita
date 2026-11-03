"""
G9c (2 Nov 2026) — Chris's live test: a real file whose rows were numbered CTH-001… was skipped
whole, and titles like "Nama Lengkap (KTP)", "Hubungan Kerja", "Atasan / Mandor" were not recognised.
"""
from django.test import SimpleTestCase

from apps.employees.importer import is_template_example, match_columns, parse_rows

HEADER = ["No. Karyawan", "Nama Lengkap (KTP)", "NIK (KTP)", "Tanggal Masuk", "Hubungan Kerja", "Atasan / Mandor",
          "Catatan Pribadi"]


class G9cImporterTests(SimpleTestCase):
    def test_titles_with_brackets_and_short_forms(self):
        fields = match_columns(HEADER)
        self.assertEqual([fields.get(i) for i in range(len(HEADER))],
                         ["employee_no", "full_name", "nik", "join_date", "employment_type", "mandor", None])

    def test_only_the_untouched_template_examples_are_skipped(self):
        rows = [["CTH-001", "Budi Santoso", "1234567890123456", "15/07/2018", "PKWTT (tetap)", "CTH-002", ""],
                ["CTH-001", "Budi Santoso", "3174011507880001", "15/07/2018", "PKWTT (tetap)", "", ""],
                ["CTH-003", "Sumargono", "3273011004820003", "10/03/2019", "PKWT (kontrak)", "CTH-001", ""]]
        items, _ = parse_rows(HEADER, rows)
        self.assertEqual([i["skip"] for i in items], ["Baris contoh dari template", "", ""])
        self.assertEqual(items[2]["values"]["employment_type"], "pkwt")
        self.assertTrue(is_template_example({"employee_no": "cth-002", "full_name": "ANDI WIJAYA"}))
