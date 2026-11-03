"""
G9d (3 Nov 2026) — "Import dari file apa saja", the pure parts: finding the table in a company's
own file, column choices, word choices, and the file of rows to fix.
"""
import io
from datetime import date

from django.test import SimpleTestCase

from apps.employees import import_mapping as im
from apps.employees.importer import parse_rows

OWN = [
    ("Ringkasan", [["Laporan gaji Oktober"], [None], ["Total", 3]]),
    ("Payroll Okt", [
        ["PT Beton Bintan"],
        [None, None],
        ["NIP", "NAMA PEGAWAI", "TGL MASUK", "GAPOK", "STATUS", "PENEMPATAN", "KODE UNIT"],
        ["B-01", "Andi", "01/02/2023", "4.000.000", "Tetap", "BP Uban", "U1"],
        [None, None, None, None, None, None, None],
        ["B-02", "Budi", "15/07/2018", "3.500.000", "Outsourcing", "BP Uban", "U1"],
        ["B-03", "Citra", "tgl salah", "3.000.000", "Outsourcing", "Kantor", "U2"],
    ]),
]


class FindTableTests(SimpleTestCase):
    def test_finds_the_sheet_and_title_row_by_itself(self):
        t = im.find_table(OWN)
        self.assertEqual((t["sheet"], t["header_row"], t["first_row"]), ("Payroll Okt", 3, 4))
        self.assertEqual([n for n, _ in t["numbered"]], [4, 6, 7])          # the empty row 5 is skipped, numbers stay true
        cols = im.match(t["header"])
        self.assertEqual(sorted(cols.values()), ["base_rate", "employee_no", "join_date"])

    def test_saved_choices_win_and_ignore_works(self):
        header = OWN[1][1][2]
        cols = im.match(header, {"namapegawai": "full_name", "status": "employment_type", "nip": "-",
                                 "kodeunit": "position"})
        self.assertEqual(cols, {1: "full_name", 2: "join_date", 3: "base_rate", 4: "employment_type", 6: "position"})

    def test_a_file_we_cannot_read_at_all_still_opens_for_mapping(self):
        t = im.find_table([("S", [["Kolom A", "Kolom B"], ["x", "y"]])])
        self.assertEqual((t["header_row"], im.match(t["header"])), (1, {}))


class WordsAndReportTests(SimpleTestCase):
    def setUp(self):
        self.t = im.find_table(OWN)
        self.cols = im.match(self.t["header"], {"namapegawai": "full_name", "status": "employment_type",
                                               "penempatan": "site"})

    def test_unknown_words_are_listed_once_with_their_count(self):
        unknown = im.unknown_values(self.t["rows"], self.cols, {}, {"site": ["Batching Plant"]})
        self.assertEqual([(u["field"], u["raw"], u["count"]) for u in unknown],
                         [("employment_type", "Outsourcing", 2), ("site", "BP Uban", 2), ("site", "Kantor", 1)])
        self.assertEqual(unknown[1]["options"], [{"value": "Batching Plant", "label": "Batching Plant"}])

    def test_mapped_words_are_read_as_ours(self):
        values = {"employment_type": {"outsourcing": "PKWT (kontrak)"}, "site": {"bpuban": "Batching Plant", "kantor": ""}}
        rows = im.apply_values(self.t["rows"], self.cols, values)
        items, _ = parse_rows(self.t["header"], rows, self.t["first_row"], columns=self.cols)
        self.assertEqual([(i["row"], i["values"].get("employment_type"), i["values"].get("site")) for i in items],
                         [(4, "pkwtt", "Batching Plant"), (6, "pkwt", "Batching Plant"), (7, "pkwt", None)])
        unknown = im.unknown_values(self.t["rows"], self.cols, values, {"site": ["Batching Plant"]})
        self.assertEqual(unknown[0]["mapped"], "PKWT (kontrak)")

    def test_error_report_holds_only_the_rows_to_fix(self):
        from openpyxl import load_workbook
        plan = [{"row": 4, "action": "create", "errors": []}, {"row": 7, "action": "error",
                                                               "errors": ["Tanggal Masuk: format tanggal tidak dikenal"]}]
        ws = load_workbook(io.BytesIO(im.error_report(self.t["header"], self.t["numbered"], plan))).active
        rows = [[c.value for c in r] for r in ws.iter_rows()]
        self.assertEqual(rows[0][:3], ["Baris di file asli", "NIP", "NAMA PEGAWAI"])
        self.assertEqual((len(rows), rows[1][0], rows[1][2], rows[1][-1]),
                         (2, 7, "Citra", "Tanggal Masuk: format tanggal tidak dikenal"))
