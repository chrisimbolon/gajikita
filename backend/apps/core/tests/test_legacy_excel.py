"""
G12a (5 Nov 2026) — old .xls files: real Excel 97-2003 (via xlrd), HTML tables saved as .xls,
and text saved as .xls. xlrd is replaced by a small stand-in so the test runs anywhere.
"""
import sys
import types
from datetime import datetime
from unittest import mock

from django.test import SimpleTestCase

from apps.core.legacy_excel import OLE_SIGNATURE, LegacyExcelError, is_legacy_excel, read_legacy_excel


def fake_xlrd(sheets):
    """A tiny stand-in for xlrd: sheets = [(name, [[(ctype, value), ...], ...])]."""
    m = types.ModuleType("xlrd")
    m.XL_CELL_EMPTY, m.XL_CELL_TEXT, m.XL_CELL_NUMBER, m.XL_CELL_DATE = 0, 1, 2, 3
    m.XL_CELL_BOOLEAN, m.XL_CELL_ERROR, m.XL_CELL_BLANK = 4, 5, 6
    m.xldate = types.SimpleNamespace(xldate_as_datetime=lambda v, mode: datetime(2026, 9, 26, 7, 14))

    class Sheet:
        def __init__(self, name, rows):
            self.name, self._rows = name, rows
            self.nrows, self.ncols = len(rows), max((len(r) for r in rows), default=0)

        def cell(self, r, c):
            row = self._rows[r]
            ctype, value = row[c] if c < len(row) else (0, "")
            return types.SimpleNamespace(ctype=ctype, value=value)

    book = types.SimpleNamespace(datemode=0, sheets=lambda: [Sheet(n, r) for n, r in sheets])
    m.open_workbook = lambda file_contents, on_demand=False: book
    return m


class LegacyExcelTests(SimpleTestCase):
    def test_real_xls_becomes_rows(self):
        xlrd = fake_xlrd([("Att.log report", [[(1, "ID:"), (2, 32.0), (0, ""), (3, 46291.3)],
                                              [(1, "07:56\n17:05"), (4, 1), (5, 42), (6, "")]])])
        with mock.patch.dict(sys.modules, {"xlrd": xlrd}):
            sheets = read_legacy_excel(OLE_SIGNATURE + b"rest of the file")
        self.assertEqual(sheets, [("Att.log report", [["ID:", 32.0, None, datetime(2026, 9, 26, 7, 14)],
                                                      ["07:56\n17:05", True, None, None]])])

    def test_missing_xlrd_says_what_to_do(self):
        with mock.patch.dict(sys.modules, {"xlrd": None}):
            with self.assertRaises(LegacyExcelError) as err:
                read_legacy_excel(OLE_SIGNATURE + b"x")
        self.assertIn("Save As", str(err.exception))

    def test_html_saved_as_xls(self):
        html = (b"<html><body><table><tr><td>ID:</td><td>32</td><td>Name:</td><td>SUDARMONO</td></tr>"
                b"<tr><td>07:56<br>17:05</td><td></td></tr></table></body></html>")
        self.assertEqual(read_legacy_excel(html), [("Tabel 1", [["ID:", "32", "Name:", "SUDARMONO"],
                                                                ["07:56\n17:05", None]])])

    def test_text_saved_as_xls_is_left_to_the_text_readers(self):
        self.assertIsNone(read_legacy_excel(b"No\tTime\n32\t2026-09-26 07:14:21\n"))
        self.assertTrue(is_legacy_excel("Absen.XLS", b""))
        self.assertTrue(is_legacy_excel("absen.bin", OLE_SIGNATURE))
