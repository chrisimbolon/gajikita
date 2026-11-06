"""
G12a (5 Nov 2026) — DKCB's machine export is "Absen 26 Sept - 25 Okt 26 DKCB Admin.xls" with four
sheets: Schedule Infor., Att. Stat., Att.log report, Exception Stat. All four carry the period, so
the reader must pick the one with the clock times (Att.log report), not the first one.
"""
from datetime import datetime
from unittest import mock

from django.test import SimpleTestCase

from apps.attendance import fingerprint
from apps.attendance.fingerprint import FileError, pick_sheet, read_punches
from apps.core.legacy_excel import OLE_SIGNATURE, LegacyExcelError

DAYS = [float(d) for d in [26, 27, 28, 29, 30] + list(range(1, 26))]     # .xls numbers are floats
SCHEDULE = [[None, "Schedule Information Report"], ["Stat.Date:", "2026-09-26 ~ 2026-10-25"],
            ["ID", "Name", "Department"] + DAYS, [32.0, "SUDARMONO", "DKCB"] + [1.0] * 30]
ATT_LOG = [[None, "Attendance Record Report"], [None], ["Att. Time", None, "2026-09-26 ~ 2026-10-25"], DAYS,
           ["ID:", None, 32.0, None, "Name:", None, "SUDARMONO"],
           ["07:14\n17:00", None, "07:56\n17:05\n17:06"],
           ["ID:", None, 10.0, None, "Name:", None, "IQBAL"],
           ["18:52", "07:00\n18:59", "06:56"]]
EXCEPTION = [["Exception Statistic Report"], ["Stat.Date:", "2026-09-26 ~ 2026-10-25"],
             ["ID", "Name", "Department", "Date", "On-duty", "Off-duty"], [32.0, "SUDARMONO", "DKCB", "2026-10-14", None, "17:01"]]
DKCB_XLS = [("Schedule Infor.", SCHEDULE), ("Att. Stat.", [["Att. Stat"], ["2026-09-26 ~ 2026-10-25"]]),
            ("Att.log report", ATT_LOG), ("Exception Stat.", EXCEPTION)]


class XlsFingerprintTests(SimpleTestCase):
    def test_picks_the_att_log_sheet(self):
        self.assertIs(pick_sheet(DKCB_XLS), ATT_LOG)

    def test_dkcb_xls_export_is_read(self):
        with mock.patch.object(fingerprint, "read_legacy_excel", return_value=DKCB_XLS):
            punches, bad, label = read_punches("Absen 26 Sept - 25 Okt 26 DKCB Admin.xls", OLE_SIGNATURE + b"...")
        self.assertEqual(label, "Attendance Record Report (Excel .xls)")
        sudar = sorted(p.at for p in punches if p.machine_id == "32")
        self.assertEqual(sudar[0], datetime(2026, 9, 26, 7, 14))
        self.assertEqual(sudar[-1], datetime(2026, 9, 28, 17, 6))
        self.assertEqual(len([p for p in punches if p.machine_id == "10"]), 4)

    def test_text_saved_as_xls_is_read_as_text(self):
        data = b"    32\t2026-09-26 07:14:21\t1\t0\t1\t0\n"
        punches, _, label = read_punches("1_attlog.xls", data)
        self.assertEqual((label, punches[0].machine_id), ("attlog.dat (download dari mesin)", "32"))

    def test_an_xls_we_cannot_open_says_what_to_do(self):
        with mock.patch.object(fingerprint, "read_legacy_excel", side_effect=LegacyExcelError("Save As .xlsx")):
            with self.assertRaises(FileError):
                read_punches("Absen.xls", OLE_SIGNATURE)
