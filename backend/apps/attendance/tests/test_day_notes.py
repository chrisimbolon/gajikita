"""
G12f.3.1 (10 Nov 2026) — reading HR's notes per day from an Excel recap. Pure tests, no database.

The rows copy the shape of DKCB's "ESR Edit" sheet (Oct 2026) with made-up names and IDs:
ID · Name · Department · Date · On-duty · Off-duty · Late · Leave early · Absence · Toleransi · Total · Note,
the Note cell coloured with HR's code, and the legend at the top of the "ASR Edit" grid.
"""
import io
from datetime import date, datetime

from django.test import SimpleTestCase

from apps.attendance.day_notes import (MAX_TEXT, parse_note_sheet, pick_note_sheet, read_legend, read_notes)
from apps.attendance.fingerprint import FileError
from apps.attendance.machines import AUTO, MAIN, assign

YELLOW, GREEN, PINK, BLUE, ORANGE, RED = "FFFF00", "00B050", "FF66CC", "00B0F0", "FFC000", "FF0000"
HEAD = ["ID", "Name", "Department", "Date", "On-duty", "Off-duty", "Late time(Min)", "Leave early(Min)",
        "Absence(Min)", "Toleransi (Mins)", "Total(Min)", "Note"]


def grid_sheet():
    """An "ASR Edit"-like sheet: title, legend in rows 1-2, day numbers in row 4 (Sundays red)."""
    values = [["Attendance Record Report"] + [None] * 33 + ["UL", "MC", "Minggu"],
              [None] * 34 + ["CT", "Lain", "Libur"],
              ["Att. Time", None, "2026-09-26 ~ 2026-10-25"],
              [26, 27, 28, 29, 30, 1, 2, 3],
              [None] * 9 + ["UL"]]                       # a code typed in a day cell: not the legend (row 5)
    fills = [[""] * 34 + [YELLOW, GREEN, RED],
             [""] * 34 + [PINK, BLUE, ORANGE],
             ["FFFFFF", "", ""],
             ["", RED, "", "", "", "", "", ""],
             [""] * 9 + [YELLOW]]
    return "ASR Edit", values, fills


def esr_sheet(rows, period="2026-09-26 ~ 2026-10-25\n"):
    """rows: [(id, name, dept, date, note, fill)] -> an "ESR Edit"-like sheet."""
    values = [["Exception Statistic Report", None, None, None, None, None, None, None, None, "Late", 98, None],
              ["Stat.Date:", period] + [None] * 10, HEAD]
    fills = [[""] * 12, [""] * 12, [""] * 12]
    for i, n, d, day, note, fill in rows:
        values.append([i, n, d, day, None, None, 0, 0, 0, 5, 0, note])
        fills.append([""] * 11 + [fill])
    return "ESR Edit", values, fills


ROWS = [("32", "SUDIRMAN", "DKCB", "2026-10-12", "Finger in tidak terbaca & mati lampu", BLUE),
        ("11", "Wawan", "DKCB", "2026-09-29", "UL", YELLOW),
        ("2", "Rina", "DKCB", "2026-09-26", None, ""),                    # an exception row without a note
        ("2", "Rina", "DKCB", "2026-10-01", "Cuti", PINK),
        ("6", "BAYU", "DKCB", "2026-10-15", "Masuk jam 13.00 wib, OT sampai jam 02.00 wib", ""),
        ("3", "Lina", "Staf", "2026-10-05", "Belanja alat", BLUE),
        ("8", "Arman", "DKCB", datetime(2026, 9, 30), "Sakit", GREEN)]    # a real date cell, not text


class LegendTests(SimpleTestCase):
    def test_short_labels_in_filled_cells_at_the_top(self):
        legend = read_legend([grid_sheet(), esr_sheet(ROWS)])
        self.assertEqual(legend, {YELLOW: "UL", GREEN: "MC", RED: "Minggu", PINK: "CT", BLUE: "Lain", ORANGE: "Libur"})

    def test_white_black_numbers_and_lower_rows_are_not_a_legend(self):
        values = [["Judul panjang sekali yang bukan kode", 27, "Ok"], ["X"], ["Y"], ["Z"]]
        fills = [[YELLOW, RED, "FFFFFF"], ["000000"], [""], [GREEN]]
        self.assertEqual(read_legend([("S", values, fills)]), {})


class ParseTests(SimpleTestCase):
    def setUp(self):
        self.legend = read_legend([grid_sheet()])

    def test_codes_come_from_the_colour(self):
        f = parse_note_sheet(*esr_sheet(ROWS)[1:], legend=self.legend, name="ESR Edit")
        self.assertEqual((f.sheet, f.period, f.period_in_file), ("ESR Edit", (date(2026, 9, 26), date(2026, 10, 25)), True))
        self.assertEqual(len(f.rows), 7)
        self.assertEqual([(n.machine_id, n.date.isoformat(), n.code, n.text) for n in f.notes], [
            ("32", "2026-10-12", "Lain", "Finger in tidak terbaca & mati lampu"),
            ("11", "2026-09-29", "UL", "UL"),
            ("2", "2026-10-01", "CT", "Cuti"),
            ("6", "2026-10-15", "", "Masuk jam 13.00 wib, OT sampai jam 02.00 wib"),   # a plain note
            ("3", "2026-10-05", "Lain", "Belanja alat"),
            ("8", "2026-09-30", "MC", "Sakit")])
        self.assertEqual((f.notes[0].name, f.notes[0].dept, f.notes[0].color), ("SUDIRMAN", "DKCB", BLUE))
        self.assertFalse(f.rows[2].has_note)

    def test_a_code_typed_without_colour_still_counts(self):
        f = parse_note_sheet(*esr_sheet([("11", "Wawan", "DKCB", "2026-10-02", " ul ", "")])[1:], legend=self.legend)
        self.assertEqual((f.notes[0].text, f.notes[0].code, f.notes[0].color), ("ul", "UL", ""))

    def test_without_a_legend_the_colour_is_kept(self):
        f = parse_note_sheet(*esr_sheet(ROWS)[1:])
        self.assertEqual((f.notes[0].code, f.notes[0].color), ("", BLUE))

    def test_blank_lines_second_header_bad_dates_and_long_text(self):
        rows = [(None, None, None, None, None, ""), ("ID", "Name", "Department", "Date", "Note", ""),
                ("5", "Dodi", "DKCB", "kemarin", "Izin", BLUE),
                ("05", "Dodi", "DKCB", "06/10/2026", "  kerja \n di   Lobam ", BLUE),
                ("5", "Dodi", "DKCB", "2026-10-07 00:00:00", "x" * (MAX_TEXT + 50), "")]
        f = parse_note_sheet(*esr_sheet(rows)[1:], legend=self.legend)
        self.assertEqual(f.unreadable, 1)
        self.assertEqual([(n.machine_id, n.date) for n in f.rows], [("5", date(2026, 10, 6)), ("5", date(2026, 10, 7))])
        self.assertEqual(f.rows[0].text, "kerja di Lobam")
        self.assertEqual(len(f.rows[1].text), MAX_TEXT)

    def test_rows_outside_the_stated_period_are_left_out(self):
        rows = ROWS + [("2", "Rina", "DKCB", "2026-10-26", "Cuti", PINK), ("2", "Rina", "DKCB", "2026-09-25", "UL", YELLOW)]
        f = parse_note_sheet(*esr_sheet(rows)[1:], legend=self.legend)
        self.assertEqual((len(f.rows), f.outside), (7, 2))

    def test_without_a_stated_period_the_dates_found_are_the_period(self):
        f = parse_note_sheet(*esr_sheet(ROWS, period="")[1:])
        self.assertEqual((f.period, f.period_in_file, f.outside), ((date(2026, 9, 26), date(2026, 10, 15)), False, 0))

    def test_a_date_written_twice_is_reported(self):
        """Finding 16: Vincent's 23 Okt is written twice in the October ESR (the second one is 24 Okt)."""
        rows = [("17", "Vino", "DKCB", "2026-10-23", None, ""),
                ("17", "Vino", "DKCB", "2026-10-23", "Masuk jam 10:00 wib, OT sampai jam 00:01 wib", ""),
                ("17", "Vino", "Staf", "2026-10-23", "Lain mesin", "")]      # same ID on another machine: not a repeat
        f = parse_note_sheet(*esr_sheet(rows)[1:])
        self.assertEqual(f.repeated, [("17", "Vino", date(2026, 10, 23))])

    def test_no_header_is_a_plain_message(self):
        with self.assertRaisesMessage(FileError, "Kolom ID, Date dan Note tidak ditemukan"):
            parse_note_sheet(*grid_sheet()[1:])


class PickSheetTests(SimpleTestCase):
    def test_the_sheet_with_the_most_notes_wins(self):
        machine = esr_sheet([(i, n, d, day, None, "") for i, n, d, day, _, _ in ROWS])   # the machine's own, empty
        machine = ("Exception Stat.",) + machine[1:]
        self.assertEqual(pick_note_sheet([grid_sheet(), machine, esr_sheet(ROWS)])[0], "ESR Edit")
        self.assertEqual(pick_note_sheet([grid_sheet(), machine])[0], "Exception Stat.")
        self.assertIsNone(pick_note_sheet([grid_sheet()]))

    def test_rows_work_with_the_machine_rules(self):
        """A NoteRow carries machine_id / dept / name like a Punch, so "Otomatis menurut Dept." applies."""
        f = parse_note_sheet(*esr_sheet(ROWS)[1:])
        groups = assign(f.rows, AUTO, {"staf": "kantor"})
        self.assertIn(("kantor", "3"), groups)
        self.assertEqual(len(groups[(MAIN, "2")]), 2)
        self.assertEqual(set(assign(f.rows, MAIN)), {(MAIN, r.machine_id) for r in f.rows})


def workbook(*sheets):
    """(name, values, fills) sheets -> .xlsx bytes, the fills as real cell colours."""
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill
    wb = Workbook()
    wb.remove(wb.active)
    for name, values, fills in sheets:
        ws = wb.create_sheet(name)
        for r, row in enumerate(values, start=1):
            for c, v in enumerate(row, start=1):
                cell = ws.cell(row=r, column=c, value=v)
                fill = fills[r - 1][c - 1] if c - 1 < len(fills[r - 1]) else ""
                if fill:
                    cell.fill = PatternFill("solid", fgColor="FF" + fill)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class WorkbookTests(SimpleTestCase):
    def workbook(self, *sheets):
        return workbook(*sheets)

    def test_an_xlsx_recap_with_colours(self):
        f = read_notes("Absen Oktober.xlsx", self.workbook(grid_sheet(), esr_sheet(ROWS)))
        self.assertEqual((f.sheet, f.colors_read, len(f.notes)), ("ESR Edit", True, 6))
        self.assertEqual([n.code for n in f.notes], ["Lain", "UL", "CT", "", "Lain", "MC"])

    def test_a_file_straight_from_the_machine_has_no_notes_yet(self):
        empty = ("Exception Stat.",) + esr_sheet([(i, n, d, day, None, "") for i, n, d, day, _, _ in ROWS])[1:]
        with self.assertRaisesMessage(FileError, "belum berisi catatan"):
            read_notes("mesin.xlsx", self.workbook(grid_sheet(), empty))

    def test_not_an_excel_file(self):
        with self.assertRaisesMessage(FileError, "hanya bisa dibaca dari file Excel"):
            read_notes("1_attlog.dat", b"    32\t2026-09-26 07:14:21\t1\t0\t1\t0\n")
