# =============================================================================
# === backend/apps/attendance/overtime_sheet.py ===
# =============================================================================
"""
HR's overtime per person per day, read from the recap HR keeps beside the machine (G17-8, 17 Nov 2026).
Pure Python + openpyxl, no Django.

DKCB's HR edits the machine's "Attendance Record Report" grid ("ASR Edit"): under each person's row of taps
he writes the overtime he pays that day, in hours (3.5, 10), and at the end of the row the totals OT / SR / UM.
That row is his decision: the taps checked against the paper SPL, rounded his way (Note sheet: 1-15 min = 0,
16-45 = ½ hour, 46-60 = 1 hour). Arief's row adds up to 88, exactly the book.

  ot_minutes(value)            one cell -> minutes (None = empty) or BAD
  parse_overtime_grid(rows)    one sheet -> OvertimeFile, or None when it has no overtime rows
  read_overtime(filename, data)   the workbook -> OvertimeFile of the sheet with the most overtime rows

A block = ID row + taps row + (overtime row). The machine's own export has no overtime row: that person is
"not in the file" for overtime and is never touched. An overtime row may be all empty (no overtime that month):
the person IS in the file and every proposal of the taps becomes "no overtime".
"""
import re
from dataclasses import dataclass, field

from apps.core.legacy_excel import LegacyExcelError, is_legacy_excel, read_legacy_excel

from .fingerprint import (FileError, TIME_IN_CELL, _cell_text, _find_day_cols, _find_period, _is_id_row,
                          _label_value, _texts, clean_id, read_xlsx_sheets)

BAD = "bad"
MAX_HOURS = 24
MAX_TOTAL_HOURS = 31 * 24          # the total at the end of the row
TOTAL_LABELS = {"ot", "lembur", "jamlembur", "totallembur", "overtime", "totalot"}
DECIMAL = re.compile(r"(\d{1,3})(?:[.,](\d{1,3}))?")                     # 3 · 3.5 · 3,5
CLOCK = re.compile(r"(\d{1,2})\s*(?::|j|jam)\s*(\d{1,2})\s*(?:m|mnt|menit)?")   # 3:30 · 3j30 · 3 jam 30 mnt
EMPTY = {"", "-", "–", "—", "0:00"}


def ot_minutes(value, max_hours=MAX_HOURS):
    """A cell of the overtime row -> whole minutes, None (empty), or BAD (something we can't read as hours)."""
    if value is None or isinstance(value, bool):
        return None if value is None else BAD
    if isinstance(value, (int, float)):
        hours = float(value)
    else:
        text = _cell_text(value).strip().lower()
        if text in EMPTY:
            return None if text != "0:00" else 0
        text = text.replace("jam", "j").replace(" ", "")
        m = CLOCK.fullmatch(text)
        if m and int(m.group(2)) < 60:
            hours = int(m.group(1)) + int(m.group(2)) / 60
        else:
            m = DECIMAL.fullmatch(text)
            if not m:
                return BAD
            hours = float(f"{m.group(1)}.{m.group(2) or 0}")
    if hours < 0 or hours > max_hours:
        return BAD
    return int(round(hours * 60))


@dataclass
class OtBlock:
    """One person in the grid. machine_id / name / dept work like a Punch, so the machine rules apply."""
    machine_id: str
    name: str = ""
    dept: str = ""
    has_row: bool = False             # an overtime row is under the taps
    minutes: dict = field(default_factory=dict)        # {date: minutes > 0}
    unreadable: list = field(default_factory=list)     # [(date, text)]
    total_file: int = None            # the total HR wrote at the end of the row, in minutes (None = none)

    @property
    def total(self):
        return sum(self.minutes.values())


@dataclass
class OvertimeFile:
    blocks: list                      # [OtBlock] in file order (with and without an overtime row)
    period: tuple                     # (start, end) stated in the report
    sheet: str = ""

    @property
    def people(self):
        return [b for b in self.blocks if b.has_row]


def _total_col(rows, day_cols):
    last = max(day_cols)
    for r in rows[:12]:
        for i, v in enumerate(r):
            if i > last and re.sub(r"[\s.]", "", _cell_text(v)).casefold() in TOTAL_LABELS:
                return i
    return None


def _looks_like_taps(row, day_cols):
    """A row of clock times (the next person's taps, or a second taps row) is not an overtime row."""
    times = sum(len(TIME_IN_CELL.findall(_cell_text(row[c]))) for c in day_cols if c < len(row))
    return times >= 2 and any(len(TIME_IN_CELL.findall(_cell_text(row[c]))) >= 2 for c in day_cols if c < len(row))


def _overtime_row(row, day_cols, total_col):
    """True when the row under the taps holds overtime: a number in a day column or in the total column."""
    if row is None or _is_id_row(_texts(row)) or _looks_like_taps(row, day_cols):
        return False
    cols = list(day_cols) + ([total_col] if total_col is not None else [])
    return any(c < len(row) and ot_minutes(row[c], MAX_TOTAL_HOURS) not in (None, BAD) for c in cols)


def parse_overtime_grid(rows, name=""):
    """One sheet -> OvertimeFile, or None when it is not a record grid with overtime rows."""
    period = _find_period(rows)
    if period is None:
        return None
    day_cols = _find_day_cols(rows, *period)
    if not day_cols:
        return None
    total_col = _total_col(rows, day_cols)
    blocks, i = [], 0
    while i < len(rows):
        texts = _texts(rows[i])
        if not _is_id_row(texts):
            i += 1
            continue
        raw_id = _label_value(texts, "ID")
        block = OtBlock(machine_id=clean_id(raw_id.split()[0]) if raw_id else "",
                        name=_label_value(texts, "Name|Nama"), dept=_label_value(texts, r"Dept\.?|Department|Departemen|Bagian"))
        taps = rows[i + 1] if i + 1 < len(rows) else None
        if taps is None or _is_id_row(_texts(taps)):
            i += 1
            if block.machine_id:
                blocks.append(block)
            continue
        ot = rows[i + 2] if i + 2 < len(rows) else None
        if _overtime_row(ot, day_cols, total_col):
            block.has_row = True
            for col, day in day_cols.items():
                v = ot[col] if col < len(ot) else None
                m = ot_minutes(v)
                if m == BAD:
                    block.unreadable.append((day, _cell_text(v).strip()[:40]))
                elif m:
                    block.minutes[day] = m
            if total_col is not None and total_col < len(ot):
                t = ot_minutes(ot[total_col], max_hours=MAX_TOTAL_HOURS)
                block.total_file = t if t not in (None, BAD) else None
            i += 3
        else:
            i += 2
        if block.machine_id:
            blocks.append(block)
    if not any(b.has_row for b in blocks):
        return None
    return OvertimeFile(blocks=blocks, period=period, sheet=name)


def read_overtime(filename, data):
    name = (filename or "").lower()
    if is_legacy_excel(name, data):
        try:
            sheets = read_legacy_excel(data)
        except LegacyExcelError as err:
            raise FileError(str(err))
        if sheets is None:
            raise FileError("Lembur hanya bisa dibaca dari file Excel (.xlsx atau .xls).")
    elif name.endswith(".xlsx") or data[:2] == b"PK":
        sheets = read_xlsx_sheets(data)
    else:
        raise FileError("Lembur hanya bisa dibaca dari file Excel (.xlsx atau .xls).")
    best = None
    for sheet_name, rows in sheets:
        of = parse_overtime_grid(rows, sheet_name)
        if of is not None and (best is None or len(of.people) > len(best.people)):
            best = of
    if best is None:
        raise FileError("Tidak ada baris lembur di file ini. SeeGaji mencari laporan absen (Attendance Record Report) "
                        "yang di bawah jam absen tiap orang ada satu baris jam lembur per hari, seperti sheet \"ASR Edit\". "
                        "File langsung dari mesin belum punya baris itu.")
    return best
