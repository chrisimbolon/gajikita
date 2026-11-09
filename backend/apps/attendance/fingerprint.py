# =============================================================================
# === backend/apps/attendance/fingerprint.py ===
# =============================================================================
"""
Reading fingerprint machine files (G9, 1 Nov 2026). Pure Python + openpyxl, no Django.

Three formats, recognised automatically:
  1. attlog.dat / 1_attlog.dat   downloaded from the machine to a flash disk (ZKTeco and the
                                 many brands built on it: Solution, Fingerspot...). One tap per line:
                                 "  15\t2026-09-26 07:14:21\t1\t0\t1\t0"
  2. CSV / TXT                   any export with a header: an ID column (No / ID / AC-No / User ID / PIN)
                                 and either a date-time column, or separate date and time columns.
  3. Attendance Record Report    the Excel grid from the machine's software ("Att.log report"
     (.xlsx)                     sheet): "Att. Time 2026-09-26 ~ 2026-10-25", one column per day,
                                 a block per person ("ID: 15  Name: Eko") with that day's taps
                                 stacked in one cell. Also old .xls files (G12a): real Excel 97-2003,
                                 an HTML table or text saved as .xls. With several sheets (Schedule
                                 Infor., Att. Stat., Att.log report...) the one with the clock times is read.
                                 G12f-a: taps in a cell may have no separator at all ("07:5917:03",
                                 how DKCB's machine writes them); the grid sheet (with its row of day
                                 numbers) is picked over an exception report; each tap keeps "Dept.:".

Every format becomes the same thing: Punch(machine_id, at, name). Then make_sessions() turns
one person's punches into working sessions: first tap = Masuk, last tap = Pulang, double
taps merged, a night shift kept on the date it started.
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date as Date, datetime, time, timedelta

from apps.core.legacy_excel import LegacyExcelError, is_legacy_excel, read_legacy_excel

DOUBLE_TAP = timedelta(minutes=3)        # taps this close together are one tap
MAX_SESSION = timedelta(hours=16)        # a tap more than 16 h after the session's first tap starts a new one
MIN_WORKED = timedelta(minutes=30)       # a last tap within 30 min of the first is not a clock-out
# G12c: shift-aware pairing, when the employee has a shift
START_EARLY = timedelta(hours=2)         # a clock-in can come this long before the shift starts ...
START_LATE = timedelta(hours=5)          # ... or this long after it (e.g. Pagi 08:00: 06:00 - 13:00)
NEW_DAY_AFTER = timedelta(hours=6)       # a tap in that window opens a new day only this long after the last clock-in
MAX_SHIFT_SESSION = timedelta(hours=24)  # any other tap closes the open day, up to 24 h after its clock-in


class FileError(Exception):
    """A file GajiKita can't read, with a message HR can act on."""


@dataclass(frozen=True)
class Punch:
    machine_id: str
    at: datetime                         # naive, the machine's local time
    name: str = ""
    dept: str = ""                       # G12f-a: "Dept.:" of the grid block (DKCB / Staf / Manager)


@dataclass
class Session:
    work_date: Date
    clock_in: datetime
    clock_out: datetime = None
    taps: int = 1
    ignored: list = field(default_factory=list)   # taps between in and out (kept for the record)


def clean_id(value):
    """'0015', 15, 15.0 -> '15'; ' ab ' -> 'ab'. Machine IDs are compared as text without leading zeros."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text.lstrip("0") or ("0" if text else "")


# ── 1. attlog.dat ──
DAT_LINE = re.compile(r"^\s*(\S+)\s+(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}(?::\d{2})?)")


def parse_dat(text):
    punches, bad = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        m = DAT_LINE.match(line)
        if not m:
            bad += 1
            continue
        t = m.group(3) if m.group(3).count(":") == 2 else m.group(3) + ":00"
        punches.append(Punch(clean_id(m.group(1)), datetime.fromisoformat(f"{m.group(2)} {t.zfill(8)}")))
    if not punches:
        raise FileError("Tidak ada baris absen yang terbaca di file .dat ini.")
    return punches, bad


# ── 2. CSV / TXT with a header ──
ID_HEADERS = {"id", "no", "acno", "userid", "pin", "enno", "nokaryawan", "idkaryawan", "idmesin", "badgenumber",
              "personid", "employeeid", "nik"}
NAME_HEADERS = {"name", "nama", "namakaryawan", "username"}
DATETIME_HEADERS = {"datetime", "time", "waktu", "checktime", "punchtime", "tanggaljam", "jam", "datetimeabsen",
                    "attendancetime"}
DATE_HEADERS = {"date", "tanggal", "tgl"}
TIME_ONLY_HEADERS = {"time", "jam", "waktu"}


def _key(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y", "%m/%d/%Y")


def parse_datetime(text):
    """'2026-09-26 07:14:21', '26/09/2026 07:14', '26-09-2026 7:14' -> datetime (day before month)."""
    text = str(text or "").strip()
    m = re.match(r"^(\S+)[ T]+(\d{1,2}:\d{2}(?::\d{2})?)\s*(AM|PM|am|pm)?$", text)
    if not m:
        raise ValueError(text)
    day = parse_date(m.group(1))
    hhmm = [int(x) for x in m.group(2).split(":")]
    hour = hhmm[0]
    if m.group(3):
        hour = hour % 12 + (12 if m.group(3).lower() == "pm" else 0)
    return datetime(day.year, day.month, day.day, hour, hhmm[1], hhmm[2] if len(hhmm) > 2 else 0)


def parse_date(text):
    text = str(text).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(text)


def parse_csv(text):
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    header_at = next((i for i, r in enumerate(rows[:10]) if any(_key(c) in ID_HEADERS for c in r)), None)
    if header_at is None:
        raise FileError("Kolom ID karyawan tidak ditemukan. Baris judul harus punya kolom seperti No / ID / AC-No / User ID.")
    header = [_key(c) for c in rows[header_at]]
    find = lambda names: next((i for i, h in enumerate(header) if h in names), None)
    i_id, i_name = find(ID_HEADERS), find(NAME_HEADERS)
    i_date = find(DATE_HEADERS)
    i_dt = find(DATETIME_HEADERS) if i_date is None else find(TIME_ONLY_HEADERS)
    if i_dt is None:
        raise FileError("Kolom waktu absen tidak ditemukan. Perlu kolom tanggal-jam (mis. \"Time\") atau kolom Tanggal + Jam.")
    punches, bad = [], 0
    for r in rows[header_at + 1:]:
        if not r or len(r) <= max(i_id, i_dt, i_date or 0) or not str(r[i_id]).strip():
            continue
        try:
            when = parse_datetime(f"{r[i_date]} {r[i_dt]}" if i_date is not None else r[i_dt])
        except ValueError:
            bad += 1
            continue
        punches.append(Punch(clean_id(r[i_id]), when, (r[i_name].strip() if i_name is not None else "")))
    if not punches:
        raise FileError("Tidak ada baris absen yang terbaca. Periksa format tanggal dan jam di file.")
    return punches, bad


# ── 3. Attendance Record Report grid (.xlsx / .xls) ──
RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")
# G12f-a: one cell holds all of a day's taps. DKCB's machine writes them with NO separator
# ("07:5917:03", double taps "07:1407:1417:0017:00"); other exports use a line break or a space.
# So the pattern has no word boundaries: it reads one HH:MM after the other. Seconds are dropped.
TIME_IN_CELL = re.compile(r"(\d{1,2}):([0-5]\d)(?::[0-5]\d)?")
MIN_DAY_COLUMNS = 7                      # a real day-number row covers at least a week


def _cell_text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (datetime, time)):
        return v.strftime("%H:%M")
    return str(v)


def taps_in_cell(value):
    """
    One grid cell -> ([(hour, minute), ...], unread).

    "07:5917:03", "07:59\\n17:03", "07:59 17:03" and "07:59:12 17:03:40" all give [(7, 59), (17, 3)].
    Codes HR types instead of taps ("UL", "CT", "sdh tdk join") give no taps and are not unread.
    unread is True when something time-like is left that we could not read ("7:5", "25:10"), so
    the import can say so instead of losing a tap without a word.
    """
    text = _cell_text(value)
    taps, unread = [], False
    for m in TIME_IN_CELL.finditer(text):
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour < 24:
            taps.append((hour, minute))
        else:
            unread = True
    if ":" in TIME_IN_CELL.sub(" ", text):
        unread = True
    return taps, unread


def _find_period(rows):
    """(start, end) from "Att. Time 2026-09-26 ~ 2026-10-25" in the first rows, or None."""
    for r in rows[:8]:
        m = RANGE.search(" ".join(_cell_text(c) for c in r))
        if m:
            try:
                start, end = Date.fromisoformat(m.group(1)), Date.fromisoformat(m.group(2))
            except ValueError:
                return None
            return (start, end) if start <= end else None
    return None


def _day_number(c):
    """A cell of the day-number row -> 1..31, or None. Booleans and 4.5 (overtime hours) are not days."""
    if isinstance(c, bool):
        return None
    if isinstance(c, (int, float)):
        return int(c) if float(c).is_integer() and 1 <= c <= 31 else None
    if isinstance(c, str) and c.strip().isdigit() and 1 <= int(c.strip()) <= 31:
        return int(c.strip())
    return None


def _find_day_cols(rows, start, end):
    """
    {column index: date} from the row of day numbers (26, 27, ... 25) under the title. The row's
    first number must be the period's first day; walk forward a day per column, a new month
    whenever the number drops, skipping dates whose column is missing. {} if there is no such row.
    """
    for r in rows[:12]:
        nums = [(i, n) for i, n in ((i, _day_number(c)) for i, c in enumerate(r)) if n is not None]
        if len(nums) < MIN_DAY_COLUMNS or nums[0][1] != start.day:
            continue
        day_cols, current = {}, start
        for k, (i, n) in enumerate(nums):
            if k:
                current += timedelta(days=1)
                while current.day != n and current <= end:      # columns skipped: next date with this number
                    current += timedelta(days=1)
            if current > end:
                break
            day_cols[i] = current
        if len(day_cols) >= MIN_DAY_COLUMNS:
            return day_cols
    return {}


def _texts(row):
    return [_cell_text(c).strip() for c in (row or [])]


def _is_id_row(texts):
    return any(re.fullmatch(r"ID\s*[:：]?", t, re.I) or re.match(r"^ID\s*[:：]\s*\S", t, re.I) for t in texts)


def _label_value(texts, labels):
    """
    The value after a label in an ID row: in the same cell ("Name: Eko") or the next filled cell
    ("Name:" | "Eko"). "" when the value is missing (the next filled cell is the next label).
    """
    for k, t in enumerate(texts):
        m = re.match(rf"^(?:{labels})\s*[:：]\s*(.+)$", t, re.I)
        value = None
        if m:
            value = m.group(1).strip()
        elif re.fullmatch(rf"(?:{labels})\s*[:：]?", t, re.I):
            value = next((x for x in texts[k + 1:] if x), "")
        if value is not None:
            return "" if value.endswith((":", "：")) else value
    return ""


def parse_record_grid(rows):
    """
    rows: one sheet as lists of cell values -> (punches, unread_cells).

    Works for the machine's own "Att.log report" (a block = ID row + taps row) and for Anthony's
    edited copy "ASR Edit" (ID row + taps row + his overtime row, a legend, OT/SR/UM columns).
    Each punch carries the name and the "Dept.:" written in the block (G12f-a).
    """
    period = _find_period(rows)
    if period is None:
        raise FileError("Periode laporan (mis. \"Att. Time 2026-09-26 ~ 2026-10-25\") tidak ditemukan di sheet.")
    day_cols = _find_day_cols(rows, *period)
    if not day_cols:
        raise FileError("Baris tanggal (26, 27, 28 ...) tidak ditemukan di bawah judul laporan.")

    punches, unread = [], 0
    i = 0
    while i < len(rows):
        texts = _texts(rows[i])
        if not _is_id_row(texts):
            i += 1
            continue
        raw_id = _label_value(texts, "ID")
        machine_id = clean_id(raw_id.split()[0]) if raw_id else ""
        name = _label_value(texts, "Name|Nama")
        dept = _label_value(texts, r"Dept\.?|Department|Departemen|Bagian")
        taps_row = rows[i + 1] if i + 1 < len(rows) else None
        if taps_row is None or _is_id_row(_texts(taps_row)):
            i += 1                               # no taps row at all: the next row is the next person
            continue
        if machine_id:
            for col, day in day_cols.items():
                if col < len(taps_row):
                    taps, bad = taps_in_cell(taps_row[col])
                    unread += bad
                    for hh, mm in taps:
                        punches.append(Punch(machine_id, datetime.combine(day, time(hh, mm)), name, dept))
        i += 2
    if not punches:
        raise FileError("Tidak ada jam absen yang terbaca di laporan ini.")
    return punches, unread


def read_xlsx_sheets(data):
    """Every sheet of an .xlsx as (name, rows)."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise FileError("File Excel tidak bisa dibuka. Pastikan formatnya .xlsx.")
    return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]


def read_xlsx_rows(data):
    return pick_sheet(read_xlsx_sheets(data))


def _sheet_score(rows):
    """
    Higher is better: (has the report period, has a day-number row, clock times, rows).

    A machine export has several sheets that all show the period (Schedule Infor., Att. Stat.,
    Att.log report, Exception Stat.). Only the Att.log report holds every tap, and only it (and
    Schedule Infor.) has the row of day numbers. G12f-a: the day row comes before the count of
    times, because an exception report can hold more times than the grid (Anthony's "ESR Edit").
    """
    period = _find_period(rows)
    grid = period is not None and bool(_find_day_cols(rows, *period))
    times = sum(len(TIME_IN_CELL.findall(c)) if isinstance(c, str) else 1
                for r in rows[:400] for c in r if isinstance(c, (str, time)))
    return (period is not None, grid, times, len(rows))


def pick_named_sheet(sheets):
    """(name, rows) of the sheet to read; ("", []) when there are none."""
    best, best_score = ("", []), None
    for name, rows in sheets:
        score = _sheet_score(rows)
        if best_score is None or score > best_score:
            best, best_score = (name, rows), score
    return best


def pick_sheet(sheets):
    """The rows of the sheet to read (G12a)."""
    return pick_named_sheet(sheets)[1]


def _from_rows(rows, label, sheet=""):
    if _find_period(rows) is not None:
        punches, bad = parse_record_grid(rows)
        where = f'{label}, sheet "{sheet}"' if sheet else label
        return punches, bad, f"Attendance Record Report ({where})"
    text = "\n".join(";".join(_cell_text(c) if not isinstance(c, datetime) else c.strftime("%Y-%m-%d %H:%M:%S")
                              for c in r) for r in rows)
    punches, bad = parse_csv(text)
    return punches, bad, f"Tabel {label}"


def _from_sheets(sheets, label):
    """Read the right sheet; name it in the label when the file has several (G12f-a)."""
    name, rows = pick_named_sheet(sheets)
    return _from_rows(rows, label, name if len(sheets) > 1 else "")


# ── which format? ──
def read_punches(filename, data):
    """Returns (punches, unreadable_line_count, format_label)."""
    name = (filename or "").lower()
    if is_legacy_excel(name, data):                       # G12a: old .xls from the machine software
        try:
            sheets = read_legacy_excel(data)
        except LegacyExcelError as err:
            raise FileError(str(err))
        if sheets is not None:
            return _from_sheets(sheets, "Excel .xls")
        # text saved with an .xls name: read below like any text file
    elif name.endswith(".xlsx") or data[:2] == b"PK":
        return _from_sheets(read_xlsx_sheets(data), "Excel")
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = data.decode(enc)
            if "\x00" in text:
                continue
            break
        except UnicodeDecodeError:
            continue
    else:
        raise FileError("File tidak bisa dibaca sebagai teks.")
    first = next((l for l in text.splitlines() if l.strip()), "")
    if DAT_LINE.match(first):
        punches, bad = parse_dat(text)
        return punches, bad, "attlog.dat (download dari mesin)"
    punches, bad = parse_csv(text)
    return punches, bad, "CSV / teks"


# ── punches -> working sessions ──
def _start_day(t, shift_start):
    """The date whose shift this tap could be the clock-in of, or None."""
    for d in (t.date(), t.date() + timedelta(days=1), t.date() - timedelta(days=1)):
        start = datetime.combine(d, shift_start)
        if start - START_EARLY <= t <= start + START_LATE:
            return d
    return None


def make_sessions(punch_times, shift_start=None):
    """
    One person's tap times (any order) -> sessions. First tap = in, last = out.

    With the employee's shift start (G12c) the taps are paired around the shift instead of by
    time alone: a tap near the start (06:00 - 13:00 for a 08:00 shift) opens a new day, any other
    tap closes the open one, up to 24 h after its clock-in. So a concrete-pump day of 08:11 -> 02:01
    the next night stays one day, and the next morning's 12:27 starts the next one. Without a
    shift: the old rule, a new session when a tap is more than 16 h after the first one.
    """
    taps = []
    for t in sorted(set(punch_times)):
        if taps and t - taps[-1] <= DOUBLE_TAP:
            continue                       # a double tap
        taps.append(t)
    if shift_start is not None:
        return _sessions_around_shift(taps, shift_start)
    sessions = []
    for t in taps:
        s = sessions[-1] if sessions else None
        if s is not None and t - s.clock_in <= MAX_SESSION:
            if s.clock_out is not None:
                s.ignored.append(s.clock_out)
            s.clock_out = t
            s.taps += 1
        else:
            sessions.append(Session(work_date=t.date(), clock_in=t))
    return _drop_short_outs(sessions)


def _sessions_around_shift(taps, shift_start):
    sessions = []
    for t in taps:
        s = sessions[-1] if sessions else None
        day = _start_day(t, shift_start)
        span = t - s.clock_in if s is not None else None
        opens_new_day = day is not None and span is not None and span >= NEW_DAY_AFTER
        if s is not None and not opens_new_day and span <= MAX_SHIFT_SESSION:
            if s.clock_out is not None:
                s.ignored.append(s.clock_out)
            s.clock_out = t
            s.taps += 1
        else:
            sessions.append(Session(work_date=day or t.date(), clock_in=t))
    return _drop_short_outs(sessions)


def _drop_short_outs(sessions):
    for s in sessions:
        if s.clock_out is not None and s.clock_out - s.clock_in < MIN_WORKED:
            s.ignored.append(s.clock_out)
            s.clock_out = None
    return sessions
