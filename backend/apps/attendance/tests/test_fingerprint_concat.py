"""
G12f-a (9 Nov 2026) — reading the Attendance Record Report the way DKCB's machine really writes it.

DKCB's machine export ("Absen 26 Sept - 25 Okt 26 DKCB Admin.xls", sheet "Att.log report") and
Anthony's edited copy (sheet "ASR Edit" in "1026 Absensi DKCB.xlsx") put all of a day's taps in
one cell with NO separator: "07:5917:03". Up to G12h the reader needed a line break between
taps and read 47 of the 1,658 taps in the real October file, without any error.

Anthony's workbook also has "ESR Edit" (the Exception Statistic Report) with MORE clock times
than the grid but no row of day numbers; it must never be picked over the grid.

The cell texts below are copied from the real files; names and IDs are anonymised (K..).
"""
import io
from datetime import date, datetime, time
from unittest import mock

from django.test import SimpleTestCase

from apps.attendance import fingerprint
from apps.attendance.fingerprint import (FileError, make_sessions, parse_record_grid, pick_named_sheet,
                                         read_punches, taps_in_cell)
from apps.core.legacy_excel import OLE_SIGNATURE

OCT_DAYS = [26, 27, 28, 29, 30] + list(range(1, 26))
LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T",
           "U", "V", "W", "X", "Y", "Z", "AA", "AB", "AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK"]
COL = {letter: i for i, letter in enumerate(LETTERS)}       # ASR: A=26 Sep ... AD=25 Okt


def row(**cells):
    r = [None] * len(LETTERS)
    for letter, value in cells.items():
        r[COL[letter]] = value
    return r


def id_row(machine_id, name, dept):
    return row(A="ID:", C=machine_id, I="Name:", K=name, S="Dept.:", U=dept)


def asr_edit():
    """Anthony's "ASR Edit": legend, period, day row + OT/SR/UM, 3-row blocks (ID, taps, his overtime)."""
    days = row(**{LETTERS[i]: d for i, d in enumerate(OCT_DAYS)}, AF="OT", AG="SR", AH="UM")
    return [
        row(A="Attendance Record Report", AI="UL", AJ="MC", AK="Minggu"),
        row(AI="CT", AJ="Lain", AK="Libur"),
        row(A="Att. Time", C="2026-09-26 ~ 2026-10-25", J="Tabulation", L="2026-10-26"),
        days,
        row(),
        id_row("32", "K32", "DKCB"),
        row(A="07:1407:1417:0017:00", C="06:4306:4317:0417:04", H="07:1207:1221:3621:36", S="17:0117:01"),
        row(H=4.5, AF="=SUM(A8:AE8)", AH=3),
        id_row("22", "K22", "DKCB"),                       # the Ganda scenario: pump days past midnight
        row(H="08:0708:0708:07", I="00:0000:0000:00",       # 3 Okt in, out at 00:00 in the 4 Okt column
            T="08:1108:1108:11", U="02:0102:0112:2712:2719:1919:19"),   # 15 Okt to 02:01, 16 Okt 12:27-19:19
        row(H=7, AH=20),
        id_row("30", "K30", "DKCB"),                       # works off site: no taps all month
        row(),
        row(),
        id_row("3", "K03", "DKCB"),                        # resigned: codes instead of taps
        row(A="08:0708:0708:0708:0717:3117:3117:31", D="UL", J="sdh tdk join", K="sdh tdk join"),
        row(),
        id_row("12", "K12b", "Staf"),                      # office machine block, same ID as a plant person
        row(A="07:5607:5612:02", C="07:5417:02"),
        row(),
    ]


def esr_edit():
    """Anthony's "ESR Edit": the period, a header, one row per exception day with on/off-duty times."""
    rows = [["Exception Statistic Report"], ["Stat.Date:", "2026-09-26 ~ 2026-10-25\n"],
            ["ID", "Name", "Department", "Date", "On-duty", "Off-duty", "Late time(Min)", "Leave early(Min)",
             "Absence(Min)", "Toleransi (Mins)", "Total(Min)", "Note"]]
    for d in range(1, 26):
        rows.append(["22", "K22", "DKCB", f"2026-10-{d:02d}", "08:15", "00:30", 15, 0, 0, 5, 10, None])
    return rows


def xlsx(sheets):
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def taps_of(punches, machine_id):
    return sorted(p.at for p in punches if p.machine_id == machine_id)


class TapsInCellTests(SimpleTestCase):
    def test_taps_written_with_no_separator(self):
        self.assertEqual(taps_in_cell("07:5917:03"), ([(7, 59), (17, 3)], False))

    def test_double_taps_are_all_read(self):
        self.assertEqual(taps_in_cell("07:1407:1417:0017:00")[0], [(7, 14), (7, 14), (17, 0), (17, 0)])

    def test_line_breaks_spaces_and_seconds(self):
        self.assertEqual(taps_in_cell("07:14\n17:00")[0], [(7, 14), (17, 0)])
        self.assertEqual(taps_in_cell("06:56 18:52")[0], [(6, 56), (18, 52)])
        self.assertEqual(taps_in_cell("07:14:21\n17:00:05"), ([(7, 14), (17, 0)], False))
        self.assertEqual(taps_in_cell("7:5917:03")[0], [(7, 59), (17, 3)])
        self.assertEqual(taps_in_cell(time(7, 14))[0], [(7, 14)])

    def test_codes_are_not_taps_and_not_unread(self):
        for code in ("UL", "CT", "MC", "sdh tdk join", "Blm Join", "", None):
            self.assertEqual(taps_in_cell(code), ([], False), code)

    def test_what_cannot_be_read_is_reported(self):
        self.assertEqual(taps_in_cell("7:5"), ([], True))
        self.assertEqual(taps_in_cell("25:10"), ([], True))
        self.assertEqual(taps_in_cell("07:5917:0"), ([(7, 59)], True))


class AsrEditTests(SimpleTestCase):
    def setUp(self):
        self.punches, self.unread = parse_record_grid(asr_edit())

    def test_every_tap_is_read(self):
        self.assertEqual(len(taps_of(self.punches, "32")), 14)
        self.assertEqual(len(taps_of(self.punches, "22")), 15)
        self.assertEqual(len(taps_of(self.punches, "3")), 7)
        self.assertEqual(len(taps_of(self.punches, "12")), 5)
        self.assertEqual(self.unread, 0)

    def test_days_follow_the_day_row(self):
        k32 = taps_of(self.punches, "32")
        self.assertEqual((k32[0], k32[-1]), (datetime(2026, 9, 26, 7, 14), datetime(2026, 10, 14, 17, 1)))

    def test_name_and_dept_come_with_each_tap(self):
        office = [p for p in self.punches if p.machine_id == "12"]
        self.assertEqual({(p.name, p.dept) for p in office}, {("K12b", "Staf")})
        self.assertEqual({p.dept for p in self.punches if p.machine_id == "32"}, {"DKCB"})

    def test_overtime_row_codes_and_formulas_are_not_taps(self):
        self.assertEqual(taps_of(self.punches, "3")[-1], datetime(2026, 9, 26, 17, 31))
        self.assertEqual(taps_of(self.punches, "30"), [])
        self.assertNotIn(datetime(2026, 10, 3, 4, 30), taps_of(self.punches, "32"))

    def test_pump_days_past_midnight_stay_one_day(self):
        sessions = make_sessions(taps_of(self.punches, "22"), time(8, 0))
        self.assertEqual([(s.work_date, s.clock_in, s.clock_out) for s in sessions], [
            (date(2026, 10, 3), datetime(2026, 10, 3, 8, 7), datetime(2026, 10, 4, 0, 0)),
            (date(2026, 10, 15), datetime(2026, 10, 15, 8, 11), datetime(2026, 10, 16, 2, 1)),
            (date(2026, 10, 16), datetime(2026, 10, 16, 12, 27), datetime(2026, 10, 16, 19, 19)),
        ])

    def test_unreadable_cells_are_counted(self):
        rows = asr_edit()
        rows[6][COL["D"]] = "7:5"
        _, unread = parse_record_grid(rows)
        self.assertEqual(unread, 1)


class SheetChoiceTests(SimpleTestCase):
    def test_grid_wins_over_an_exception_report_with_more_times(self):
        grid, esr = asr_edit(), esr_edit()
        self.assertGreater(fingerprint._sheet_score(esr)[2], fingerprint._sheet_score(grid)[2])
        sheets = [("Note", [["Lembur dihitung ..."]]), ("ESR Edit", esr), ("ASR Edit", grid), ("K22", [["Basic"]])]
        self.assertEqual(pick_named_sheet(sheets)[0], "ASR Edit")

    def test_anthony_workbook_reads_end_to_end_and_names_the_sheet(self):
        data = xlsx([("Note", [["Lembur dihitung ..."]]), ("ESR Edit", esr_edit()), ("ASR Edit", asr_edit())])
        punches, unread, label = read_punches("1026 Absensi DKCB.xlsx", data)
        self.assertEqual(label, 'Attendance Record Report (Excel, sheet "ASR Edit")')
        self.assertEqual((len(punches), unread), (41, 0))

    def test_exception_report_alone_says_what_is_missing(self):
        with self.assertRaisesMessage(FileError, "Baris tanggal"):
            read_punches("ESR.xlsx", xlsx([("ESR Edit", esr_edit())]))

    def test_a_few_numbers_are_not_a_day_row(self):
        rows = asr_edit()
        rows[3] = row(A=26, B=27, C=28, AF="OT")
        self.assertEqual(fingerprint._find_day_cols(rows, date(2026, 9, 26), date(2026, 10, 25)), {})


class MachineXlsTests(SimpleTestCase):
    """The machine's own .xls: 4 sheets, 2-row blocks, day numbers as floats, IDs as text."""

    def machine_sheets(self):
        days = [float(d) for d in OCT_DAYS]
        att_log = [["Attendance Record Report"], [None],
                   ["Att. Time", None, "2026-09-26 ~ 2026-10-25", None, None, None, None, None, None, "Tabulation",
                    None, "2026-10-26"], days,
                   ["ID:", None, "32", None, None, None, None, None, "Name:", None, "K32", None, None, None,
                    None, None, None, None, "Dept.:", None, "DKCB"],
                   ["07:1407:1417:0017:00", None, "06:4306:4317:0417:04", "06:5306:5317:0117:01"],
                   ["ID:", None, "11", None, None, None, None, None, "Name:", None, "K11"],
                   ["07:5917:03", None, "07:5417:03", "UL", "07:5717:02"],
                   ["ID:", None, "25", None, None, None, None, None, "Name:", None, "K25"],   # enrolled, never taps:
                   ["ID:", None, "30", None, None, None, None, None, "Name:", None, "K30"],   # no taps row at all
                   [None, None, "08:0217:00"]]
        schedule = [["Schedule Information Report"], ["Stat.Date:", "2026-09-26 ~ 2026-10-25"],
                    ["ID", "Name", "Department"] + days, ["32", "K32", "DKCB"] + [1.0] * 30]
        stat = [["Statistical Report of Attendance"], ["Stat.Date:", "2026-09-26 ~ 2026-10-25"],
                ["ID", "Name", "Department", "Work hour"], ["32", "K32", "DKCB", "225:00", "207:00"]]
        exception = esr_edit()
        return [("Schedule Infor.", schedule), ("Att. Stat.", stat), ("Att.log report", att_log),
                ("Exception Stat.", exception)]

    def test_real_machine_xls_is_read_in_full(self):
        with mock.patch.object(fingerprint, "read_legacy_excel", return_value=self.machine_sheets()):
            punches, unread, label = read_punches("Absen 26 Sept - 25 Okt 26 DKCB Admin.xls", OLE_SIGNATURE + b"..")
        self.assertEqual(label, 'Attendance Record Report (Excel .xls, sheet "Att.log report")')
        self.assertEqual(len(taps_of(punches, "32")), 12)
        self.assertEqual(taps_of(punches, "11"), [datetime(2026, 9, 26, 7, 59), datetime(2026, 9, 26, 17, 3),
                                                   datetime(2026, 9, 28, 7, 54), datetime(2026, 9, 28, 17, 3),
                                                   datetime(2026, 9, 30, 7, 57), datetime(2026, 9, 30, 17, 2)])
        self.assertEqual(unread, 0)

    def test_a_person_without_a_taps_row_does_not_swallow_the_next_one(self):
        punches, _ = parse_record_grid(self.machine_sheets()[2][1])
        self.assertEqual(taps_of(punches, "25"), [])
        self.assertEqual(taps_of(punches, "30"), [datetime(2026, 9, 28, 8, 2), datetime(2026, 9, 28, 17, 0)])
