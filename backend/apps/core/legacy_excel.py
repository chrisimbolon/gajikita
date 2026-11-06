# =============================================================================
# === backend/apps/core/legacy_excel.py ===
# =============================================================================
"""
Old Excel files (.xls) as plain rows (G12a, 5 Nov 2026). Pure Python, no Django.

Fingerprint machine software (ZKTeco and friends) still exports ".xls". In practice an ".xls"
is one of three things, and all three are handled:
  1. a real Excel 97-2003 file (starts with the OLE signature D0 CF 11 E0) -> read with xlrd
  2. an HTML table saved with an .xls name (many machine programs do this)  -> read the tables
  3. tab- or comma-separated text with an .xls name                          -> None: the caller
     reads it as text, like a CSV

read_legacy_excel(data) -> [(sheet name, rows)] or None (for 3). Each row is a list of cell
values: str, float, bool, datetime or None, the same shapes openpyxl gives for .xlsx.
"""
import re
from html.parser import HTMLParser

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0"


class LegacyExcelError(Exception):
    """An .xls we can't open, with a message HR can act on."""


def is_legacy_excel(filename, data):
    return (filename or "").lower().endswith(".xls") or data[:4] == OLE_SIGNATURE


def read_legacy_excel(data):
    if data[:4] == OLE_SIGNATURE:
        return _read_biff(data)
    head = data[:2048].lstrip().lower()
    if head.startswith((b"<", b"\xef\xbb\xbf<")) and (b"<table" in data[:200000].lower() or b"<html" in head):
        return _read_html(data)
    return None


def _read_biff(data):
    try:
        import xlrd
    except ImportError:                                      # the server is missing the package
        raise LegacyExcelError("File .xls belum bisa dibaca di server ini (paket xlrd belum terpasang). "
                               "Sementara, buka di Excel lalu Save As \"Excel Workbook (.xlsx)\".")
    try:
        book = xlrd.open_workbook(file_contents=data, on_demand=False)
    except Exception:
        raise LegacyExcelError("File .xls tidak bisa dibuka. Mungkin rusak atau dilindungi password. "
                               "Coba buka di Excel lalu Save As \"Excel Workbook (.xlsx)\".")
    sheets = []
    for sh in book.sheets():
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        value = xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
                    except Exception:
                        value = cell.value
                elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
                    value = None
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    value = bool(cell.value)
                else:
                    value = cell.value
                row.append(value)
            rows.append(row)
        sheets.append((sh.name, rows))
    return sheets


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._row, self._cell, self._in_cell = [], None, [], False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._in_cell = [], True
        elif tag == "br" and self._in_cell:
            self._cell.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            text = re.sub(r"[ \t\r\f\v]+", " ", "".join(self._cell)).strip()
            self._row.append(text or None)
            self._in_cell = False
        elif tag == "tr" and self._row is not None and self.tables:
            self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)


def _read_html(data):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    parser = _Tables()
    parser.feed(text)
    tables = [t for t in parser.tables if t]
    if not tables:
        raise LegacyExcelError("File .xls ini berisi halaman web tanpa tabel yang bisa dibaca.")
    return [(f"Tabel {i + 1}", t) for i, t in enumerate(tables)]
