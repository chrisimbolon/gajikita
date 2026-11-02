"""
G9 (1 Nov 2026) — reading fingerprint machine files (pure, no database).
The grid test rebuilds the layout of PT DKCB's "Attendance Record Report" (Att.log report sheet).
"""
import io
from datetime import date, datetime

from django.test import SimpleTestCase

from apps.attendance.fingerprint import FileError, Punch, clean_id, make_sessions, parse_datetime, read_punches


def dt(s):
    return datetime.fromisoformat(s)


def grid_xlsx():
    """Att.log report, as the machine software writes it: title, period, a day-number row, a block per person."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Att.log report"
    ws["P1"] = "Attendance Record Report"
    ws["A3"] = "Att. Time"
    ws["C3"] = "2026-09-26 ~ 2026-10-25"
    ws["N3"] = "Tabulation"
    ws["P3"] = "2026-10-26"
    days = [26, 27, 28, 29, 30] + list(range(1, 26))
    for i, d in enumerate(days):
        ws.cell(row=4, column=1 + i, value=d)
    # person 1: ID 32 (day shift, double taps, overtime on 3 Oct)
    ws["A5"], ws["C5"], ws["K5"], ws["M5"], ws["T5"], ws["V5"] = "ID:", 32, "Name:", "SUDARMONO", "Dept.:", "DKCB"
    ws.cell(row=6, column=1, value="07:14\n07:14\n17:00\n17:00")         # 26 Sep
    ws.cell(row=6, column=8, value="07:12\n07:12\n21:36\n21:36")          # 3 Oct (column 8 = 3 Oct)
    # person 2: ID 10, night shift: one tap per day, evening in / next morning out
    ws["A7"], ws["C7"], ws["K7"], ws["M7"] = "ID:", 10, "Name:", "IQBAL"
    ws.cell(row=8, column=1, value="18:52")                                 # 26 Sep in
    ws.cell(row=8, column=2, value="07:00\n18:59")                          # 27 Sep out, in again
    ws.cell(row=8, column=3, value="06:56")                                 # 28 Sep out
    # person 3: ID 30, no taps at all (works off site)
    ws["A9"], ws["C9"], ws["K9"], ws["M9"] = "ID:", 30, "Name:", "MARGANDA"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class FormatTests(SimpleTestCase):
    def test_attlog_dat_from_the_machine(self):
        data = (b"    32\t2026-09-26 07:14:21\t1\t0\t1\t0\n"
                b"    32\t2026-09-26 17:00:05\t1\t1\t1\t0\n"
                b"  0010\t2026-09-26 18:52:00\t1\t0\t1\t0\n"
                b"garbage line\n")
        punches, bad, label = read_punches("1_attlog.dat", data)
        self.assertEqual(label, "attlog.dat (download dari mesin)")
        self.assertEqual(bad, 1)
        self.assertEqual(punches[0], Punch("32", dt("2026-09-26 07:14:21")))
        self.assertEqual(punches[2].machine_id, "10")          # leading zeros don't matter

    def test_csv_export_with_day_first_dates(self):
        data = "No.;Name;Time;State\n15;Eko;26/09/2026 07:14;C/In\n15;Eko;26/09/2026 17:03;C/Out\n".encode()
        punches, bad, label = read_punches("export.csv", data)
        self.assertEqual((label, bad, len(punches)), ("CSV / teks", 0, 2))
        self.assertEqual((punches[0].machine_id, punches[0].name, punches[1].at), ("15", "Eko", dt("2026-09-26 17:03")))

    def test_csv_with_separate_date_and_time_columns(self):
        data = "User ID,Nama,Tanggal,Jam\n7,Andi,2026-10-01,07:58\n7,Andi,2026-10-01,17:01\n".encode()
        punches, _, _ = read_punches("absen.csv", data)
        self.assertEqual([p.at for p in punches], [dt("2026-10-01 07:58"), dt("2026-10-01 17:01")])

    def test_attendance_record_report_grid(self):
        punches, _, label = read_punches("Absen 26 Sept - 25 Okt.xlsx", grid_xlsx())
        self.assertEqual(label, "Attendance Record Report (Excel)")
        by_id = {}
        for p in punches:
            by_id.setdefault(p.machine_id, []).append(p.at)
        self.assertEqual(sorted(by_id), ["10", "32"])           # ID 30 had no taps
        self.assertIn(dt("2026-10-03 21:36"), by_id["32"])      # the column for 3 Oct, across the month change
        self.assertEqual(len(by_id["32"]), 8)
        self.assertEqual({p.name for p in punches if p.machine_id == "10"}, {"IQBAL"})

    def test_unreadable_files_say_what_to_do(self):
        with self.assertRaises(FileError) as e:
            read_punches("Absen.xls", b"\xd0\xcf\x11\xe0")
        self.assertIn("Save As", str(e.exception))
        with self.assertRaises(FileError):
            read_punches("notes.csv", b"hello,world\n1,2\n")

    def test_small_helpers(self):
        self.assertEqual([clean_id(v) for v in ("0015", 15, 15.0, " 7 ", "0")], ["15", "15", "15", "7", "0"])
        self.assertEqual(parse_datetime("26/09/2026 7:14 PM"), dt("2026-09-26 19:14"))


class SessionTests(SimpleTestCase):
    def test_day_shift_with_double_taps(self):
        s = make_sessions([dt("2026-09-26 07:14"), dt("2026-09-26 07:14:30"), dt("2026-09-26 17:00"), dt("2026-09-26 17:01")])
        self.assertEqual(len(s), 1)
        self.assertEqual((s[0].work_date, s[0].clock_in, s[0].clock_out), (date(2026, 9, 26), dt("2026-09-26 07:14"), dt("2026-09-26 17:00")))

    def test_night_shift_stays_on_the_date_it_started(self):
        s = make_sessions([dt("2026-09-26 18:52"), dt("2026-09-27 07:00"), dt("2026-09-27 18:59"), dt("2026-09-28 06:56")])
        self.assertEqual([(x.work_date, x.clock_out) for x in s],
                         [(date(2026, 9, 26), dt("2026-09-27 07:00")), (date(2026, 9, 27), dt("2026-09-28 06:56"))])

    def test_forgot_to_clock_out_and_overtime(self):
        s = make_sessions([dt("2026-10-01 07:10"),                       # forgot to clock out
                           dt("2026-10-02 07:05"), dt("2026-10-02 22:00")])   # long overtime day
        self.assertEqual([(x.work_date, x.clock_out) for x in s],
                         [(date(2026, 10, 1), None), (date(2026, 10, 2), dt("2026-10-02 22:00"))])

    def test_middle_taps_are_kept_aside_and_a_quick_second_tap_is_not_a_clock_out(self):
        s = make_sessions([dt("2026-10-05 08:00"), dt("2026-10-05 12:00"), dt("2026-10-05 13:00"), dt("2026-10-05 17:00")])
        self.assertEqual((s[0].clock_out, s[0].ignored, s[0].taps), (dt("2026-10-05 17:00"), [dt("2026-10-05 12:00"), dt("2026-10-05 13:00")], 4))
        s = make_sessions([dt("2026-10-06 08:00"), dt("2026-10-06 08:20")])
        self.assertIsNone(s[0].clock_out)
