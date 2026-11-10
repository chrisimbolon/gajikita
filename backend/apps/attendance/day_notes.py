# =============================================================================
# === backend/apps/attendance/day_notes.py ===
# =============================================================================
"""
HR's own notes per day, read from an Excel recap (G12f.3, 10 Nov 2026). Pure Python + openpyxl, no Django.

DKCB's HR keeps an "Exception Statistic Report" ("ESR Edit") beside the machine export: one row per
exception day (ID, Name, Department, Date, On-duty, Off-duty, ..., Note) and in Note his reason,
the cell coloured with his code (yellow = UL, pink = CT, blue = Lain ...). The colour legend sits at
the top of his "ASR Edit" sheet: a short label in a filled cell ("UL" on yellow).

  read_note_sheets(filename, data)   the workbook as [(sheet name, values, fills)]; a fill is "RRGGBB" or "".
  read_legend(sheets)                {colour: label} from filled short labels in the first rows of any sheet.
  pick_note_sheet(sheets)            the sheet with an ID / Date / Note header and the most notes.
  parse_note_sheet(values, fills, legend)   -> NoteFile: every readable row (with or without a note),
                                     the report period, rows we could not read, dates listed twice.
  read_notes(filename, data)         all of the above in one call.

Nothing here decides anything about attendance: a note is text and a colour, shown to HR beside the day.
The machine's own "Exception Stat." sheet has the same columns with an empty Note: it reads, with no notes.
"""
import io
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import date as Date, datetime

from apps.core.legacy_excel import LegacyExcelError, is_legacy_excel, read_legacy_excel

from .fingerprint import FileError, _cell_text, _find_period, _key, clean_id, parse_date

LEGEND_ROWS = 3                      # a colour legend sits in the first rows of a sheet (DKCB: rows 1-2)
HEADER_ROWS = 15                     # the column header is somewhere in the first rows
MAX_TEXT = 500                       # a note longer than this is cut (a cell, not a document)
LEGEND_LABEL = re.compile(r"[^\W\d_][\w .\-/]{0,15}")
NOT_A_CODE = {"FFFFFF", "000000"}    # white / black fills are formatting, not codes

ID_KEYS = ("id", "acno", "userid", "pin", "enno", "idmesin", "nomesin", "no")
DATE_KEYS = ("date", "tanggal", "tgl")
NOTE_KEYS = ("note", "notes", "keterangan", "ket", "catatan", "remark", "remarks")
NAME_KEYS = ("name", "nama")
DEPT_KEYS = ("department", "dept", "departemen", "bagian", "divisi")


@dataclass(frozen=True)
class NoteRow:
    """One row of the report. machine_id / name / dept work like a Punch, so the machine rules apply."""
    machine_id: str
    date: Date
    name: str = ""
    dept: str = ""
    text: str = ""
    color: str = ""                  # "FFFF00", or "" (no fill / not readable)
    code: str = ""                   # the legend label for the colour ("UL"), or ""

    @property
    def has_note(self):
        return bool(self.text or self.color)


@dataclass
class NoteFile:
    rows: list                       # [NoteRow], file order, with and without notes
    period: tuple                    # (start, end): the report's own period, else the dates found
    period_in_file: bool             # True when the report states its period ("Stat.Date: ... ~ ...")
    sheet: str = ""
    legend: dict = field(default_factory=dict)
    unreadable: int = 0              # rows with an ID whose date could not be read
    outside: int = 0                 # rows dated outside the report period (left out)
    repeated: list = field(default_factory=list)   # [(machine id, name, date)] written on two rows or more
    colors_read: bool = True         # False for .xls: colours are not read from old Excel files

    @property
    def notes(self):
        return [r for r in self.rows if r.has_note]


# ── reading the workbook ──
def _fill_hex(cell):
    """'RRGGBB' of a solid fill given as RGB, else "" (theme / indexed colours are not codes we can name)."""
    fill = getattr(cell, "fill", None)
    if fill is None or fill.fill_type != "solid":
        return ""
    color = fill.fgColor
    rgb = getattr(color, "rgb", None) if getattr(color, "type", None) == "rgb" else None
    return rgb[-6:].upper() if isinstance(rgb, str) and len(rgb) >= 6 else ""


def read_xlsx_with_fills(data):
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise FileError("File Excel tidak bisa dibuka. Pastikan formatnya .xlsx.")
    sheets = []
    for ws in wb.worksheets:
        values, fills = [], []
        for row in ws.iter_rows():
            values.append([getattr(c, "value", None) for c in row])
            fills.append([_fill_hex(c) for c in row])
        sheets.append((ws.title, values, fills))
    return sheets


def read_note_sheets(filename, data):
    """-> ([(sheet name, values, fills)], colors_read)."""
    name = (filename or "").lower()
    if is_legacy_excel(name, data):
        try:
            sheets = read_legacy_excel(data)
        except LegacyExcelError as err:
            raise FileError(str(err))
        if sheets is None:
            raise FileError("Catatan hanya bisa dibaca dari file Excel (.xlsx atau .xls).")
        return [(n, rows, [[""] * len(r) for r in rows]) for n, rows in sheets], False
    if name.endswith(".xlsx") or data[:2] == b"PK":
        return read_xlsx_with_fills(data), True
    raise FileError("Catatan hanya bisa dibaca dari file Excel (.xlsx atau .xls).")


# ── the colour legend ──
def read_legend(sheets):
    """{"FFFF00": "UL", ...}: a short label in a filled cell in the first rows of any sheet. First one wins."""
    legend = {}
    for _, values, fills in sheets:
        for r in range(min(LEGEND_ROWS, len(values))):
            for c, v in enumerate(values[r]):
                color = fills[r][c] if c < len(fills[r]) else ""
                if not color or color in NOT_A_CODE or not isinstance(v, str):
                    continue
                label = v.strip()
                if LEGEND_LABEL.fullmatch(label):
                    legend.setdefault(color, label)
    return legend


# ── the notes sheet ──
def _column(keys, wanted):
    """Index of the first header cell matching the wanted names, in the order of preference."""
    for w in wanted:
        if w in keys:
            return keys.index(w)
    return None


def find_header(values):
    """(row index, {"id", "date", "note", "name", "dept": column}) of the column header, or None."""
    for r, row in enumerate(values[:HEADER_ROWS]):
        keys = [_key(_cell_text(v)) for v in row]
        cols = {k: _column(keys, w) for k, w in (("id", ID_KEYS), ("date", DATE_KEYS), ("note", NOTE_KEYS),
                                                 ("name", NAME_KEYS), ("dept", DEPT_KEYS))}
        if cols["id"] is not None and cols["date"] is not None and cols["note"] is not None:
            return r, cols
    return None


def _cell(row, col):
    return row[col] if col is not None and col < len(row) else None


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, Date):
        return v
    text = _cell_text(v).strip()
    if not text:
        return None
    try:
        return parse_date(text.split()[0])
    except ValueError:
        return None


def _note_text(v):
    text = re.sub(r"\s+", " ", _cell_text(v)).strip()
    return text[:MAX_TEXT]


def _count_notes(values, fills):
    found = find_header(values)
    if found is None:
        return None
    r0, cols = found
    n = 0
    for r in range(r0 + 1, len(values)):
        row = values[r]
        if not clean_id(_cell(row, cols["id"])):
            continue
        fill = fills[r][cols["note"]] if cols["note"] < len(fills[r]) else ""
        if _note_text(_cell(row, cols["note"])) or (fill and fill not in NOT_A_CODE):
            n += 1
    return n


def pick_note_sheet(sheets):
    """(name, values, fills) of the sheet with an ID / Date / Note header and the most notes, or None."""
    best, best_n = None, -1
    for sheet in sheets:
        n = _count_notes(sheet[1], sheet[2])
        if n is not None and n > best_n:
            best, best_n = sheet, n
    return best


def parse_note_sheet(values, fills, legend=None, name=""):
    legend = legend or {}
    found = find_header(values)
    if found is None:
        raise FileError("Kolom ID, Date dan Note tidak ditemukan. Pilih file rekap pengecualian "
                        "(mis. sheet \"ESR Edit\" / Exception Statistic Report).")
    r0, cols = found
    by_label = {label.casefold(): label for label in legend.values()}
    stated = _find_period(values[:r0 + 1])
    rows, unreadable = [], 0
    for r in range(r0 + 1, len(values)):
        row = values[r]
        machine_id = clean_id(_cell(row, cols["id"]))
        if not machine_id or _key(machine_id) in ID_KEYS:       # a blank line, a second header line
            continue
        day = _as_date(_cell(row, cols["date"]))
        if day is None:
            unreadable += 1
            continue
        text = _note_text(_cell(row, cols["note"]))
        color = fills[r][cols["note"]] if cols["note"] < len(fills[r]) else ""
        color = "" if color in NOT_A_CODE else color
        code = legend.get(color, "") or by_label.get(text.casefold(), "")     # "UL" typed with no colour
        rows.append(NoteRow(machine_id=machine_id, date=day, name=_cell_text(_cell(row, cols["name"])).strip(),
                            dept=_cell_text(_cell(row, cols["dept"])).strip(), text=text, color=color, code=code))
    if not rows:
        raise FileError("Tidak ada baris yang terbaca di bawah judul kolom (ID, Date, Note).")
    if stated is not None:
        period = stated
        inside = [x for x in rows if period[0] <= x.date <= period[1]]
        outside = len(rows) - len(inside)
        rows = inside
    else:
        dates = [x.date for x in rows]
        period, outside = (min(dates), max(dates)), 0
    seen = Counter((x.machine_id, x.dept.casefold(), x.date) for x in rows)
    repeated = OrderedDict()
    for x in rows:
        if seen[(x.machine_id, x.dept.casefold(), x.date)] > 1:
            repeated.setdefault((x.machine_id, x.dept.casefold(), x.date), (x.machine_id, x.name, x.date))
    return NoteFile(rows=rows, period=period, period_in_file=stated is not None, sheet=name, legend=dict(legend),
                    unreadable=unreadable, outside=outside, repeated=list(repeated.values()))


def read_notes(filename, data):
    sheets, colors_read = read_note_sheets(filename, data)
    sheet = pick_note_sheet(sheets)
    if sheet is None:
        raise FileError("Kolom ID, Date dan Note tidak ditemukan di file ini. Pilih file rekap pengecualian "
                        "(mis. sheet \"ESR Edit\" / Exception Statistic Report).")
    result = parse_note_sheet(sheet[1], sheet[2], read_legend(sheets), sheet[0])
    result.colors_read = colors_read
    if not result.notes:
        raise FileError(f"Sheet \"{sheet[0]}\" belum berisi catatan (kolom Note kosong). File langsung dari mesin "
                        f"memang belum ada catatannya: pilih file rekap yang sudah diisi HR.")
    return result
